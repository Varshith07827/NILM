"""The inference engine used by the live backend.

Deliberately free of any TensorFlow import.  The backend must start in under a
second and must keep a one-second inference budget; importing TensorFlow costs
roughly thirty seconds and hundreds of megabytes, which is precisely the reason
TensorFlow Lite (and, in this project, the NumPy kernel in :mod:`ai.runtime`)
exists in the first place.

Three backends are supported, selected automatically in this order:

``numpy``
    The exported, batch-norm-folded weights executed by :class:`NumpyInterpreter`.
    Verified at export time to match Keras to ~1e-7.  This is the default.

``tflite``
    The actual ``.tflite`` flatbuffer run through TensorFlow's interpreter.
    Slower to start but useful for demonstrating that the deployed artefact is
    a genuine TFLite model.  Opt in explicitly.

``heuristic``
    A classical, training-free NILM solver used when no trained model is
    present.  It is not a stub: it solves the same non-negative harmonic
    least-squares problem as the disaggregator, over all twelve appliances at
    once, and reports any appliance assigned a meaningful share of the current.
    It is a genuine baseline, and the training report compares the neural model
    against it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import numpy as np
from scipy.optimize import nnls

from ai.disaggregate import UNIT_DESIGN_MATRIX, measured_phasors
from ai.export import METADATA_FILE, TFLITE_MODEL_FILE, WEIGHTS_FILE
from ai.features import NUM_FEATURES, SEQUENCE_LENGTH
from ai.runtime import ModelBundle, NumpyInterpreter
from simulator.appliances import APPLIANCE_IDS, NOMINAL_VOLTAGE_V

DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"

#: An appliance must be assigned at least this fraction of its rated current by
#: the heuristic solver before it is called "on".
HEURISTIC_DETECTION_FRACTION: float = 0.35


class InferenceBackend(str, Enum):
    NUMPY = "numpy"
    TFLITE = "tflite"
    HEURISTIC = "heuristic"


@dataclass
class InferenceResult:
    """One classification of one acquisition window."""

    probabilities: dict[str, float] = field(default_factory=dict)
    detected: list[str] = field(default_factory=list)
    backend: str = InferenceBackend.HEURISTIC.value
    latency_ms: float = 0.0

    def confidence(self, appliance_id: str) -> float:
        return self.probabilities.get(appliance_id, 0.0)


class HeuristicDetector:
    """Training-free NILM baseline built on non-negative harmonic matching.

    Solves ``min ||A a - b||`` subject to ``a >= 0`` over *all* appliances,
    where ``A`` holds each appliance's unit harmonic phasors and ``b`` is the
    measured aggregate.  Appliances whose fitted scale exceeds a fraction of
    their rating are reported as detected.

    This is a real algorithm and a fair point of comparison: it is essentially
    what NILM looked like before neural networks, and it fails in instructive
    ways -- it cannot use transients, so it confuses combinations of small
    loads with single larger ones.
    """

    def __init__(self, detection_fraction: float = HEURISTIC_DETECTION_FRACTION) -> None:
        self.detection_fraction = detection_fraction

    def predict(self, current: np.ndarray, voltage_rms: float) -> dict[str, float]:
        sag = max(voltage_rms, 1.0) / NOMINAL_VOLTAGE_V
        design = UNIT_DESIGN_MATRIX * sag
        target = measured_phasors(current)
        stacked = np.concatenate([target.real, target.imag])

        # A light ridge term keeps the solution stable when several appliances
        # have near-parallel signatures.
        ridge = 0.02 * float(np.linalg.norm(design)) / design.shape[1]
        augmented_design = np.vstack([design, ridge * np.eye(design.shape[1])])
        augmented_target = np.concatenate([stacked, np.zeros(design.shape[1])])

        scales, _ = nnls(augmented_design, augmented_target)

        # Map the fitted scale onto a pseudo-probability with a soft ramp so the
        # dashboard still gets a usable confidence bar.
        probabilities: dict[str, float] = {}
        for appliance_id, scale in zip(APPLIANCE_IDS, scales):
            ratio = float(scale) / max(self.detection_fraction, 1e-6)
            probabilities[appliance_id] = float(np.clip(ratio, 0.0, 1.0))
        return probabilities


class InferenceEngine:
    """Loads whichever backend is available and classifies feature sequences."""

    def __init__(
        self,
        artifact_dir: Path | str = DEFAULT_ARTIFACT_DIR,
        backend: str = "auto",
    ) -> None:
        self.artifact_dir = Path(artifact_dir)
        self.bundle: ModelBundle | None = None
        self._interpreter: NumpyInterpreter | None = None
        self._tflite = None
        self._heuristic = HeuristicDetector()
        self.backend = InferenceBackend.HEURISTIC
        self.load_error: str | None = None

        self._select_backend(backend)

    # ------------------------------------------------------------------ #
    # Setup
    # ------------------------------------------------------------------ #

    def _select_backend(self, requested: str) -> None:
        weights_path = self.artifact_dir / WEIGHTS_FILE
        metadata_path = self.artifact_dir / METADATA_FILE

        if requested == InferenceBackend.HEURISTIC.value:
            return

        if not (weights_path.exists() and metadata_path.exists()):
            self.load_error = (
                f"no trained model in {self.artifact_dir} -- "
                "falling back to the heuristic solver (run: python -m ai.train)"
            )
            return

        try:
            self.bundle = ModelBundle.load(weights_path, metadata_path)
        except Exception as exc:  # pragma: no cover - defensive
            self.load_error = f"failed to load model bundle: {exc}"
            return

        if requested == InferenceBackend.TFLITE.value:
            try:
                import tensorflow as tf

                interpreter = tf.lite.Interpreter(
                    model_path=str(self.artifact_dir / TFLITE_MODEL_FILE)
                )
                interpreter.allocate_tensors()
                self._tflite = interpreter
                self.backend = InferenceBackend.TFLITE
                return
            except Exception as exc:  # pragma: no cover - optional path
                self.load_error = f"TFLite backend unavailable ({exc}); using NumPy"

        self._interpreter = NumpyInterpreter(self.bundle)
        self.backend = InferenceBackend.NUMPY

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #

    @property
    def thresholds(self) -> dict[str, float]:
        if self.bundle is None:
            return {aid: 0.5 for aid in APPLIANCE_IDS}
        return {
            aid: float(value)
            for aid, value in zip(self.bundle.appliance_ids, self.bundle.thresholds)
        }

    def info(self) -> dict:
        """Model card shown on the dashboard."""
        metadata = self.bundle.metadata if self.bundle else {}
        return {
            "backend": self.backend.value,
            "model_available": self.bundle is not None,
            "architecture": metadata.get("architecture", "harmonic-nnls-baseline"),
            "parameters": metadata.get("parameters", 0),
            "sequence_length": metadata.get("sequence_length", SEQUENCE_LENGTH),
            "num_features": NUM_FEATURES,
            "metrics": metadata.get("metrics", {}),
            "load_error": self.load_error,
            "artifact_dir": str(self.artifact_dir),
        }

    # ------------------------------------------------------------------ #
    # Inference
    # ------------------------------------------------------------------ #

    def predict(
        self,
        sequence: np.ndarray,
        current: np.ndarray | None = None,
        voltage_rms: float = NOMINAL_VOLTAGE_V,
    ) -> InferenceResult:
        """Classify one feature sequence.

        ``current`` is only needed by the heuristic backend, which works
        directly on the waveform rather than on extracted features.
        """
        started = time.perf_counter()

        if self.backend is InferenceBackend.NUMPY and self._interpreter is not None:
            raw = self._interpreter.predict(sequence)
            probabilities = {
                aid: float(value) for aid, value in zip(APPLIANCE_IDS, raw)
            }
        elif self.backend is InferenceBackend.TFLITE and self._tflite is not None:
            assert self.bundle is not None
            normalised = (
                np.asarray(sequence, dtype=np.float32) - self.bundle.feature_mean
            ) / self.bundle.feature_std
            batch = normalised[None, :, :, None].astype(np.float32)
            input_detail = self._tflite.get_input_details()[0]
            output_detail = self._tflite.get_output_details()[0]
            self._tflite.set_tensor(input_detail["index"], batch)
            self._tflite.invoke()
            raw = self._tflite.get_tensor(output_detail["index"])[0]
            probabilities = {
                aid: float(value) for aid, value in zip(APPLIANCE_IDS, raw)
            }
        else:
            if current is None:
                probabilities = {aid: 0.0 for aid in APPLIANCE_IDS}
            else:
                probabilities = self._heuristic.predict(current, voltage_rms)

        thresholds = self.thresholds
        detected = [
            aid
            for aid in APPLIANCE_IDS
            if probabilities.get(aid, 0.0) >= thresholds.get(aid, 0.5)
        ]

        return InferenceResult(
            probabilities=probabilities,
            detected=detected,
            backend=self.backend.value,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )
