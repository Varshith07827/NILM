"""Dependency-free NumPy inference kernel.

This is the edge deployment target.  It executes exactly the graph described in
:mod:`ai.architecture` using nothing but NumPy, reading folded weights out of a
single ``.npz`` file.

Why not just call TensorFlow?
-----------------------------
Importing TensorFlow costs roughly thirty seconds and several hundred megabytes
of RSS on this machine.  A one-second inference loop cannot pay that, and
neither could the ESP32 the project is modelled on -- which is the whole reason
TensorFlow Lite for Microcontrollers exists.  So the pipeline follows the same
path a real deployment does:

    train in TensorFlow  ->  quantise to TFLite  ->  run a tiny interpreter

The tiny interpreter here is Python instead of C++, but the arithmetic is the
same, the weights are the same, and the outputs are verified against both Keras
and the TFLite interpreter at export time (see :mod:`ai.export`).

Batch normalisation has already been folded into the preceding convolution at
export time, so this file contains no BN layer at all -- exactly the
optimisation a real edge converter performs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ai.architecture import (
    BottleneckSpec,
    ConvSpec,
    DenseSpec,
    ModelArchitecture,
    PoolSpec,
    architecture_for,
    same_padding,
)

# --------------------------------------------------------------------------- #
# Primitive operations
# --------------------------------------------------------------------------- #


def hard_swish(x: np.ndarray) -> np.ndarray:
    return x * np.clip(x + 3.0, 0.0, 6.0) / 6.0


def hard_sigmoid(x: np.ndarray) -> np.ndarray:
    return np.clip(x + 3.0, 0.0, 6.0) / 6.0


def relu(x: np.ndarray) -> np.ndarray:
    return np.maximum(x, 0.0)


def sigmoid(x: np.ndarray) -> np.ndarray:
    # Numerically stable for large-magnitude logits.
    out = np.empty_like(x)
    positive = x >= 0
    out[positive] = 1.0 / (1.0 + np.exp(-x[positive]))
    exp_x = np.exp(x[~positive])
    out[~positive] = exp_x / (1.0 + exp_x)
    return out


_ACTIVATIONS = {
    "hswish": hard_swish,
    "relu": relu,
    "sigmoid": sigmoid,
    "linear": lambda x: x,
}


def _pad_same(x: np.ndarray, kernel: tuple[int, int], stride: tuple[int, int]) -> np.ndarray:
    """Apply TensorFlow's asymmetric SAME padding."""
    top, bottom = same_padding(x.shape[1], kernel[0], stride[0])
    left, right = same_padding(x.shape[2], kernel[1], stride[1])
    if top == bottom == left == right == 0:
        return x
    return np.pad(x, ((0, 0), (top, bottom), (left, right), (0, 0)))


def conv2d(
    x: np.ndarray,
    weight: np.ndarray,
    bias: np.ndarray,
    stride: tuple[int, int] = (1, 1),
) -> np.ndarray:
    """SAME-padded 2-D convolution over NHWC input.

    Implemented as an accumulation over the ``kh * kw`` kernel taps, each of
    which is a single ``tensordot``.  For a 3x3 kernel that is nine dense
    matrix products -- far faster in NumPy than an explicit loop over pixels,
    and it avoids materialising a large im2col buffer.
    """
    kh, kw, _, out_channels = weight.shape
    stride_h, stride_w = stride
    padded = _pad_same(x, (kh, kw), stride)

    out_h = (padded.shape[1] - kh) // stride_h + 1
    out_w = (padded.shape[2] - kw) // stride_w + 1
    out = np.zeros((x.shape[0], out_h, out_w, out_channels), dtype=np.float32)

    for a in range(kh):
        rows = slice(a, a + (out_h - 1) * stride_h + 1, stride_h)
        for b in range(kw):
            cols = slice(b, b + (out_w - 1) * stride_w + 1, stride_w)
            patch = padded[:, rows, cols, :]
            out += np.tensordot(patch, weight[a, b], axes=([3], [0]))

    return out + bias


def depthwise_conv2d(
    x: np.ndarray,
    weight: np.ndarray,
    bias: np.ndarray,
    stride: tuple[int, int] = (1, 1),
) -> np.ndarray:
    """SAME-padded depthwise convolution (one spatial filter per channel)."""
    kh, kw, channels, multiplier = weight.shape
    assert multiplier == 1, "depth_multiplier > 1 is not used by this architecture"
    stride_h, stride_w = stride
    padded = _pad_same(x, (kh, kw), stride)

    out_h = (padded.shape[1] - kh) // stride_h + 1
    out_w = (padded.shape[2] - kw) // stride_w + 1
    out = np.zeros((x.shape[0], out_h, out_w, channels), dtype=np.float32)

    for a in range(kh):
        rows = slice(a, a + (out_h - 1) * stride_h + 1, stride_h)
        for b in range(kw):
            cols = slice(b, b + (out_w - 1) * stride_w + 1, stride_w)
            out += padded[:, rows, cols, :] * weight[a, b, :, 0]

    return out + bias


def global_average_pool(x: np.ndarray, keepdims: bool = False) -> np.ndarray:
    return x.mean(axis=(1, 2), keepdims=keepdims)


def dense(x: np.ndarray, weight: np.ndarray, bias: np.ndarray) -> np.ndarray:
    return x @ weight + bias


# --------------------------------------------------------------------------- #
# Graph execution
# --------------------------------------------------------------------------- #


@dataclass
class ModelBundle:
    """Everything the runtime needs: weights, normalisation and metadata."""

    weights: dict[str, np.ndarray]
    feature_mean: np.ndarray
    feature_std: np.ndarray
    appliance_ids: tuple[str, ...]
    feature_names: tuple[str, ...]
    sequence_length: int
    thresholds: np.ndarray
    metadata: dict

    @property
    def num_classes(self) -> int:
        return len(self.appliance_ids)

    @property
    def architecture(self) -> ModelArchitecture:
        return architecture_for(self.num_classes)

    @classmethod
    def load(cls, weights_path: str | Path, metadata_path: str | Path) -> "ModelBundle":
        archive = np.load(weights_path)
        weights = {key: archive[key].astype(np.float32) for key in archive.files}
        metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
        return cls(
            weights=weights,
            feature_mean=weights["norm.mean"],
            feature_std=weights["norm.std"],
            appliance_ids=tuple(metadata["appliance_ids"]),
            feature_names=tuple(metadata["feature_names"]),
            sequence_length=int(metadata["sequence_length"]),
            thresholds=np.asarray(metadata["thresholds"], dtype=np.float32),
            metadata=metadata,
        )


class NumpyInterpreter:
    """Executes the architecture graph on folded float32 weights."""

    def __init__(self, bundle: ModelBundle) -> None:
        self.bundle = bundle
        self._architecture = bundle.architecture

    # -- block implementations ---------------------------------------- #

    def _run_bottleneck(self, x: np.ndarray, spec: BottleneckSpec) -> np.ndarray:
        weights = self.bundle.weights
        shortcut = x
        in_channels = x.shape[-1]
        activation = _ACTIVATIONS[spec.activation]

        x = conv2d(
            x,
            weights[f"{spec.name}.expand.W"],
            weights[f"{spec.name}.expand.b"],
            stride=(1, 1),
        )
        x = activation(x)

        x = depthwise_conv2d(
            x,
            weights[f"{spec.name}.depthwise.W"],
            weights[f"{spec.name}.depthwise.b"],
            stride=spec.stride,
        )
        x = activation(x)

        if spec.use_se:
            pooled = global_average_pool(x, keepdims=True)
            se = conv2d(
                pooled,
                weights[f"{spec.name}.se_reduce.W"],
                weights[f"{spec.name}.se_reduce.b"],
            )
            se = relu(se)
            se = conv2d(
                se,
                weights[f"{spec.name}.se_expand.W"],
                weights[f"{spec.name}.se_expand.b"],
            )
            x = x * hard_sigmoid(se)

        # Linear bottleneck -- deliberately no activation here.
        x = conv2d(
            x,
            weights[f"{spec.name}.project.W"],
            weights[f"{spec.name}.project.b"],
            stride=(1, 1),
        )

        if spec.has_residual_candidate and in_channels == spec.out_filters:
            x = x + shortcut
        return x

    # -- forward pass --------------------------------------------------- #

    def forward(self, x: np.ndarray) -> np.ndarray:
        """Run the graph on a batch of shape ``(N, seq_len, n_features, 1)``.

        Returns raw sigmoid probabilities of shape ``(N, num_classes)``.
        """
        weights = self.bundle.weights
        x = np.ascontiguousarray(x, dtype=np.float32)

        for spec in self._architecture.layers:
            if isinstance(spec, ConvSpec):
                x = conv2d(
                    x,
                    weights[f"{spec.name}.W"],
                    weights[f"{spec.name}.b"],
                    stride=spec.stride,
                )
                x = _ACTIVATIONS[spec.activation](x)
            elif isinstance(spec, BottleneckSpec):
                x = self._run_bottleneck(x, spec)
            elif isinstance(spec, PoolSpec):
                x = global_average_pool(x)
            elif isinstance(spec, DenseSpec):
                x = dense(x, weights[f"{spec.name}.W"], weights[f"{spec.name}.b"])
                x = _ACTIVATIONS[spec.activation](x)
            else:  # pragma: no cover
                raise TypeError(f"Unsupported layer spec: {spec!r}")

        return sigmoid(x)

    # -- convenience ---------------------------------------------------- #

    def normalise(self, sequence: np.ndarray) -> np.ndarray:
        """Standardise a raw feature sequence with the frozen training stats."""
        return (sequence - self.bundle.feature_mean) / self.bundle.feature_std

    def predict(self, sequence: np.ndarray) -> np.ndarray:
        """Classify one raw ``(seq_len, n_features)`` feature sequence."""
        normalised = self.normalise(np.asarray(sequence, dtype=np.float32))
        batch = normalised[None, :, :, None]
        return self.forward(batch)[0]

    def predict_batch(self, sequences: np.ndarray) -> np.ndarray:
        """Classify a batch of raw ``(N, seq_len, n_features)`` sequences."""
        normalised = self.normalise(np.asarray(sequences, dtype=np.float32))
        return self.forward(normalised[..., None])
