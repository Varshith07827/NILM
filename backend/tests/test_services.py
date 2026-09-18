"""Tests for the tariff, energy accounting, notification and replay services."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.app.services.cost import (
    TARIFF_PRESETS,
    Tariff,
    TariffSlab,
    get_tariff,
)
from backend.app.services.energy import EnergyTracker
from backend.app.services.notifications import AlertContext, NotificationEngine
from simulator.replay import Recorder, Recording, RecordingPlayer, list_recordings


@pytest.fixture
def slab_tariff() -> Tariff:
    """0-100 at 5, 100-200 at 10, above 200 at 20."""
    return Tariff(
        id="test",
        name="Test Slab",
        description="fixture",
        slabs=(TariffSlab(100, 5.0), TariffSlab(200, 10.0), TariffSlab(None, 20.0)),
        fixed_charge_inr=50.0,
    )


class TestTariff:
    def test_telescopic_charging_within_the_first_band(self, slab_tariff):
        assert slab_tariff.energy_charge(50) == pytest.approx(250.0)

    def test_telescopic_charging_across_bands(self, slab_tariff):
        # 100 * 5 + 50 * 10
        assert slab_tariff.energy_charge(150) == pytest.approx(1000.0)
        # 100 * 5 + 100 * 10 + 100 * 20
        assert slab_tariff.energy_charge(300) == pytest.approx(3500.0)

    def test_slabs_are_not_applied_as_a_single_flat_rate(self, slab_tariff):
        """The classic mistake: charging every unit at the top band's rate."""
        naive = 300 * 20.0
        assert slab_tariff.energy_charge(300) < naive

    def test_zero_and_negative_consumption_cost_nothing(self, slab_tariff):
        assert slab_tariff.energy_charge(0) == 0.0
        assert slab_tariff.energy_charge(-10) == 0.0

    def test_monthly_bill_includes_the_fixed_charge(self, slab_tariff):
        assert slab_tariff.monthly_bill(0) == pytest.approx(50.0)
        assert slab_tariff.monthly_bill(150) == pytest.approx(1050.0)

    def test_marginal_rate_tracks_the_active_band(self, slab_tariff):
        assert slab_tariff.marginal_rate(0) == 5.0
        assert slab_tariff.marginal_rate(99) == 5.0
        assert slab_tariff.marginal_rate(100) == 10.0
        assert slab_tariff.marginal_rate(250) == 20.0

    def test_incremental_cost_straddling_a_boundary_is_priced_correctly(self, slab_tariff):
        """20 units on top of 90 already used: 10 at 5, then 10 at 10."""
        assert slab_tariff.cost_of(20, 90) == pytest.approx(150.0)

    def test_incremental_cost_equals_the_difference_of_two_bills(self, slab_tariff):
        before, after = 175.0, 205.0
        expected = slab_tariff.energy_charge(after) - slab_tariff.energy_charge(before)
        assert slab_tariff.cost_of(after - before, before) == pytest.approx(expected)

    def test_effective_rate_is_not_absurd_at_tiny_consumption(self, slab_tariff):
        """A standing charge over a fraction of a unit must not read as 50,000/kWh."""
        assert slab_tariff.effective_rate(0.001) == pytest.approx(5.0)

    def test_slab_breakdown_marks_exactly_one_active_band(self, slab_tariff):
        rows = slab_tariff.slab_breakdown(150)
        assert sum(1 for row in rows if row["active"]) == 1
        assert sum(row["charge_inr"] for row in rows) == pytest.approx(
            slab_tariff.energy_charge(150)
        )

    def test_round_trips_through_a_dictionary(self, slab_tariff):
        restored = Tariff.from_dict(slab_tariff.to_dict())
        assert restored.energy_charge(275) == pytest.approx(
            slab_tariff.energy_charge(275)
        )

    def test_every_preset_is_usable(self):
        for tariff in TARIFF_PRESETS:
            assert tariff.monthly_bill(250) > 0
            assert get_tariff(tariff.id) is tariff

    def test_unknown_tariff_raises(self):
        with pytest.raises(KeyError, match="Unknown tariff"):
            get_tariff("gold-plated")


class TestEnergyTracker:
    def test_energy_integrates_power_over_time(self, slab_tariff):
        tracker = EnergyTracker(slab_tariff)
        start = datetime(2024, 5, 1, 12, 0, 0)
        for second in range(3600):
            tracker.update(
                start + timedelta(seconds=second), 1.0, 1000.0, {"fan": 1000.0}
            )
        # 1000 W for one hour is 1000 Wh.
        assert tracker.energy_wh_today == pytest.approx(1000.0, rel=1e-6)

    def test_speed_does_not_distort_energy(self, slab_tariff):
        """One simulated second is one watt-second regardless of playback speed."""
        slow = EnergyTracker(slab_tariff)
        start = datetime(2024, 5, 1, 12, 0, 0)
        for second in range(600):
            slow.update(start + timedelta(seconds=second), 1.0, 500.0, {})
        assert slow.energy_wh_session == pytest.approx(500.0 * 600 / 3600.0)

    def test_daily_counters_reset_at_midnight(self, slab_tariff):
        tracker = EnergyTracker(slab_tariff)
        tracker.update(datetime(2024, 5, 1, 23, 59, 59), 1.0, 3600.0, {})
        assert tracker.energy_wh_today > 0
        tracker.update(datetime(2024, 5, 2, 0, 0, 0), 1.0, 3600.0, {})
        assert tracker.energy_wh_today == pytest.approx(1.0)
        assert tracker.energy_wh_month > 1.0  # month total survives the day roll

    def test_monthly_counters_reset_at_month_end(self, slab_tariff):
        tracker = EnergyTracker(slab_tariff)
        tracker.update(datetime(2024, 5, 31, 23, 59, 59), 1.0, 3600.0, {})
        tracker.update(datetime(2024, 6, 1, 0, 0, 0), 1.0, 3600.0, {})
        assert tracker.energy_wh_month == pytest.approx(1.0)

    def test_per_appliance_energy_sums_to_the_total(self, slab_tariff):
        tracker = EnergyTracker(slab_tariff)
        start = datetime(2024, 5, 1, 9, 0, 0)
        for second in range(300):
            tracker.update(
                start + timedelta(seconds=second),
                1.0,
                900.0,
                {"fan": 100.0, "tv": 300.0, "air_conditioner": 500.0},
            )
        summed = sum(t.energy_wh_today for t in tracker.totals.values())
        assert summed == pytest.approx(tracker.energy_wh_today, rel=1e-6)

    def test_peak_power_is_tracked(self, slab_tariff):
        tracker = EnergyTracker(slab_tariff)
        start = datetime(2024, 5, 1, 9, 0, 0)
        for index, watts in enumerate([100.0, 4000.0, 250.0]):
            tracker.update(start + timedelta(seconds=index), 1.0, watts, {})
        assert tracker.peak_power_w_session == pytest.approx(4000.0)

    def test_changing_tariff_reprices_the_month(self, slab_tariff):
        tracker = EnergyTracker(slab_tariff)
        start = datetime(2024, 5, 1, 9, 0, 0)
        for second in range(3600):
            tracker.update(start + timedelta(seconds=second), 1.0, 10_000.0, {})
        expensive = Tariff(
            id="x", name="X", description="", slabs=(TariffSlab(None, 100.0),)
        )
        before = tracker.cost_inr_month
        tracker.set_tariff(expensive)
        assert tracker.cost_inr_month > before

    def test_snapshot_reports_a_sane_load_factor(self, slab_tariff):
        tracker = EnergyTracker(slab_tariff)
        start = datetime(2024, 5, 1, 9, 0, 0)
        for second in range(120):
            tracker.update(start + timedelta(seconds=second), 1.0, 500.0, {})
        snapshot = tracker.snapshot()
        assert 0.0 <= snapshot.load_factor <= 1.0


class TestNotificationEngine:
    def make_context(self, **overrides) -> AlertContext:
        base = dict(
            sim_time=datetime(2024, 5, 1, 19, 0, 0),
            sim_seconds=0.0,
            power_w=100.0,
            current_a=0.5,
            peak_current_a=1.0,
            power_factor=0.95,
            detected=[],
            newly_detected=[],
            newly_stopped=[],
            appliance_power_w={},
            appliance_runtime_s={},
            cost_today_inr=0.0,
            energy_today_wh=0.0,
        )
        base.update(overrides)
        return AlertContext(**base)

    @pytest.fixture
    def engine(self):
        return NotificationEngine(3000.0, 100.0, 25.0, 5000.0)

    def test_high_power_raises_a_warning(self, engine):
        alerts = engine.evaluate(self.make_context(power_w=3500.0))
        assert any(a.category == "load" for a in alerts)

    def test_approaching_sanctioned_load_is_critical(self, engine):
        alerts = engine.evaluate(self.make_context(power_w=4800.0))
        assert any(a.level.value == "critical" for a in alerts)

    def test_cooldown_suppresses_repeat_alerts(self, engine):
        first = engine.evaluate(self.make_context(power_w=3500.0, sim_seconds=0.0))
        second = engine.evaluate(self.make_context(power_w=3500.0, sim_seconds=5.0))
        assert first and not second

    def test_cooldown_expires(self, engine):
        engine.evaluate(self.make_context(power_w=3500.0, sim_seconds=0.0))
        later = engine.evaluate(self.make_context(power_w=3500.0, sim_seconds=10_000.0))
        assert later

    def test_daily_budget_fires_once_only(self, engine):
        first = engine.evaluate(self.make_context(cost_today_inr=150.0))
        second = engine.evaluate(
            self.make_context(cost_today_inr=200.0, sim_seconds=100_000.0)
        )
        assert any(a.category == "cost" for a in first)
        assert not any(a.category == "cost" for a in second)

    def test_heavy_appliance_start_is_announced(self, engine):
        alerts = engine.evaluate(
            self.make_context(
                newly_detected=["air_conditioner"],
                appliance_power_w={"air_conditioner": 1500.0},
            )
        )
        assert any("Air Conditioner" in a.title for a in alerts)

    def test_small_appliance_start_is_not_announced(self, engine):
        alerts = engine.evaluate(self.make_context(newly_detected=["led_light"]))
        assert not any("LED" in a.title for a in alerts)

    def test_quiet_house_produces_no_load_alerts(self, engine):
        alerts = engine.evaluate(self.make_context(power_w=150.0))
        assert not any(a.category == "load" for a in alerts)

    def test_reset_clears_cooldowns(self, engine):
        engine.evaluate(self.make_context(power_w=3500.0))
        engine.reset()
        assert engine.evaluate(self.make_context(power_w=3500.0, sim_seconds=1.0))


class TestRecording:
    def test_round_trip(self, tmp_path):
        recorder = Recorder(tmp_path)
        recorder.start("unit-test", "evening", "demo", 7, datetime(2024, 5, 1, 18, 0))
        for second in range(25):
            recorder.append(
                datetime(2024, 5, 1, 18, 0, second), {"fan": 1.0, "tv": 0.5}
            )
        path = recorder.stop()
        assert path is not None and path.exists()

        recording = Recording.load(path)
        assert recording.header.frame_count == 25
        assert recording.header.scenario_id == "evening"
        assert recording.frames[0].scales["fan"] == pytest.approx(1.0)
        assert recording.frames[0].scales["tv"] == pytest.approx(0.5)

    def test_player_loops(self, tmp_path):
        recorder = Recorder(tmp_path)
        recorder.start("loop", "night", "demo", 1, datetime(2024, 5, 1, 22, 0))
        for second in range(3):
            recorder.append(datetime(2024, 5, 1, 22, 0, second), {"fan": 1.0})
        path = recorder.stop()

        player = RecordingPlayer(Recording.load(path), loop=True)
        frames = [player.next_frame() for _ in range(7)]
        assert all(frame is not None for frame in frames)

    def test_player_stops_when_not_looping(self, tmp_path):
        recorder = Recorder(tmp_path)
        recorder.start("once", "night", "demo", 1, datetime(2024, 5, 1, 22, 0))
        recorder.append(datetime(2024, 5, 1, 22, 0, 0), {"fan": 1.0})
        path = recorder.stop()

        player = RecordingPlayer(Recording.load(path), loop=False)
        assert player.next_frame() is not None
        assert player.next_frame() is None

    def test_listing_ignores_corrupt_files(self, tmp_path):
        (tmp_path / "broken.nilm.jsonl").write_text("not json at all\n", encoding="utf-8")
        assert list_recordings(tmp_path) == []

    def test_listing_an_absent_directory_is_empty(self, tmp_path):
        assert list_recordings(tmp_path / "nope") == []
