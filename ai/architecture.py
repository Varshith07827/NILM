"""Declarative description of the NILM classifier.

The network is a MobileNetV3-inspired convolutional classifier, shrunk to the
size of the problem.  It keeps the three ideas that make MobileNetV3 a good fit
for microcontroller inference:

* **Depthwise separable convolutions** -- a full KxK convolution is split into a
  per-channel spatial filter plus a 1x1 channel mixer, cutting multiply count by
  roughly a factor of K^2.
* **Inverted residual bottlenecks** -- expand to a wide channel space, do the
  cheap depthwise work there, then project back down, with a skip connection
  when the shapes line up.
* **Squeeze-and-excitation + hard-swish** -- cheap global channel attention and
  a piecewise-linear activation that needs no exponentials, which matters a lot
  on a device without an FPU-friendly ``exp``.

The input is not an image but a **feature-time tensor** of shape
``(SEQUENCE_LENGTH, NUM_FEATURES, 1)``: eight consecutive one-second windows
stacked against the 34 electrical features of each.  Convolving over that
rectangle lets the network learn both *what* a signature looks like and *how it
evolves* over the last eight seconds -- which is what separates a refrigerator
compressor kicking in from an air conditioner doing the same thing.

This module is the single source of truth for the topology.  Both the Keras
builder (:mod:`ai.model`) and the dependency-free NumPy runtime
(:mod:`ai.runtime`) are driven from the same spec, so the trained model and the
edge interpreter cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class ConvSpec:
    """A standard convolution + batch norm + activation."""

    name: str
    filters: int
    kernel: tuple[int, int]
    stride: tuple[int, int] = (1, 1)
    activation: Literal["hswish", "relu", "linear"] = "hswish"
    kind: Literal["conv"] = "conv"


@dataclass(frozen=True)
class BottleneckSpec:
    """An inverted residual bottleneck, optionally with squeeze-excitation."""

    name: str
    expand_filters: int
    out_filters: int
    kernel: tuple[int, int] = (3, 3)
    stride: tuple[int, int] = (1, 1)
    use_se: bool = True
    se_ratio: float = 0.25
    activation: Literal["hswish", "relu"] = "hswish"
    kind: Literal["bottleneck"] = "bottleneck"

    @property
    def has_residual_candidate(self) -> bool:
        """Residual is added when stride is 1 and channel counts match."""
        return self.stride == (1, 1)


@dataclass(frozen=True)
class DenseSpec:
    """Fully connected layer."""

    name: str
    units: int
    activation: Literal["hswish", "relu", "sigmoid", "linear"] = "hswish"
    dropout: float = 0.0
    kind: Literal["dense"] = "dense"


@dataclass(frozen=True)
class PoolSpec:
    """Global average pooling over the spatial dimensions."""

    name: str = "global_pool"
    kind: Literal["pool"] = "pool"


LayerSpec = ConvSpec | BottleneckSpec | PoolSpec | DenseSpec


@dataclass(frozen=True)
class ModelArchitecture:
    """Complete topology description."""

    name: str
    layers: tuple[LayerSpec, ...]
    #: Multi-label output: one independent sigmoid per appliance.
    output_activation: str = "sigmoid"

    def describe(self) -> list[str]:
        lines = []
        for layer in self.layers:
            if isinstance(layer, ConvSpec):
                lines.append(
                    f"{layer.name:<18} conv {layer.kernel} x{layer.filters} "
                    f"stride={layer.stride} act={layer.activation}"
                )
            elif isinstance(layer, BottleneckSpec):
                lines.append(
                    f"{layer.name:<18} bneck exp={layer.expand_filters} "
                    f"out={layer.out_filters} k={layer.kernel} "
                    f"stride={layer.stride} se={layer.use_se} act={layer.activation}"
                )
            elif isinstance(layer, PoolSpec):
                lines.append(f"{layer.name:<18} global average pool")
            else:
                lines.append(
                    f"{layer.name:<18} dense units={layer.units} "
                    f"act={layer.activation} dropout={layer.dropout}"
                )
        return lines


#: The production topology.
#:
#: Strides are asymmetric on purpose.  The feature axis (34 wide) carries far
#: more independent information than the time axis (8 deep), so downsampling
#: happens mostly along the feature axis and the time axis is left mostly
#: intact until the final pool.
NILM_MOBILENETV3_SMALL = ModelArchitecture(
    name="nilm-mobilenetv3-small",
    layers=(
        ConvSpec("stem", filters=16, kernel=(3, 3), stride=(1, 2), activation="hswish"),
        BottleneckSpec(
            "bneck1",
            expand_filters=48,
            out_filters=24,
            kernel=(3, 3),
            stride=(1, 2),
            use_se=False,
            activation="relu",
        ),
        BottleneckSpec(
            "bneck2",
            expand_filters=72,
            out_filters=24,
            kernel=(3, 3),
            stride=(1, 1),
            use_se=False,
            activation="relu",
        ),
        BottleneckSpec(
            "bneck3",
            expand_filters=96,
            out_filters=40,
            kernel=(3, 3),
            stride=(2, 2),
            use_se=True,
            activation="hswish",
        ),
        BottleneckSpec(
            "bneck4",
            expand_filters=120,
            out_filters=40,
            kernel=(3, 3),
            stride=(1, 1),
            use_se=True,
            activation="hswish",
        ),
        BottleneckSpec(
            "bneck5",
            expand_filters=144,
            out_filters=56,
            kernel=(3, 3),
            stride=(1, 1),
            use_se=True,
            activation="hswish",
        ),
        ConvSpec("head_conv", filters=192, kernel=(1, 1), activation="hswish"),
        PoolSpec("global_pool"),
        DenseSpec("fc1", units=128, activation="hswish", dropout=0.3),
        DenseSpec("logits", units=0, activation="linear"),  # units filled at build
    ),
)


def architecture_for(num_classes: int) -> ModelArchitecture:
    """Return the architecture with its output layer sized to the label set."""
    layers = list(NILM_MOBILENETV3_SMALL.layers)
    layers[-1] = DenseSpec("logits", units=num_classes, activation="linear")
    return ModelArchitecture(
        name=NILM_MOBILENETV3_SMALL.name,
        layers=tuple(layers),
        output_activation=NILM_MOBILENETV3_SMALL.output_activation,
    )


def same_padding(
    in_size: int, kernel: int, stride: int
) -> tuple[int, int]:
    """TensorFlow's asymmetric SAME padding rule.

    Reproduced exactly so the NumPy runtime matches Keras bit for bit rather
    than approximately.
    """
    out_size = -(-in_size // stride)  # ceil division
    pad_total = max((out_size - 1) * stride + kernel - in_size, 0)
    pad_before = pad_total // 2
    return pad_before, pad_total - pad_before
