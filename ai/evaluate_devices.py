"""Evaluate the edge chain on a multi-device house.

The classifier was trained on houses with exactly one device per catalogue
type. This script measures what happens when that assumption is broken -- a
fan in every room, ratings changed by the admin -- at both levels the system
reports:

* **type level** -- does the classifier still say "a fan is on" correctly?
* **device level** -- does the disaggregator attribute power to the right fan?

Run from the project root::

    python -m ai.evaluate_devices --windows 4000
"""

from __future__ import annotations

import argparse
from dataclasses import replace

import numpy as np

from ai.disaggregate import DeviceDisaggregator
from ai.features import FeatureExtractor
from ai.inference import InferenceEngine
from simulator.devices import DeviceConfig, catalogue_devices, default_house
from simulator.house import VirtualHouse
from simulator.scenarios import SimulationMode

#: An estimate above this fraction of rating counts as "on" at device level.
ON_FRACTION: float = 0.3


#: Pseudo-scenario: same-type devices toggled one at a time, with background
#: load running. The hardest and most direct test of "which one is on?".
SHUFFLE = "shuffle"


def _shuffle_step(house: VirtualHouse, index: int, rng: np.random.Generator) -> None:
    if index == 0:
        for device_id in ("refrigerator", "tv"):
            if device_id in house.states:
                house.set_appliance(device_id, True)
    if index % 300 == 0 and "microwave" in house.states:
        house.set_appliance("microwave", not house.states["microwave"].socket_on)
    if index % 45 == 20:
        kinds = [s.spec.kind for s in house.states.values()]
        multi = [aid for aid, s in house.states.items() if kinds.count(s.spec.kind) > 1]
        if multi:
            target = str(rng.choice(multi))
            house.set_appliance(target, not house.states[target].socket_on)


def evaluate(
    devices: list[DeviceConfig],
    windows: int,
    scenario: str = "afternoon",
    seed: int = 11,
    warmup: int = 10,
) -> dict:
    shuffle = scenario == SHUFFLE
    house = VirtualHouse(
        scenario_id="custom" if shuffle else scenario,
        mode=SimulationMode.DEMO if shuffle else SimulationMode.SIMULATION,
        seed=seed,
        devices=devices,
    )
    rng = np.random.default_rng(seed)
    extractor = FeatureExtractor()
    engine = InferenceEngine()
    solver = DeviceDisaggregator(list(house.specs.values()))

    tp = fp = fn = 0
    device_ok = device_total = 0
    abs_err_w: list[float] = []
    multi_ok = multi_total = 0
    #: Windows where some, but not all, devices of a multi-device type are on:
    #: the only windows where "which one?" is actually being asked.
    mixed_ok = mixed_total = 0
    multi_kinds = {
        spec.kind
        for spec in house.specs.values()
        if sum(s.kind == spec.kind for s in house.specs.values()) > 1
    }

    for index in range(windows):
        if shuffle:
            _shuffle_step(house, index, rng)
        window = house.step(1.0)
        features = extractor.process(window.voltage, window.current)
        result = engine.predict(
            extractor.sequence(), current=window.current, voltage_rms=features.v_rms
        )
        if index < warmup:
            continue

        detected = set(result.detected)
        truth = window.ground_truth.drawing_types()
        tp += len(detected & truth)
        fp += len(detected - truth)
        fn += len(truth - detected)

        attribution = solver.solve(
            window.current,
            total_power_w=features.real_power_w,
            voltage_rms=features.v_rms,
            probabilities=result.probabilities,
            thresholds=engine.thresholds,
        )
        for device_id, spec in house.specs.items():
            estimate = attribution.power_w.get(device_id, 0.0)
            actual = window.ground_truth.power_w[device_id]
            on_truth = window.ground_truth.drawing[device_id]
            on_estimate = estimate > ON_FRACTION * spec.rated_power_w
            device_ok += on_truth == on_estimate
            device_total += 1
            if on_truth or on_estimate:
                abs_err_w.append(abs(estimate - actual) / spec.rated_power_w)
            if spec.kind in multi_kinds:
                multi_ok += on_truth == on_estimate
                multi_total += 1
        for kind in multi_kinds:
            states = [
                window.ground_truth.drawing[d]
                for d, s in house.specs.items()
                if s.kind == kind
            ]
            if any(states) and not all(states):
                for device_id, spec in house.specs.items():
                    if spec.kind != kind:
                        continue
                    estimate = attribution.power_w.get(device_id, 0.0)
                    mixed_ok += window.ground_truth.drawing[device_id] == (
                        estimate > ON_FRACTION * spec.rated_power_w
                    )
                    mixed_total += 1

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "type_f1": f1,
        "type_precision": precision,
        "type_recall": recall,
        "device_on_off_accuracy": device_ok / max(device_total, 1),
        "multi_device_on_off_accuracy": (multi_ok / multi_total) if multi_total else None,
        "mixed_on_off_accuracy": (mixed_ok / mixed_total) if mixed_total else None,
        "mixed_windows_fraction": mixed_total / max(multi_total, 1),
        "device_power_error_mean": float(np.mean(abs_err_w)) if abs_err_w else 0.0,
        "device_power_error_p95": float(np.percentile(abs_err_w, 95)) if abs_err_w else 0.0,
    }


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:5.1f}%"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--windows", type=int, default=4000)
    parser.add_argument(
        "--scenario",
        default="afternoon",
        help=f"a scenario id, or {SHUFFLE!r} to toggle same-type devices one at a time",
    )
    args = parser.parse_args()

    _, room_fans = default_house()
    rerated = [
        replace(d, rated_power_w=(90.0 if d.type_id == "fan" else d.rated_power_w))
        for d in room_fans
    ]
    houses = {
        "catalogue (training house)": catalogue_devices(),
        "fan in every room": room_fans,
        "fan in every room, fans 90 W": rerated,
    }
    for label, devices in houses.items():
        stats = evaluate(devices, args.windows, scenario=args.scenario)
        multi = stats["multi_device_on_off_accuracy"]
        print(
            f"{label:30s} type F1 {stats['type_f1']:.3f} "
            f"(P {stats['type_precision']:.3f} R {stats['type_recall']:.3f}) | "
            f"device on/off {stats['device_on_off_accuracy'] * 100:5.1f}% | "
            f"same-type devices {'-' if multi is None else f'{multi * 100:5.1f}%'} "
            f"(mixed {_pct(stats['mixed_on_off_accuracy'])}) | "
            f"power err mean {stats['device_power_error_mean'] * 100:4.1f}% "
            f"p95 {stats['device_power_error_p95'] * 100:5.1f}%"
        )


if __name__ == "__main__":
    main()
