"""Export a trained Keras model to the edge artefacts.

Produces three things from one trained model:

``nilm_model.keras``
    The full-fat Keras model, kept for retraining and for reference.

``nilm_model.tflite``
    A float16-quantised TensorFlow Lite flatbuffer.  This is what would be
    flashed onto the device in the hardware version of the project.

``nilm_weights.npz`` + ``nilm_model.json``
    Batch-norm-folded float32 weights plus metadata, consumed by the
    dependency-free NumPy interpreter in :mod:`ai.runtime`.

Batch-norm folding
------------------
Every convolution in this network is followed by batch normalisation and has no
bias of its own.  At inference time BN is a fixed affine map per channel::

    y = gamma * (conv(x) - mean) / sqrt(var + eps) + beta
      = conv(x) * s + (beta - mean * s)      where s = gamma / sqrt(var + eps)

Because convolution is linear, ``s`` can be pushed straight into the kernel and
the constant term becomes an ordinary bias.  The folded model is numerically
identical, has no BN layers left, and needs one fewer pass over the activations
-- which is why every real edge converter does this.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ai.architecture import BottleneckSpec, ConvSpec, DenseSpec, architecture_for
from ai.features import FEATURE_NAMES, SEQUENCE_LENGTH
from simulator.appliances import APPLIANCE_IDS

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"

KERAS_MODEL_FILE = "nilm_model.keras"
TFLITE_MODEL_FILE = "nilm_model.tflite"
WEIGHTS_FILE = "nilm_weights.npz"
METADATA_FILE = "nilm_model.json"


@dataclass
class ExportResult:
    keras_path: Path
    tflite_path: Path
    weights_path: Path
    metadata_path: Path
    keras_bytes: int
    tflite_bytes: int
    weights_bytes: int


def _fold_conv_bn(kernel: np.ndarray, bn_weights: list[np.ndarray], eps: float = 1e-3):
    """Fold a BatchNormalization layer into the preceding convolution kernel.

    ``kernel`` is ``(kh, kw, in, out)`` for a normal convolution or
    ``(kh, kw, channels, 1)`` for a depthwise one; in both cases the last
    non-unit axis indexes the output channel that BN scales.
    """
    gamma, beta, moving_mean, moving_var = bn_weights
    scale = gamma / np.sqrt(moving_var + eps)

    if kernel.shape[-1] == 1 and kernel.shape[-2] == len(scale):
        # Depthwise: output channel is axis -2.
        folded = kernel * scale.reshape(1, 1, -1, 1)
    else:
        folded = kernel * scale.reshape(1, 1, 1, -1)

    bias = beta - moving_mean * scale
    return folded.astype(np.float32), bias.astype(np.float32)


def fold_weights(model, num_classes: int) -> dict[str, np.ndarray]:
    """Walk the architecture and pull out folded weights, keyed by layer path."""
    architecture = architecture_for(num_classes)
    weights: dict[str, np.ndarray] = {}

    def layer(name: str):
        return model.get_layer(name)

    def fold(conv_name: str, bn_name: str, out_key: str) -> None:
        kernel = layer(conv_name).get_weights()[0]
        bn = layer(bn_name).get_weights()
        eps = layer(bn_name).epsilon
        folded, bias = _fold_conv_bn(kernel, bn, eps)
        weights[f"{out_key}.W"] = folded
        weights[f"{out_key}.b"] = bias

    for spec in architecture.layers:
        if isinstance(spec, ConvSpec):
            fold(spec.name, f"{spec.name}_bn", spec.name)
        elif isinstance(spec, BottleneckSpec):
            fold(f"{spec.name}_expand", f"{spec.name}_expand_bn", f"{spec.name}.expand")
            fold(
                f"{spec.name}_depthwise",
                f"{spec.name}_depthwise_bn",
                f"{spec.name}.depthwise",
            )
            if spec.use_se:
                for part in ("se_reduce", "se_expand"):
                    kernel, bias = layer(f"{spec.name}_{part}").get_weights()
                    weights[f"{spec.name}.{part}.W"] = kernel.astype(np.float32)
                    weights[f"{spec.name}.{part}.b"] = bias.astype(np.float32)
            fold(
                f"{spec.name}_project", f"{spec.name}_project_bn", f"{spec.name}.project"
            )
        elif isinstance(spec, DenseSpec):
            kernel, bias = layer(spec.name).get_weights()
            weights[f"{spec.name}.W"] = kernel.astype(np.float32)
            weights[f"{spec.name}.b"] = bias.astype(np.float32)

    return weights


def export_model(
    model,
    feature_mean: np.ndarray,
    feature_std: np.ndarray,
    thresholds: np.ndarray,
    metrics: dict,
    artifact_dir: Path | str = ARTIFACT_DIR,
    representative_data: np.ndarray | None = None,
) -> ExportResult:
    """Write every deployment artefact to ``artifact_dir``."""
    import tensorflow as tf  # imported lazily: build-time dependency only

    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    keras_path = artifact_dir / KERAS_MODEL_FILE
    tflite_path = artifact_dir / TFLITE_MODEL_FILE
    weights_path = artifact_dir / WEIGHTS_FILE
    metadata_path = artifact_dir / METADATA_FILE

    model.save(keras_path)

    # --- TensorFlow Lite (float16) ------------------------------------- #
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.target_spec.supported_types = [tf.float16]
    tflite_model = converter.convert()
    tflite_path.write_bytes(tflite_model)

    # --- NumPy bundle --------------------------------------------------- #
    weights = fold_weights(model, num_classes=len(APPLIANCE_IDS))
    weights["norm.mean"] = np.asarray(feature_mean, dtype=np.float32)
    weights["norm.std"] = np.asarray(feature_std, dtype=np.float32)
    np.savez_compressed(weights_path, **weights)

    metadata = {
        "architecture": architecture_for(len(APPLIANCE_IDS)).name,
        "appliance_ids": list(APPLIANCE_IDS),
        "feature_names": list(FEATURE_NAMES),
        "sequence_length": SEQUENCE_LENGTH,
        "thresholds": [float(t) for t in thresholds],
        "parameters": int(model.count_params()),
        "metrics": metrics,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return ExportResult(
        keras_path=keras_path,
        tflite_path=tflite_path,
        weights_path=weights_path,
        metadata_path=metadata_path,
        keras_bytes=keras_path.stat().st_size,
        tflite_bytes=tflite_path.stat().st_size,
        weights_bytes=weights_path.stat().st_size,
    )


def verify_export(
    model,
    bundle,
    sequences: np.ndarray,
    tflite_path: Path | str | None = None,
) -> dict[str, float]:
    """Check that Keras, TFLite and the NumPy runtime agree.

    Returns the maximum absolute probability difference for each pair.  If the
    NumPy interpreter had drifted from the trained graph -- a wrong padding
    rule, a missed residual, a botched BN fold -- it would show up here as a
    large disagreement rather than as quietly wrong predictions on the
    dashboard.
    """
    from ai.runtime import NumpyInterpreter

    interpreter = NumpyInterpreter(bundle)

    normalised = (sequences - bundle.feature_mean) / bundle.feature_std
    batch = normalised[..., None].astype(np.float32)

    keras_out = np.asarray(model.predict(batch, verbose=0))
    numpy_out = interpreter.forward(batch)

    results = {
        "keras_vs_numpy_max_abs": float(np.max(np.abs(keras_out - numpy_out))),
        "keras_vs_numpy_mean_abs": float(np.mean(np.abs(keras_out - numpy_out))),
    }

    if tflite_path is not None:
        import tensorflow as tf

        lite = tf.lite.Interpreter(model_path=str(tflite_path))
        lite.allocate_tensors()
        input_detail = lite.get_input_details()[0]
        output_detail = lite.get_output_details()[0]

        tflite_out = np.empty_like(keras_out)
        for index in range(len(batch)):
            lite.set_tensor(input_detail["index"], batch[index : index + 1])
            lite.invoke()
            tflite_out[index] = lite.get_tensor(output_detail["index"])[0]

        results["keras_vs_tflite_max_abs"] = float(
            np.max(np.abs(keras_out - tflite_out))
        )
        results["tflite_vs_numpy_max_abs"] = float(
            np.max(np.abs(tflite_out - numpy_out))
        )

    return results
