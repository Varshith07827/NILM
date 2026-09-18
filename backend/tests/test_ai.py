"""Tests for feature extraction, the edge runtime, and disaggregation."""

from __future__ import annotations

import numpy as np
import pytest

from ai.disaggregate import (
    DISAGGREGATION_ORDERS,
    UNIT_PHASOR_MATRIX,
    disaggregate,
    measured_phasors,
)
from ai.features import (
    FEATURE_NAMES,
    NUM_FEATURES,
    SEQUENCE_LENGTH,
    FeatureExtractor,
    extract_features,
)
from ai.inference import HeuristicDetector, InferenceEngine
from ai.runtime import hard_sigmoid, hard_swish, relu, sigmoid
from simulator.appliances import (
    APPLIANCE_CATALOGUE,
    APPLIANCE_IDS,
    NOMINAL_VOLTAGE_V,
    get_appliance,
)
from simulator.waveform import HarmonicKernel, synthesise_voltage, time_axis


@pytest.fixture(scope="module")
def axis():
    return time_axis(0.0)


@pytest.fixture(scope="module")
def voltage(axis):
    return synthesise_voltage(axis, NOMINAL_VOLTAGE_V)


def single_appliance_current(appliance_id: str, axis, scale: float = 1.0):
    spec = get_appliance(appliance_id)
    return HarmonicKernel.from_spec(spec).synthesise(axis, spec.rms_current_a * scale)


class TestFeatureExtraction:
    def test_vector_length_matches_the_declared_names(self, voltage, axis):
        features = extract_features(voltage, single_appliance_current("fan", axis))
        assert len(features.to_vector()) == NUM_FEATURES == len(FEATURE_NAMES)

    def test_no_time_of_day_leaks_into_the_model_input(self):
        """The classifier must identify appliances electrically, not by the clock."""
        forbidden = ("hour", "time", "day", "minute", "clock")
        assert not [n for n in FEATURE_NAMES if any(f in n for f in forbidden)]

    def test_features_are_finite_for_an_idle_line(self, voltage, axis):
        features = extract_features(voltage, np.zeros_like(axis))
        assert np.all(np.isfinite(features.to_vector()))

    def test_measured_power_matches_the_appliance(self, voltage, axis):
        for spec in APPLIANCE_CATALOGUE:
            features = extract_features(voltage, single_appliance_current(spec.id, axis))
            assert features.real_power_w == pytest.approx(spec.rated_power_w, rel=0.02)
            assert features.i_rms == pytest.approx(spec.rms_current_a, rel=0.01)

    def test_displacement_power_factor_is_recovered(self, voltage, axis):
        for spec in APPLIANCE_CATALOGUE:
            features = extract_features(voltage, single_appliance_current(spec.id, axis))
            assert features.displacement_pf == pytest.approx(
                spec.displacement_power_factor, abs=0.02
            )

    def test_harmonic_ratios_match_the_specification(self, voltage, axis):
        spec = get_appliance("led_light")
        features = extract_features(voltage, single_appliance_current("led_light", axis))
        assert features.harmonic_ratio_3 == pytest.approx(spec.harmonics[3], abs=0.02)
        assert features.harmonic_ratio_5 == pytest.approx(spec.harmonics[5], abs=0.02)

    def test_smps_and_motor_loads_are_separable_by_crest_factor(self, voltage, axis):
        motor = extract_features(voltage, single_appliance_current("fan", axis))
        smps = extract_features(voltage, single_appliance_current("mobile_charger", axis))
        assert motor.crest_factor < 2.0 < smps.crest_factor

    def test_delta_features_are_zero_without_a_previous_window(self, voltage, axis):
        features = extract_features(voltage, single_appliance_current("tv", axis))
        assert features.delta_power_w == 0.0
        assert features.event_magnitude == 0.0

    def test_delta_features_capture_a_step_change(self, voltage, axis):
        idle = extract_features(voltage, np.zeros_like(axis))
        started = extract_features(
            voltage, single_appliance_current("air_conditioner", axis), previous=idle
        )
        assert started.delta_power_w > 1000.0
        assert started.event_magnitude > 0.5


class TestFeatureExtractorState:
    def test_sequence_has_the_right_shape_from_the_first_window(self, voltage, axis):
        extractor = FeatureExtractor()
        extractor.process(voltage, single_appliance_current("fan", axis))
        assert extractor.sequence().shape == (SEQUENCE_LENGTH, NUM_FEATURES)

    def test_becomes_ready_after_enough_windows(self, voltage, axis):
        extractor = FeatureExtractor()
        current = single_appliance_current("fan", axis)
        for index in range(SEQUENCE_LENGTH):
            assert extractor.ready is (index >= SEQUENCE_LENGTH)
            extractor.process(voltage, current)
        assert extractor.ready

    def test_leading_edge_is_padded_by_repeating_the_first_frame(self, voltage, axis):
        extractor = FeatureExtractor()
        extractor.process(voltage, single_appliance_current("fan", axis))
        sequence = extractor.sequence()
        assert np.allclose(sequence[0], sequence[-1])

    def test_reset_clears_history(self, voltage, axis):
        extractor = FeatureExtractor()
        for _ in range(SEQUENCE_LENGTH):
            extractor.process(voltage, single_appliance_current("tv", axis))
        extractor.reset()
        assert not extractor.ready


class TestRuntimeActivations:
    def test_hard_swish_matches_its_definition(self):
        x = np.linspace(-6, 6, 50)
        assert np.allclose(hard_swish(x), x * np.clip(x + 3, 0, 6) / 6)

    def test_hard_sigmoid_is_bounded(self):
        x = np.linspace(-20, 20, 100)
        y = hard_sigmoid(x)
        assert y.min() >= 0.0 and y.max() <= 1.0

    def test_sigmoid_is_numerically_stable_at_extremes(self):
        y = sigmoid(np.array([-1000.0, 0.0, 1000.0]))
        assert np.all(np.isfinite(y))
        assert y[0] == pytest.approx(0.0)
        assert y[1] == pytest.approx(0.5)
        assert y[2] == pytest.approx(1.0)

    def test_relu_clips_negatives(self):
        assert np.array_equal(relu(np.array([-2.0, 0.0, 3.0])), np.array([0.0, 0.0, 3.0]))


class TestInferenceEngine:
    @pytest.fixture(scope="class")
    def engine(self):
        return InferenceEngine()

    def test_a_backend_is_always_available(self, engine):
        assert engine.backend.value in {"numpy", "tflite", "heuristic"}

    def test_predicts_a_probability_per_appliance(self, engine, voltage, axis):
        extractor = FeatureExtractor()
        current = single_appliance_current("air_conditioner", axis)
        for _ in range(SEQUENCE_LENGTH):
            features = extractor.process(voltage, current)
        result = engine.predict(
            extractor.sequence(), current=current, voltage_rms=features.v_rms
        )
        assert set(result.probabilities) == set(APPLIANCE_IDS)
        assert all(0.0 <= p <= 1.0 for p in result.probabilities.values())
        assert result.latency_ms >= 0.0

    def test_inference_is_fast_enough_for_a_one_second_budget(self, engine, voltage, axis):
        """The whole point of the NumPy kernel is that it fits the loop budget."""
        extractor = FeatureExtractor()
        current = single_appliance_current("tv", axis)
        for _ in range(SEQUENCE_LENGTH):
            features = extractor.process(voltage, current)

        latencies = [
            engine.predict(
                extractor.sequence(), current=current, voltage_rms=features.v_rms
            ).latency_ms
            for _ in range(20)
        ]
        assert float(np.median(latencies)) < 200.0

    def test_thresholds_cover_every_appliance(self, engine):
        assert set(engine.thresholds) == set(APPLIANCE_IDS)

    def test_heuristic_backend_can_be_forced(self):
        engine = InferenceEngine(backend="heuristic")
        assert engine.backend.value == "heuristic"


class TestHeuristicDetector:
    def test_finds_a_large_isolated_load(self, axis):
        detector = HeuristicDetector()
        current = single_appliance_current("air_conditioner", axis)
        probabilities = detector.predict(current, NOMINAL_VOLTAGE_V)
        assert probabilities["air_conditioner"] > 0.8

    def test_reports_nothing_on_a_dead_line(self, axis):
        detector = HeuristicDetector()
        probabilities = detector.predict(np.zeros_like(axis), NOMINAL_VOLTAGE_V)
        assert max(probabilities.values()) < 0.2


class TestDisaggregation:
    def test_signature_matrix_shape(self):
        assert UNIT_PHASOR_MATRIX.shape == (
            len(DISAGGREGATION_ORDERS),
            len(APPLIANCE_IDS),
        )

    def test_no_two_appliances_share_a_signature(self):
        """If two columns were identical, separating them would be impossible."""
        normalised = UNIT_PHASOR_MATRIX / np.linalg.norm(
            UNIT_PHASOR_MATRIX, axis=0, keepdims=True
        )
        similarity = np.abs(normalised.conj().T @ normalised)
        np.fill_diagonal(similarity, 0.0)
        assert similarity.max() < 0.9999

    def test_measured_phasors_recover_a_known_appliance(self, axis):
        spec = get_appliance("tv")
        current = single_appliance_current("tv", axis)
        phasors = measured_phasors(current)
        expected = UNIT_PHASOR_MATRIX[:, APPLIANCE_IDS.index("tv")]
        assert np.allclose(phasors, expected, atol=1e-3)
        assert abs(phasors[0]) == pytest.approx(
            spec.rms_current_a * spec.distortion_power_factor * np.sqrt(2), rel=0.02
        )

    def test_attributes_a_single_appliance_correctly(self, voltage, axis):
        spec = get_appliance("microwave")
        current = single_appliance_current("microwave", axis)
        features = extract_features(voltage, current)

        result = disaggregate(
            current,
            total_power_w=features.real_power_w,
            voltage_rms=features.v_rms,
            probabilities={aid: (1.0 if aid == "microwave" else 0.0) for aid in APPLIANCE_IDS},
            thresholds={aid: 0.5 for aid in APPLIANCE_IDS},
        )
        assert result.power_w["microwave"] == pytest.approx(spec.rated_power_w, rel=0.1)

    def test_splits_a_mixture_across_the_right_appliances(self, voltage, axis):
        mixture = (
            single_appliance_current("air_conditioner", axis)
            + single_appliance_current("tv", axis)
            + single_appliance_current("refrigerator", axis)
        )
        features = extract_features(voltage, mixture)
        detected = {"air_conditioner", "tv", "refrigerator"}

        result = disaggregate(
            mixture,
            total_power_w=features.real_power_w,
            voltage_rms=features.v_rms,
            probabilities={aid: (1.0 if aid in detected else 0.0) for aid in APPLIANCE_IDS},
            thresholds={aid: 0.5 for aid in APPLIANCE_IDS},
        )

        for appliance_id in detected:
            expected = get_appliance(appliance_id).rated_power_w
            assert result.power_w[appliance_id] == pytest.approx(expected, rel=0.2)

    def test_a_confident_detection_is_never_assigned_zero(self, voltage, axis):
        """Regression: a zero-centred prior used to collapse small loads.

        An LED lamp beside a tube light has a near-identical harmonic shape.
        With the prior centred at zero, least squares resolved the ambiguity by
        driving the lamp to exactly 0 W while still reporting it as detected.
        """
        mixture = (
            single_appliance_current("led_light", axis)
            + single_appliance_current("tube_light", axis)
            + single_appliance_current("air_conditioner", axis)
        )
        features = extract_features(voltage, mixture)
        detected = {"led_light", "tube_light", "air_conditioner"}

        result = disaggregate(
            mixture,
            total_power_w=features.real_power_w,
            voltage_rms=features.v_rms,
            probabilities={aid: (1.0 if aid in detected else 0.0) for aid in APPLIANCE_IDS},
            thresholds={aid: 0.5 for aid in APPLIANCE_IDS},
        )
        assert result.power_w.get("led_light", 0.0) > 1.0

    def test_attribution_sums_to_the_measured_total(self, voltage, axis):
        mixture = single_appliance_current("fan", axis) + single_appliance_current(
            "laptop", axis
        )
        features = extract_features(voltage, mixture)
        result = disaggregate(
            mixture,
            total_power_w=features.real_power_w,
            voltage_rms=features.v_rms,
            probabilities={aid: (1.0 if aid in {"fan", "laptop"} else 0.0) for aid in APPLIANCE_IDS},
            thresholds={aid: 0.5 for aid in APPLIANCE_IDS},
        )
        total = result.attributed_w + result.unattributed_w
        assert total == pytest.approx(features.real_power_w, rel=0.02)

    def test_nothing_detected_means_everything_is_unattributed(self, voltage, axis):
        current = single_appliance_current("tv", axis)
        features = extract_features(voltage, current)
        result = disaggregate(
            current,
            total_power_w=features.real_power_w,
            voltage_rms=features.v_rms,
            probabilities={aid: 0.0 for aid in APPLIANCE_IDS},
            thresholds={aid: 0.5 for aid in APPLIANCE_IDS},
        )
        assert result.power_w == {}
        assert result.unattributed_w == pytest.approx(features.real_power_w)

    def test_never_assigns_negative_power(self, voltage, axis):
        mixture = sum(
            single_appliance_current(aid, axis) for aid in ("fan", "tv", "laptop")
        )
        features = extract_features(voltage, mixture)
        result = disaggregate(
            mixture,
            total_power_w=features.real_power_w,
            voltage_rms=features.v_rms,
            probabilities={aid: 0.9 for aid in APPLIANCE_IDS},
            thresholds={aid: 0.5 for aid in APPLIANCE_IDS},
        )
        assert all(watts >= 0.0 for watts in result.power_w.values())
