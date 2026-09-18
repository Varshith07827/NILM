"""Train the NILM classifier and export the edge artefacts.

Run from the project root::

    python -m ai.train                 # full run
    python -m ai.train --smoke         # tiny run, for checking the plumbing

The script is deliberately verbose: it prints a per-appliance breakdown of
precision, recall and F1 so the numbers quoted in the report can be traced back
to an actual evaluation rather than asserted.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

# Keep TensorFlow quiet; it is chatty about CPU instruction sets on import.
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

from ai.dataset import (  # noqa: E402
    DatasetConfig,
    build_sequences,
    generate_dataset,
    normalisation_stats,
    split_by_episode,
)
from ai.export import ARTIFACT_DIR, export_model, verify_export  # noqa: E402
from ai.features import NUM_FEATURES, SEQUENCE_LENGTH  # noqa: E402
from simulator.appliances import APPLIANCE_IDS, APPLIANCES_BY_ID, NUM_APPLIANCES  # noqa: E402


def set_seeds(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    import tensorflow as tf

    tf.random.set_seed(seed)
    tf.keras.utils.set_random_seed(seed)


def weighted_binary_crossentropy(pos_weight: np.ndarray):
    """Binary cross-entropy with a per-appliance positive-class weight.

    A microwave is drawing power for a couple of percent of the day.  Without
    reweighting, predicting "microwave off" always would already score 98% and
    the network would happily settle there.
    """
    import tensorflow as tf

    weights = tf.constant(pos_weight.astype("float32"))

    def loss(y_true, y_pred):
        epsilon = tf.keras.backend.epsilon()
        y_pred = tf.clip_by_value(y_pred, epsilon, 1.0 - epsilon)
        positive = weights * y_true * tf.math.log(y_pred)
        negative = (1.0 - y_true) * tf.math.log(1.0 - y_pred)
        return -tf.reduce_mean(positive + negative)

    return loss


def tune_thresholds(y_true: np.ndarray, y_prob: np.ndarray) -> np.ndarray:
    """Pick the decision threshold per appliance that maximises F1.

    A single global 0.5 threshold is the wrong choice for multi-label problems
    with very different base rates; tuning per class on the validation split is
    standard practice and is worth a few points of F1 on the rare appliances.
    """
    thresholds = np.full(y_true.shape[1], 0.5, dtype=np.float32)
    grid = np.arange(0.05, 0.96, 0.01)
    for index in range(y_true.shape[1]):
        truth = y_true[:, index]
        if truth.sum() == 0:
            continue
        best_f1, best_threshold = -1.0, 0.5
        for threshold in grid:
            predicted = y_prob[:, index] >= threshold
            true_positive = float(np.sum(predicted & (truth > 0.5)))
            if true_positive == 0:
                continue
            precision = true_positive / float(predicted.sum())
            recall = true_positive / float((truth > 0.5).sum())
            f1 = 2 * precision * recall / (precision + recall)
            if f1 > best_f1:
                best_f1, best_threshold = f1, float(threshold)
        thresholds[index] = best_threshold
    return thresholds


def classification_report(
    y_true: np.ndarray, y_prob: np.ndarray, thresholds: np.ndarray
) -> dict:
    """Per-appliance and aggregate multi-label metrics."""
    y_pred = (y_prob >= thresholds).astype(np.float32)

    per_appliance = {}
    f1_scores = []
    for index, appliance_id in enumerate(APPLIANCE_IDS):
        truth = y_true[:, index] > 0.5
        predicted = y_pred[:, index] > 0.5
        true_positive = float(np.sum(truth & predicted))
        false_positive = float(np.sum(~truth & predicted))
        false_negative = float(np.sum(truth & ~predicted))

        precision = true_positive / (true_positive + false_positive) if (true_positive + false_positive) else 0.0
        recall = true_positive / (true_positive + false_negative) if (true_positive + false_negative) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        accuracy = float(np.mean(truth == predicted))

        per_appliance[appliance_id] = {
            "name": APPLIANCES_BY_ID[appliance_id].name,
            "support": int(truth.sum()),
            "base_rate": float(truth.mean()),
            "threshold": float(thresholds[index]),
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "accuracy": accuracy,
        }
        f1_scores.append(f1)

    exact_match = float(np.mean(np.all(y_pred == y_true, axis=1)))
    hamming = float(np.mean(y_pred == y_true))

    micro_tp = float(np.sum((y_true > 0.5) & (y_pred > 0.5)))
    micro_fp = float(np.sum((y_true <= 0.5) & (y_pred > 0.5)))
    micro_fn = float(np.sum((y_true > 0.5) & (y_pred <= 0.5)))
    micro_precision = micro_tp / (micro_tp + micro_fp) if (micro_tp + micro_fp) else 0.0
    micro_recall = micro_tp / (micro_tp + micro_fn) if (micro_tp + micro_fn) else 0.0
    micro_f1 = (
        2 * micro_precision * micro_recall / (micro_precision + micro_recall)
        if (micro_precision + micro_recall)
        else 0.0
    )

    return {
        "per_appliance": per_appliance,
        "macro_f1": float(np.mean(f1_scores)),
        "micro_f1": micro_f1,
        "micro_precision": micro_precision,
        "micro_recall": micro_recall,
        "hamming_accuracy": hamming,
        "exact_match_accuracy": exact_match,
    }


def print_report(report: dict) -> None:
    header = (
        f"{'appliance':<20}{'support':>9}{'base%':>8}{'thr':>6}"
        f"{'prec':>8}{'recall':>8}{'F1':>8}{'acc':>8}"
    )
    print("\n" + header)
    print("-" * len(header))
    for stats in report["per_appliance"].values():
        print(
            f"{stats['name']:<20}{stats['support']:>9,}{stats['base_rate'] * 100:>7.1f}%"
            f"{stats['threshold']:>6.2f}{stats['precision']:>8.3f}"
            f"{stats['recall']:>8.3f}{stats['f1']:>8.3f}{stats['accuracy']:>8.3f}"
        )
    print("-" * len(header))
    print(
        f"{'MACRO F1':<20}{report['macro_f1']:>50.4f}\n"
        f"{'MICRO F1':<20}{report['micro_f1']:>50.4f}\n"
        f"{'HAMMING ACCURACY':<20}{report['hamming_accuracy']:>50.4f}\n"
        f"{'EXACT MATCH':<20}{report['exact_match_accuracy']:>50.4f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the NILM classifier")
    parser.add_argument("--windows", type=int, default=72_000)
    parser.add_argument("--episode-length", type=int, default=400)
    parser.add_argument("--epochs", type=int, default=18)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=2e-3)
    parser.add_argument("--seed", type=int, default=20240501)
    parser.add_argument("--artifact-dir", type=Path, default=ARTIFACT_DIR)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Tiny run that only checks the pipeline end to end",
    )
    args = parser.parse_args()

    if args.smoke:
        args.windows, args.episode_length, args.epochs = 4_000, 200, 2

    set_seeds(args.seed)
    import tensorflow as tf

    print("=" * 78)
    print("NILM classifier training")
    print("=" * 78)

    # ------------------------------------------------------------------ #
    # 1. Data
    # ------------------------------------------------------------------ #
    print("\n[1/6] Generating simulated training data ...")
    config = DatasetConfig(
        total_windows=args.windows,
        episode_length_s=args.episode_length,
        seed=args.seed,
    )
    dataset = generate_dataset(config)
    train_raw, validation_raw = split_by_episode(
        dataset, config.validation_split, seed=args.seed
    )

    x_train, y_train, _ = build_sequences(train_raw)
    x_validation, y_validation, _ = build_sequences(validation_raw)
    print(
        f"  train {x_train.shape}  validation {x_validation.shape}  "
        f"({len(np.unique(train_raw.episodes))} / "
        f"{len(np.unique(validation_raw.episodes))} episodes)"
    )

    mean, std = normalisation_stats(train_raw.features)
    x_train = (x_train - mean) / std
    x_validation = (x_validation - mean) / std
    x_train = x_train[..., None]
    x_validation = x_validation[..., None]

    base_rates = y_train.mean(axis=0)
    print("\n  appliance base rates (fraction of windows drawing power):")
    for appliance_id, rate in zip(APPLIANCE_IDS, base_rates):
        print(f"    {APPLIANCES_BY_ID[appliance_id].name:<20} {rate * 100:5.1f}%")

    # ------------------------------------------------------------------ #
    # 2. Model
    # ------------------------------------------------------------------ #
    print("\n[2/6] Building model ...")
    from ai.model import build_model

    model = build_model(NUM_APPLIANCES, SEQUENCE_LENGTH, NUM_FEATURES)
    print(f"  {model.count_params():,} parameters")

    pos_weight = np.clip((1.0 - base_rates) / np.maximum(base_rates, 1e-4), 0.5, 8.0)
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=args.learning_rate),
        loss=weighted_binary_crossentropy(pos_weight),
        metrics=[tf.keras.metrics.AUC(name="auc", multi_label=True)],
    )

    # ------------------------------------------------------------------ #
    # 3. Training
    # ------------------------------------------------------------------ #
    print("\n[3/6] Training ...")
    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_auc", mode="max", patience=5, restore_best_weights=True
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_auc", mode="max", factor=0.4, patience=2, min_lr=1e-5
        ),
    ]
    started = time.perf_counter()
    history = model.fit(
        x_train,
        y_train,
        validation_data=(x_validation, y_validation),
        epochs=args.epochs,
        batch_size=args.batch_size,
        callbacks=callbacks,
        verbose=2,
    )
    training_seconds = time.perf_counter() - started
    print(f"  trained in {training_seconds:.0f}s")

    # ------------------------------------------------------------------ #
    # 4. Evaluation
    # ------------------------------------------------------------------ #
    print("\n[4/6] Evaluating ...")
    y_probability = np.asarray(model.predict(x_validation, batch_size=512, verbose=0))
    thresholds = tune_thresholds(y_validation, y_probability)
    report = classification_report(y_validation, y_probability, thresholds)
    print_report(report)

    # ------------------------------------------------------------------ #
    # 5. Export
    # ------------------------------------------------------------------ #
    print("\n[5/6] Exporting edge artefacts ...")
    metrics = {
        "macro_f1": report["macro_f1"],
        "micro_f1": report["micro_f1"],
        "hamming_accuracy": report["hamming_accuracy"],
        "exact_match_accuracy": report["exact_match_accuracy"],
        "training_seconds": training_seconds,
        "training_windows": int(args.windows),
        "epochs_run": len(history.history["loss"]),
    }
    result = export_model(
        model,
        feature_mean=mean,
        feature_std=std,
        thresholds=thresholds,
        metrics=metrics,
        artifact_dir=args.artifact_dir,
    )
    print(f"  {result.keras_path.name:<22} {result.keras_bytes / 1024:8.1f} KB")
    print(f"  {result.tflite_path.name:<22} {result.tflite_bytes / 1024:8.1f} KB")
    print(f"  {result.weights_path.name:<22} {result.weights_bytes / 1024:8.1f} KB")

    # ------------------------------------------------------------------ #
    # 6. Cross-backend verification
    # ------------------------------------------------------------------ #
    print("\n[6/6] Verifying Keras / TFLite / NumPy agreement ...")
    from ai.runtime import ModelBundle

    bundle = ModelBundle.load(result.weights_path, result.metadata_path)
    sample = (x_validation[:256, ..., 0] * std) + mean  # de-normalise for the check
    agreement = verify_export(model, bundle, sample, tflite_path=result.tflite_path)
    for key, value in agreement.items():
        print(f"  {key:<28} {value:.3e}")

    report["backend_agreement"] = agreement
    report["metrics"] = metrics
    report_path = Path(args.artifact_dir) / "training_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nreport written to {report_path}")

    if agreement["keras_vs_numpy_max_abs"] > 1e-3:
        raise SystemExit(
            "NumPy runtime disagrees with Keras -- refusing to ship this model"
        )
    print("\nDone.")


if __name__ == "__main__":
    main()
