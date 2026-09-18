"""Keras construction of the NILM classifier described in :mod:`ai.architecture`.

Kept separate from everything else because TensorFlow is a *build-time*
dependency of this project, not a runtime one.  The backend imports
:mod:`ai.inference`, which never touches TensorFlow; only training and export
import this module.
"""

from __future__ import annotations

import keras
from keras import layers, ops

from ai.architecture import (
    BottleneckSpec,
    ConvSpec,
    DenseSpec,
    ModelArchitecture,
    PoolSpec,
    architecture_for,
)
from ai.features import NUM_FEATURES, SEQUENCE_LENGTH


@keras.saving.register_keras_serializable(package="nilm")
class HardSwish(layers.Layer):
    """``x * relu6(x + 3) / 6`` -- MobileNetV3's activation.

    Piecewise linear, so it costs a compare and a multiply on a microcontroller
    instead of a transcendental.
    """

    def call(self, inputs):
        return inputs * ops.clip(inputs + 3.0, 0.0, 6.0) / 6.0


@keras.saving.register_keras_serializable(package="nilm")
class HardSigmoid(layers.Layer):
    """``relu6(x + 3) / 6`` -- the gate used by squeeze-and-excitation."""

    def call(self, inputs):
        return ops.clip(inputs + 3.0, 0.0, 6.0) / 6.0


def _activation(name: str, prefix: str):
    if name == "hswish":
        return HardSwish(name=f"{prefix}_hswish")
    if name == "relu":
        return layers.ReLU(name=f"{prefix}_relu")
    if name == "sigmoid":
        return layers.Activation("sigmoid", name=f"{prefix}_sigmoid")
    return layers.Activation("linear", name=f"{prefix}_linear")


def _squeeze_excite(x, spec: BottleneckSpec):
    """Global channel attention: pool, bottleneck, gate, rescale."""
    channels = x.shape[-1]
    reduced = max(8, int(channels * spec.se_ratio))
    se = layers.GlobalAveragePooling2D(keepdims=True, name=f"{spec.name}_se_pool")(x)
    se = layers.Conv2D(reduced, 1, name=f"{spec.name}_se_reduce")(se)
    se = layers.ReLU(name=f"{spec.name}_se_relu")(se)
    se = layers.Conv2D(channels, 1, name=f"{spec.name}_se_expand")(se)
    se = HardSigmoid(name=f"{spec.name}_se_gate")(se)
    return layers.Multiply(name=f"{spec.name}_se_scale")([x, se])


def _bottleneck(x, spec: BottleneckSpec):
    """Inverted residual block: expand -> depthwise -> SE -> project."""
    shortcut = x
    in_channels = x.shape[-1]

    # Expand.  Always applied (even when the expansion is 1:1) so the exported
    # weight layout is uniform and the NumPy runtime needs no special cases.
    x = layers.Conv2D(
        spec.expand_filters, 1, use_bias=False, name=f"{spec.name}_expand"
    )(x)
    x = layers.BatchNormalization(name=f"{spec.name}_expand_bn")(x)
    x = _activation(spec.activation, f"{spec.name}_expand")(x)

    # Depthwise spatial filter.
    x = layers.DepthwiseConv2D(
        spec.kernel,
        strides=spec.stride,
        padding="same",
        use_bias=False,
        name=f"{spec.name}_depthwise",
    )(x)
    x = layers.BatchNormalization(name=f"{spec.name}_depthwise_bn")(x)
    x = _activation(spec.activation, f"{spec.name}_depthwise")(x)

    if spec.use_se:
        x = _squeeze_excite(x, spec)

    # Project back down -- linear, no activation (the "linear bottleneck").
    x = layers.Conv2D(spec.out_filters, 1, use_bias=False, name=f"{spec.name}_project")(x)
    x = layers.BatchNormalization(name=f"{spec.name}_project_bn")(x)

    if spec.has_residual_candidate and in_channels == spec.out_filters:
        x = layers.Add(name=f"{spec.name}_residual")([shortcut, x])
    return x


def build_model(
    num_classes: int,
    sequence_length: int = SEQUENCE_LENGTH,
    num_features: int = NUM_FEATURES,
    architecture: ModelArchitecture | None = None,
) -> keras.Model:
    """Build the classifier for a ``(sequence_length, num_features, 1)`` input."""
    architecture = architecture or architecture_for(num_classes)

    inputs = keras.Input(shape=(sequence_length, num_features, 1), name="features")
    x = inputs

    for spec in architecture.layers:
        if isinstance(spec, ConvSpec):
            x = layers.Conv2D(
                spec.filters,
                spec.kernel,
                strides=spec.stride,
                padding="same",
                use_bias=False,
                name=spec.name,
            )(x)
            x = layers.BatchNormalization(name=f"{spec.name}_bn")(x)
            x = _activation(spec.activation, spec.name)(x)
        elif isinstance(spec, BottleneckSpec):
            x = _bottleneck(x, spec)
        elif isinstance(spec, PoolSpec):
            x = layers.GlobalAveragePooling2D(name=spec.name)(x)
        elif isinstance(spec, DenseSpec):
            x = layers.Dense(spec.units, name=spec.name)(x)
            if spec.activation != "linear":
                x = _activation(spec.activation, spec.name)(x)
            if spec.dropout > 0.0:
                x = layers.Dropout(spec.dropout, name=f"{spec.name}_dropout")(x)
        else:  # pragma: no cover - guarded by the type union
            raise TypeError(f"Unsupported layer spec: {spec!r}")

    outputs = layers.Activation(
        architecture.output_activation, name="appliance_probabilities"
    )(x)
    return keras.Model(inputs, outputs, name=architecture.name)
