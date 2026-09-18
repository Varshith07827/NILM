"""Tests for the virtual house and the waveform synthesis.

The important property under test is *self-consistency*: whatever the appliance
catalogue claims on its nameplate must be what you actually measure when you
synthesise its waveform and then analyse it the way firmware would. If those
two ever drift apart, every number downstream is quietly wrong.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from simulator.appliances import (
    APPLIANCE_CATALOGUE,
    APPLIANCE_IDS,
    MAX_HARMONIC,
    NOMINAL_VOLTAGE_V,
    get_appliance,
)
from simulator.house import VirtualHouse
from simulator.scenarios import SCENARIOS, SimulationMode, get_scenario
from simulator.waveform import (
    SAMPLE_RATE_HZ,
    SAMPLES_PER_WINDOW,
    HarmonicKernel,
    inrush_gain,
    sagged_voltage_rms,
    synthesise_voltage,
    time_axis,
)


class TestApplianceCatalogue:
    def test_every_appliance_has_a_unique_id(self):
        assert len(set(APPLIANCE_IDS)) == len(APPLIANCE_IDS)

    def test_power_factor_decomposition_is_consistent(self):
        """PF_total must equal PF_displacement * PF_distortion."""
        for spec in APPLIANCE_CATALOGUE:
            product = spec.displacement_power_factor * spec.distortion_power_factor
            assert product == pytest.approx(spec.power_factor, rel=1e-9)

    def test_real_power_from_the_fundamental_matches_nameplate(self):
        """P = V * I_fundamental * cos(phi) must reproduce the rated power."""
        for spec in APPLIANCE_CATALOGUE:
            fundamental_rms = spec.rms_current_a * spec.distortion_power_factor
            power = (
                NOMINAL_VOLTAGE_V * fundamental_rms * math.cos(spec.phase_angle_rad)
            )
            assert power == pytest.approx(spec.rated_power_w, rel=1e-9)

    def test_smps_loads_are_more_distorted_than_motors(self):
        """The whole disaggregation premise depends on this separation."""
        fan = get_appliance("fan")
        charger = get_appliance("mobile_charger")
        assert fan.thd < 0.1
        assert charger.thd > 1.0

    def test_hourly_profiles_are_well_formed(self):
        for spec in APPLIANCE_CATALOGUE:
            assert len(spec.hourly_probability) == 24
            assert all(0.0 <= p <= 1.0 for p in spec.hourly_probability)

    def test_unknown_appliance_raises_a_helpful_error(self):
        with pytest.raises(KeyError, match="Unknown appliance"):
            get_appliance("teleporter")

    def test_sampling_rate_avoids_aliasing_the_modelled_harmonics(self):
        """Nyquist must sit above the highest harmonic in the catalogue."""
        highest_hz = MAX_HARMONIC * 50.0
        assert highest_hz < SAMPLE_RATE_HZ / 2


class TestWaveformSynthesis:
    @pytest.fixture(scope="class")
    def axis(self):
        return time_axis(0.0)

    def test_synthesised_current_measures_back_to_its_nameplate(self, axis):
        voltage = synthesise_voltage(axis, NOMINAL_VOLTAGE_V)
        v_rms = float(np.sqrt(np.mean(voltage**2)))

        for spec in APPLIANCE_CATALOGUE:
            kernel = HarmonicKernel.from_spec(spec)
            current = kernel.synthesise(axis, spec.rms_current_a)

            i_rms = float(np.sqrt(np.mean(current**2)))
            power = float(np.mean(voltage * current))
            power_factor = power / (v_rms * i_rms)

            assert i_rms == pytest.approx(spec.rms_current_a, rel=0.01)
            assert power == pytest.approx(spec.rated_power_w, rel=0.02)
            assert power_factor == pytest.approx(spec.power_factor, rel=0.02)

    def test_zero_current_is_returned_for_a_switched_off_appliance(self, axis):
        kernel = HarmonicKernel.from_spec(get_appliance("fan"))
        assert np.allclose(kernel.synthesise(axis, 0.0), 0.0)

    def test_voltage_sags_under_load(self):
        assert sagged_voltage_rms(0.0) == pytest.approx(NOMINAL_VOLTAGE_V)
        assert sagged_voltage_rms(20.0) < NOMINAL_VOLTAGE_V - 5.0

    def test_inrush_decays_towards_unity(self):
        spec = get_appliance("refrigerator")
        assert inrush_gain(0.0, spec) == pytest.approx(spec.startup.multiplier)
        assert inrush_gain(spec.startup.duration_s, spec) < 1.2
        assert inrush_gain(10.0, spec) == pytest.approx(1.0, abs=1e-6)

    def test_window_is_a_whole_number_of_mains_cycles(self):
        """Guarantees every harmonic lands exactly on an FFT bin."""
        cycles = SAMPLES_PER_WINDOW * 50.0 / SAMPLE_RATE_HZ
        assert cycles == int(cycles)


class TestVirtualHouse:
    def test_step_returns_a_well_formed_window(self, house):
        window = house.step(1.0)
        assert len(window.current) == SAMPLES_PER_WINDOW
        assert len(window.voltage) == SAMPLES_PER_WINDOW
        assert set(window.ground_truth.power_w) == set(APPLIANCE_IDS)

    def test_aggregate_power_equals_the_sum_of_its_parts(self, house):
        """The single most important invariant in the simulator."""
        for _ in range(120):
            window = house.step(1.0)
            measured = float(np.mean(window.voltage * window.current))
            summed = sum(window.ground_truth.power_w.values())
            if abs(summed) > 20.0:
                assert measured == pytest.approx(summed, rel=0.02)

    def test_demo_mode_is_reproducible(self):
        """Two runs with the same seed must be bit-for-bit identical."""
        first = VirtualHouse("evening", SimulationMode.DEMO, seed=99)
        second = VirtualHouse("evening", SimulationMode.DEMO, seed=99)
        for _ in range(40):
            a, b = first.step(1.0), second.step(1.0)
            assert np.array_equal(a.current, b.current)
            assert a.ground_truth.drawing == b.ground_truth.drawing

    def test_different_seeds_diverge(self):
        first = VirtualHouse("evening", SimulationMode.SIMULATION, seed=1)
        second = VirtualHouse("evening", SimulationMode.SIMULATION, seed=2)
        differences = 0
        for _ in range(60):
            if not np.array_equal(first.step(1.0).current, second.step(1.0).current):
                differences += 1
        assert differences > 0

    def test_manual_switching_changes_the_measured_current(self, empty_house):
        before = empty_house.step(1.0)
        baseline = float(np.sqrt(np.mean(before.current**2)))

        empty_house.set_appliance("air_conditioner", True)
        # Skip the inrush window so we compare settled states.
        empty_house.step(1.0)
        after = empty_house.step(1.0)
        running = float(np.sqrt(np.mean(after.current**2)))

        assert running > baseline + 5.0
        assert after.ground_truth.drawing["air_conditioner"]

    def test_switching_produces_an_event(self, empty_house):
        empty_house.set_appliance("tv", True)
        window = empty_house.step(1.0)
        actions = [(e.appliance_id, e.action.value) for e in window.events]
        assert ("tv", "on") in actions

    def test_demo_script_fires_in_order(self):
        house = VirtualHouse("evening", SimulationMode.DEMO, seed=5)
        fired: list[str] = []
        for _ in range(400):
            for event in house.step(1.0).events:
                if event.action.value == "on":
                    fired.append(event.appliance_id)
        # The evening script starts with the fan, then lights, then the TV.
        assert fired[:4] == ["fan", "led_light", "tube_light", "tv"]

    def test_reset_restores_the_starting_state(self, house):
        for _ in range(50):
            house.step(1.0)
        assert house.sim_seconds > 0
        house.reset()
        assert house.sim_seconds == 0.0

    def test_never_on_appliances_stay_off(self):
        house = VirtualHouse("vacation", SimulationMode.SIMULATION, seed=3)
        scenario = get_scenario("vacation")
        for _ in range(300):
            truth = house.step(1.0).ground_truth
            for appliance_id in scenario.never_on:
                assert not truth.drawing[appliance_id]

    def test_always_on_appliances_are_switched_on(self):
        house = VirtualHouse("evening", SimulationMode.DEMO, seed=3)
        window = house.step(1.0)
        assert window.ground_truth.socket_on["refrigerator"]

    def test_duty_cycled_appliance_actually_cycles(self, empty_house):
        """A refrigerator switched on at the socket must not draw continuously."""
        empty_house.set_appliance("refrigerator", True)
        drawing = [empty_house.step(1.0).ground_truth.drawing["refrigerator"]
                   for _ in range(3000)]
        assert any(drawing) and not all(drawing)


class TestScenarios:
    def test_all_scenarios_are_well_formed(self):
        for scenario in SCENARIOS:
            assert 0.0 <= scenario.start_hour < 24.0
            assert scenario.activity >= 0.0
            assert set(scenario.always_on).isdisjoint(scenario.never_on)
            for appliance_id in (*scenario.always_on, *scenario.never_on):
                assert appliance_id in APPLIANCE_IDS

    def test_scripts_reference_real_appliances_and_ascend_in_time(self):
        for scenario in SCENARIOS:
            offsets = [event.offset_s for event in scenario.script]
            assert offsets == sorted(offsets), scenario.id
            for event in scenario.script:
                assert event.appliance_id in APPLIANCE_IDS

    def test_unknown_scenario_raises(self):
        with pytest.raises(KeyError, match="Unknown scenario"):
            get_scenario("atlantis")
