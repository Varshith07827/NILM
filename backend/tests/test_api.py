"""API and WebSocket tests.

The pipeline is driven explicitly rather than left to run on wall-clock time
(``NILM_AUTOSTART`` is disabled in ``conftest``), so these tests are
deterministic and do not depend on how fast the machine happens to be.
"""

from __future__ import annotations

import pytest

from simulator.appliances import APPLIANCE_IDS


def advance(client, windows: int = 12) -> None:
    """Process a fixed number of windows synchronously."""
    pipeline = client.app.state.pipeline
    for _ in range(windows):
        pipeline._process_window()  # noqa: SLF001 - deliberate in-process driving


class TestMeta:
    def test_health(self, client):
        body = client.get("/api/health").json()
        assert body["status"] == "ok"
        assert body["inference_backend"] in {"numpy", "tflite", "heuristic"}

    def test_root_points_at_the_docs(self, client):
        assert client.get("/").json()["docs"] == "/docs"

    def test_openapi_schema_is_generated(self, client):
        schema = client.get("/openapi.json").json()
        assert "/api/live" in schema["paths"]
        assert "/api/simulation/start" in schema["paths"]


class TestCatalogue:
    def test_appliances_endpoint(self, client):
        appliances = client.get("/api/appliances").json()
        assert len(appliances) == len(APPLIANCE_IDS)
        first = appliances[0]
        assert {"id", "name", "rated_power_w", "thd_percent", "harmonics"} <= set(first)

    def test_scenarios_endpoint(self, client):
        scenarios = client.get("/api/scenarios").json()
        ids = {scenario["id"] for scenario in scenarios}
        assert {"morning", "evening", "night", "vacation", "custom"} <= ids

    def test_model_card(self, client):
        model = client.get("/api/model").json()
        assert set(model["thresholds"]) == set(APPLIANCE_IDS)

    def test_signature_matrix(self, client):
        signatures = client.get("/api/model/signatures").json()
        assert signatures["orders"][0] == 1
        assert len(signatures["appliances"]) == len(APPLIANCE_IDS)

    def test_tariffs(self, client):
        tariffs = client.get("/api/tariffs").json()
        assert any(tariff["id"] == "domestic_slab" for tariff in tariffs)


class TestLiveData:
    def test_live_reports_unavailable_before_any_window(self, client):
        pipeline = client.app.state.pipeline
        if pipeline.latest_frame is None:
            assert client.get("/api/live").json()["available"] is False

    def test_live_frame_is_well_formed(self, client):
        advance(client)
        frame = client.get("/api/live").json()["frame"]

        assert {"measurement", "energy", "cost", "appliances", "scope"} <= set(frame)
        assert len(frame["appliances"]) == len(APPLIANCE_IDS)
        assert frame["measurement"]["voltage_v"] > 200.0
        assert frame["measurement"]["power_w"] >= 0.0
        assert 0.0 <= frame["measurement"]["power_factor"] <= 1.0
        assert len(frame["scope"]["current"]) == len(frame["scope"]["voltage"])

    def test_probabilities_are_valid(self, client):
        advance(client)
        frame = client.get("/api/live").json()["frame"]
        for appliance in frame["appliances"]:
            assert 0.0 <= appliance["probability"] <= 1.0
            assert appliance["estimated_power_w"] >= 0.0

    def test_attribution_does_not_exceed_the_meter(self, client):
        advance(client, 20)
        frame = client.get("/api/live").json()["frame"]
        attributed = sum(a["estimated_power_w"] for a in frame["appliances"])
        total = frame["measurement"]["power_w"]
        assert attributed <= total * 1.05 + 1.0

    def test_buffer_returns_chart_ready_series(self, client):
        advance(client)
        body = client.get("/api/buffer", params={"limit": 10}).json()
        assert body["count"] > 0
        assert len(body["series"]["power_w"]) == body["count"]

    def test_status_reports_the_model_and_stats(self, client):
        status = client.get("/api/status").json()
        assert status["state"] in {"stopped", "running", "paused"}
        assert status["stats"]["windows_processed"] >= 0
        assert "tariff" in status


class TestSimulationControls:
    def test_speed_must_be_one_of_the_allowed_values(self, client):
        assert client.post("/api/simulation/speed", json={"speed": 5}).status_code == 200
        assert client.post("/api/simulation/speed", json={"speed": 7}).status_code == 422

    def test_scenario_can_be_changed(self, client):
        response = client.post("/api/simulation/scenario", json={"scenario_id": "night"})
        assert response.status_code == 200
        assert client.get("/api/status").json()["scenario"]["id"] == "night"

    def test_unknown_scenario_is_rejected(self, client):
        response = client.post(
            "/api/simulation/scenario", json={"scenario_id": "narnia"}
        )
        assert response.status_code == 404

    def test_appliance_can_be_toggled(self, client):
        client.post("/api/simulation/scenario", json={"scenario_id": "custom"})
        response = client.post(
            "/api/simulation/appliance", json={"appliance_id": "microwave", "on": True}
        )
        assert response.status_code == 200

        advance(client, 4)
        frame = client.get("/api/live").json()["frame"]
        microwave = next(a for a in frame["appliances"] if a["id"] == "microwave")
        assert microwave["socket_on"]

    def test_unknown_appliance_is_rejected(self, client):
        response = client.post(
            "/api/simulation/appliance", json={"appliance_id": "reactor", "on": True}
        )
        assert response.status_code == 404

    def test_replay_mode_requires_a_recording(self, client):
        response = client.post("/api/simulation/mode", json={"mode": "replay"})
        assert response.status_code == 400

    def test_mode_can_be_switched(self, client):
        assert (
            client.post("/api/simulation/mode", json={"mode": "simulation"}).status_code
            == 200
        )
        assert client.get("/api/status").json()["mode"] == "simulation"
        client.post("/api/simulation/mode", json={"mode": "demo"})

    def test_reset_clears_the_buffer(self, client):
        advance(client, 5)
        client.post("/api/simulation/reset", json={"clear_history": True})
        assert client.app.state.pipeline.stats.windows_processed == 0


class TestRecordingAndReplay:
    def test_record_then_replay(self, client):
        client.post("/api/simulation/scenario", json={"scenario_id": "evening"})

        started = client.post(
            "/api/simulation/recordings/start", json={"name": "pytest-run"}
        )
        assert started.status_code == 200

        advance(client, 15)
        stopped = client.post("/api/simulation/recordings/stop").json()
        assert stopped["ok"]

        recordings = client.get("/api/simulation/recordings").json()["recordings"]
        assert any(r["name"] == "pytest-run" for r in recordings)

        target = next(r for r in recordings if r["name"] == "pytest-run")
        response = client.post(
            "/api/simulation/mode",
            json={"mode": "replay", "recording_file": target["file"]},
        )
        assert response.status_code == 200
        assert client.get("/api/status").json()["mode"] == "replay"

        advance(client, 5)
        assert client.get("/api/status").json()["recording"]["replay_progress"] > 0

        client.post("/api/simulation/mode", json={"mode": "demo"})

    def test_stopping_without_recording_is_reported(self, client):
        assert client.post("/api/simulation/recordings/stop").json()["ok"] is False

    def test_loading_a_missing_recording_fails(self, client):
        response = client.post(
            "/api/simulation/mode",
            json={"mode": "replay", "recording_file": "does-not-exist.jsonl"},
        )
        assert response.status_code == 400


class TestCostAndSettings:
    def test_cost_endpoint(self, client):
        advance(client)
        body = client.get("/api/cost").json()
        assert body["today_inr"] >= 0.0
        assert body["marginal_rate_inr"] >= 0.0
        assert len(body["slab_breakdown"]) >= 1

    def test_switching_to_a_preset_tariff(self, client):
        response = client.post("/api/settings/tariff", json={"tariff_id": "flat_rate"})
        assert response.status_code == 200
        assert client.get("/api/cost").json()["tariff"]["id"] == "flat_rate"

    def test_custom_tariff_is_accepted(self, client):
        response = client.post(
            "/api/settings/tariff",
            json={
                "name": "Unit Test Tariff",
                "fixed_charge_inr": 25.0,
                "slabs": [{"up_to_kwh": 50, "rate_inr": 3.0}, {"rate_inr": 9.0}],
            },
        )
        assert response.status_code == 200
        assert client.get("/api/cost").json()["tariff"]["name"] == "Unit Test Tariff"

    def test_descending_slabs_are_rejected(self, client):
        response = client.post(
            "/api/settings/tariff",
            json={
                "slabs": [{"up_to_kwh": 200, "rate_inr": 3.0},
                          {"up_to_kwh": 100, "rate_inr": 9.0}],
            },
        )
        assert response.status_code == 422

    def test_an_empty_tariff_request_is_rejected(self, client):
        assert client.post("/api/settings/tariff", json={}).status_code == 400

    def test_alert_thresholds_can_be_updated(self, client):
        response = client.post(
            "/api/settings/alerts", json={"high_power_threshold_w": 1234.0}
        )
        assert response.status_code == 200
        assert (
            client.get("/api/settings").json()["alerts"]["high_power_threshold_w"]
            == 1234.0
        )

    def test_out_of_range_threshold_is_rejected(self, client):
        response = client.post(
            "/api/settings/alerts", json={"sanctioned_load_w": -5.0}
        )
        assert response.status_code == 422


class TestHistoryAndReports:
    def test_history_after_a_flush(self, client):
        advance(client, 40)
        client.get("/api/reports", params={"period": "daily"})  # forces a flush
        body = client.get("/api/history", params={"max_points": 25}).json()
        assert body["total_rows"] > 0
        assert len(body["points"]) <= 25

    def test_daily_report_json(self, client):
        advance(client, 30)
        report = client.get("/api/reports", params={"period": "daily"}).json()
        assert report["period"] == "daily"
        assert report["total_energy_kwh"] >= 0.0
        assert isinstance(report["appliances"], list)

    @pytest.mark.parametrize("period", ["daily", "weekly", "monthly"])
    def test_every_period_builds(self, client, period):
        advance(client, 10)
        assert client.get("/api/reports", params={"period": period}).status_code == 200

    def test_csv_export(self, client):
        advance(client, 20)
        response = client.get(
            "/api/reports", params={"period": "daily", "format": "csv"}
        )
        assert response.status_code == 200
        assert b"APPLIANCE BREAKDOWN" in response.content

    def test_pdf_export(self, client):
        advance(client, 20)
        response = client.get(
            "/api/reports", params={"period": "daily", "format": "pdf"}
        )
        assert response.status_code == 200
        assert response.content[:4] == b"%PDF"

    def test_invalid_period_is_rejected(self, client):
        assert client.get("/api/reports", params={"period": "hourly"}).status_code == 422

    def test_exported_files_are_listed(self, client):
        advance(client, 10)
        client.get("/api/reports", params={"period": "daily", "format": "csv"})
        assert len(client.get("/api/reports/files").json()["files"]) > 0


class TestWebSocket:
    def test_handshake_sends_status_then_snapshot(self, client):
        advance(client, 6)
        with client.websocket_connect("/ws") as socket:
            assert socket.receive_json()["type"] == "status"
            snapshot = socket.receive_json()
            assert snapshot["type"] == "snapshot"
            assert "frames" in snapshot["data"]

    def test_ping_is_answered(self, client):
        with client.websocket_connect("/ws") as socket:
            socket.receive_json()  # status
            socket.receive_json()  # snapshot
            socket.send_json({"type": "ping"})
            assert socket.receive_json()["type"] == "pong"

    def test_resync_resends_state(self, client):
        advance(client, 4)
        with client.websocket_connect("/ws") as socket:
            socket.receive_json()
            socket.receive_json()
            socket.send_json({"type": "resync"})
            assert socket.receive_json()["type"] == "status"
            assert socket.receive_json()["type"] == "snapshot"


class TestAlertsAndEvents:
    def test_endpoints_return_lists(self, client):
        advance(client, 20)
        assert isinstance(client.get("/api/alerts").json()["alerts"], list)
        assert isinstance(client.get("/api/events").json()["events"], list)
