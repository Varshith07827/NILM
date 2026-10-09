"""Devices, house configuration, admin auth and the notification centre."""

from __future__ import annotations

import math
import time
from dataclasses import replace

import numpy as np
import pytest

from ai.device_tracker import SETTLE_WINDOWS
from ai.disaggregate import DeviceDisaggregator, unit_column
from backend.app.core.config import get_settings
from backend.app.core.security import (
    LoginThrottle,
    create_token,
    hash_password,
    verify_password,
    verify_token,
)
from simulator.appliances import APPLIANCE_CATALOGUE, get_appliance
from simulator.devices import (
    MAX_DEVICES_PER_TYPE,
    DeviceConfig,
    catalogue_devices,
    default_house,
    device_spec,
    next_free_variant,
    rating_bounds,
    variant_spec,
)
from simulator.house import VirtualHouse
from simulator.scenarios import SimulationMode
from simulator.waveform import HarmonicKernel, synthesise_voltage, time_axis

from .test_api import advance

# --------------------------------------------------------------------------- #
# Variants and device specs
# --------------------------------------------------------------------------- #


class TestVariants:
    @pytest.mark.parametrize("spec", APPLIANCE_CATALOGUE, ids=lambda s: s.id)
    def test_variants_keep_power_and_differ_in_phase(self, spec):
        angles = []
        for variant in range(MAX_DEVICES_PER_TYPE):
            v = variant_spec(spec, variant)
            assert v.rated_power_w == spec.rated_power_w
            assert set(v.harmonics) == set(spec.harmonics)
            # Same watts whatever the shape: P = V * I_rms * PF by construction.
            assert v.rms_current_a * v.power_factor == pytest.approx(
                spec.rms_current_a * spec.power_factor
            )
            angles.append(math.degrees(v.phase_angle_rad))
        assert len({round(a, 3) for a in angles}) == MAX_DEVICES_PER_TYPE

    @pytest.mark.parametrize("spec", APPLIANCE_CATALOGUE, ids=lambda s: s.id)
    def test_variant_columns_are_not_collinear(self, spec):
        columns = [unit_column(variant_spec(spec, v)) for v in range(MAX_DEVICES_PER_TYPE)]
        for i in range(len(columns)):
            for j in range(i + 1, len(columns)):
                cosine = columns[i] @ columns[j] / (
                    np.linalg.norm(columns[i]) * np.linalg.norm(columns[j])
                )
                assert cosine < 0.9995, (spec.id, i, j)

    def test_device_spec_applies_rating_and_identity(self):
        spec = device_spec(
            DeviceConfig(
                id="fan-x", type_id="fan", room_id="study", name="Study Fan",
                variant=2, rated_power_w=90.0,
            )
        )
        assert (spec.id, spec.kind, spec.name, spec.variant) == ("fan-x", "fan", "Study Fan", 2)
        assert spec.rated_power_w == 90.0
        assert spec.rms_current_a > get_appliance("fan").rms_current_a

    def test_default_house_has_a_fan_in_every_room(self):
        rooms, devices = default_house()
        fan_rooms = {d.room_id for d in devices if d.type_id == "fan"}
        assert fan_rooms == {room.id for room in rooms}
        fan_variants = [d.variant for d in devices if d.type_id == "fan"]
        assert len(set(fan_variants)) == len(fan_variants)

    def test_next_free_variant_respects_the_cap(self):
        devices = [
            DeviceConfig(id=f"fan{v}", type_id="fan", room_id="r", name="f", variant=v)
            for v in range(MAX_DEVICES_PER_TYPE)
        ]
        assert next_free_variant("fan", devices) is None
        assert next_free_variant("fan", devices[1:]) == 0
        assert next_free_variant("tv", devices) == 0


class TestMultiDeviceHouse:
    def test_ground_truth_is_per_device_with_types(self):
        _, devices = default_house()
        house = VirtualHouse("evening", SimulationMode.DEMO, seed=3, devices=devices)
        window = house.step(1.0)
        assert set(window.ground_truth.power_w) == {d.id for d in devices}
        assert window.ground_truth.type_of["fan-bedroom"] == "fan"

    def test_configure_keeps_running_devices_on(self):
        house = VirtualHouse("custom", SimulationMode.DEMO, seed=1)
        house.set_appliance("fan", True)
        devices = catalogue_devices() + [
            DeviceConfig(id="fan-2", type_id="fan", room_id="study", name="Study Fan", variant=1)
        ]
        house.configure(devices)
        assert house.states["fan"].socket_on
        assert not house.states["fan-2"].socket_on

    def test_unknown_device_cannot_be_toggled(self):
        house = VirtualHouse("custom", SimulationMode.DEMO, seed=1)
        with pytest.raises(KeyError):
            house.set_appliance("teleporter", True)


class TestDeviceDisaggregation:
    """The point of variants: two fans on one mains, attributed separately."""

    def _aggregate(self, specs, on):
        t = time_axis(0.0)
        current = np.zeros_like(t)
        for spec, is_on in zip(specs, on, strict=True):
            if is_on:
                current += HarmonicKernel.from_spec(spec).synthesise(t, spec.rms_current_a)
        return current

    @pytest.mark.parametrize("on", [(True, False), (False, True), (True, True)])
    def test_two_fans_are_told_apart(self, on):
        specs = [
            device_spec(DeviceConfig(id=f"fan{v}", type_id="fan", room_id="r", name="f", variant=v))
            for v in (0, 1)
        ]
        current = self._aggregate(specs, on)
        voltage = synthesise_voltage(time_axis(0.0), 230.0)
        total = float(np.mean(voltage * current))
        # The solver tracks state across windows and waits for start-up
        # transients to settle before its first decision.
        solver = DeviceDisaggregator(specs)
        for _ in range(SETTLE_WINDOWS + 1):
            result = solver.solve(
                current, total_power_w=total, voltage_rms=230.0,
                probabilities={"fan": 1.0}, thresholds={"fan": 0.5},
            )
        for spec, is_on in zip(specs, on, strict=True):
            watts = result.power_w.get(spec.id, 0.0)
            if is_on:
                assert watts == pytest.approx(spec.rated_power_w, rel=0.15)
            else:
                assert watts < 0.3 * spec.rated_power_w

    def test_catalogue_disaggregator_matches_device_ids(self):
        solver = DeviceDisaggregator(list(APPLIANCE_CATALOGUE))
        assert solver.ids == [spec.id for spec in APPLIANCE_CATALOGUE]


# --------------------------------------------------------------------------- #
# Security primitives
# --------------------------------------------------------------------------- #


class TestSecurity:
    def test_password_hash_round_trip(self):
        stored = hash_password("correct horse", iterations=1000)
        assert "correct horse" not in stored
        assert verify_password("correct horse", stored)
        assert not verify_password("wrong horse", stored)
        assert not verify_password("anything", "garbage")

    def test_token_round_trip_and_tamper(self):
        settings = get_settings()
        token = create_token("admin", settings)
        claims = verify_token(token, settings)
        assert claims is not None and claims.username == "admin"
        body, signature = token.split(".")
        assert verify_token(body + "x." + signature, settings) is None
        assert verify_token("not-a-token", settings) is None

    def test_token_expires(self):
        settings = get_settings()
        token = create_token("admin", settings, now=time.time() - 10 * 24 * 3600)
        assert verify_token(token, settings) is None

    def test_throttle_blocks_after_repeated_failures(self):
        throttle = LoginThrottle(max_failures=3, window_s=60.0)
        for _ in range(3):
            assert not throttle.blocked("1.2.3.4", now=100.0)
            throttle.record_failure("1.2.3.4", now=100.0)
        assert throttle.blocked("1.2.3.4", now=100.0)
        assert not throttle.blocked("1.2.3.4", now=200.0)
        assert not throttle.blocked("5.6.7.8", now=100.0)


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #


class TestAuthApi:
    def test_status_reports_configured_admin(self, client):
        assert client.get("/api/auth/status").json()["admin_configured"] is True

    def test_wrong_password_is_rejected(self, client):
        response = client.post(
            "/api/auth/login", json={"username": "admin", "password": "nope-nope"}
        )
        assert response.status_code == 401

    def test_me_requires_token(self, client, admin_headers):
        assert client.get("/api/auth/me").status_code == 401
        assert client.get("/api/auth/me", headers=admin_headers).json()["username"] == "admin"

    @pytest.mark.parametrize(
        ("method", "path", "body"),
        [
            ("post", "/api/house/rooms", {"name": "Garage"}),
            ("post", "/api/house/devices", {"type_id": "fan", "room_id": "living"}),
            ("patch", "/api/house/devices/fan", {"rated_power_w": 80}),
            ("delete", "/api/house/rooms/living", None),
            ("post", "/api/settings/tariff", {"tariff_id": "flat_rate"}),
            ("post", "/api/settings/alerts", {"high_power_threshold_w": 1}),
        ],
    )
    def test_changes_need_admin(self, client, method, path, body):
        kwargs = {"json": body} if body is not None else {}
        assert getattr(client, method)(path, **kwargs).status_code == 401


class TestHouseApi:
    def test_default_house_is_seeded(self, client):
        house = client.get("/api/house").json()
        fans = [d for d in house["devices"] if d["type_id"] == "fan"]
        assert len(house["rooms"]) == 5
        assert {d["room_id"] for d in fans} == {r["id"] for r in house["rooms"]}
        fan_type = next(t for t in house["types"] if t["id"] == "fan")
        assert fan_type["device_count"] == len(fans)

    def test_add_room_and_device_reaches_the_simulation(self, client, admin_headers):
        created = client.post(
            "/api/house/rooms", json={"name": "Guest Room"}, headers=admin_headers
        )
        assert created.status_code == 201
        room_id = created.json()["detail"]["room_id"]

        added = client.post(
            "/api/house/devices",
            json={"type_id": "tv", "room_id": room_id, "rated_power_w": 120},
            headers=admin_headers,
        )
        assert added.status_code == 201, added.text
        device_id = added.json()["detail"]["device_id"]

        pipeline = client.app.state.pipeline
        assert pipeline.house.specs[device_id].rated_power_w == 120
        assert device_id in pipeline.disaggregator.ids
        assert client.post(
            "/api/simulation/appliance", json={"appliance_id": device_id, "on": True}
        ).status_code == 200

        advance(client, windows=2)
        frame = pipeline.latest_frame
        row = next(a for a in frame["appliances"] if a["id"] == device_id)
        assert row["room_name"] == "Guest Room"
        assert row["name"] == "Guest Room Television"

        removed = client.delete(f"/api/house/rooms/{room_id}", headers=admin_headers)
        assert removed.json()["detail"]["removed_device_ids"] == [device_id]
        assert device_id not in pipeline.house.states

    def test_rating_outside_the_band_is_rejected(self, client, admin_headers):
        low, high = rating_bounds("fan")
        for watts in (low - 1, high + 1):
            response = client.patch(
                "/api/house/devices/fan", json={"rated_power_w": watts}, headers=admin_headers
            )
            assert response.status_code == 400

    def test_rating_change_and_reset(self, client, admin_headers):
        pipeline = client.app.state.pipeline
        assert client.patch(
            "/api/house/devices/fan", json={"rated_power_w": 80}, headers=admin_headers
        ).status_code == 200
        assert pipeline.house.specs["fan"].rated_power_w == 80
        assert client.patch(
            "/api/house/devices/fan", json={"rated_power_w": None}, headers=admin_headers
        ).status_code == 200
        assert pipeline.house.specs["fan"].rated_power_w == get_appliance("fan").rated_power_w

    def test_per_type_device_cap(self, client, admin_headers):
        fans = [d for d in client.get("/api/house").json()["devices"] if d["type_id"] == "fan"]
        assert len(fans) == MAX_DEVICES_PER_TYPE
        response = client.post(
            "/api/house/devices",
            json={"type_id": "fan", "room_id": "living"},
            headers=admin_headers,
        )
        assert response.status_code == 400
        assert "tell apart" in response.json()["detail"]

    def test_unknown_room_and_type(self, client, admin_headers):
        assert client.post(
            "/api/house/devices", json={"type_id": "tv", "room_id": "attic"},
            headers=admin_headers,
        ).status_code == 404
        assert client.post(
            "/api/house/devices", json={"type_id": "jetpack", "room_id": "living"},
            headers=admin_headers,
        ).status_code == 400

    def test_device_history(self, client):
        advance(client, windows=5)
        body = client.get("/api/devices/fan/history").json()
        assert body["device_id"] == "fan"
        assert body["points"]
        assert {"sim_time", "power_w", "current_a"} <= set(body["points"][0])
        assert client.get("/api/devices/nope/history").status_code == 404


class TestNotificationsApi:
    def test_list_and_mark_read(self, client):
        pipeline = client.app.state.pipeline
        pipeline._notification_rows.append(
            {
                "sim_time": pipeline.house.sim_time,
                "recorded_at": pipeline.house.sim_time,
                "level": "info",
                "category": "test",
                "title": "Test alert",
                "message": "for the notification centre",
                "value": 0.0,
                "run_id": pipeline.run_id,
            }
        )
        body = client.get("/api/notifications").json()
        assert body["unread"] >= 1
        newest = body["items"][0]
        assert newest["title"] == "Test alert" and newest["read"] is False

        client.post("/api/notifications/read", json={"ids": [newest["id"]]})
        after = client.get("/api/notifications").json()
        assert after["items"][0]["read"] is True
        assert after["unread"] == body["unread"] - 1

        client.post("/api/notifications/read", json={})
        assert client.get("/api/notifications").json()["unread"] == 0


def test_rerated_device_draws_more_current():
    base = catalogue_devices()
    rerated = [replace(d, rated_power_w=150.0) if d.id == "fan" else d for d in base]
    house = VirtualHouse("custom", SimulationMode.DEMO, seed=5, devices=rerated)
    house.set_appliance("fan", True)
    for _ in range(5):
        window = house.step(1.0)
    assert window.ground_truth.power_w["fan"] == pytest.approx(150.0, rel=0.1)
