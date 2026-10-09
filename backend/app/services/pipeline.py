"""The real-time NILM pipeline (Module 9).

One object owns the whole edge chain and drives it once per simulated second::

    VirtualHouse -> waveform -> features -> inference -> disaggregation
                 -> energy -> cost -> alerts -> SQLite -> WebSocket

Design notes
------------
*Simulated time is the unit of account.*  Running at 10x speed produces
simulated seconds ten times faster in wall-clock terms, but each one still
represents exactly one watt-second of energy.  That is what makes "a full day
of household usage in 2.4 minutes" a meaningful statement rather than a
tenfold billing error.

*The database is written in batches.*  At 10x speed the pipeline produces 10
readings and 130 bucket updates per second; committing each individually would
spend all its time in fsync.  Rows accumulate in memory and are flushed in one
transaction off the event loop via ``asyncio.to_thread``.

*Detection is scored honestly.*  The simulator's ground truth is carried
alongside the model's prediction but never fed into it.  The live accuracy
panel compares the two after the fact, which is why it shows a real number that
moves rather than a decorative 99%.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

from ai.disaggregate import DeviceDisaggregator
from ai.features import FeatureExtractor, WindowFeatures
from ai.inference import InferenceEngine
from backend.app.core.config import Settings
from backend.app.db.repositories.energy import TOTAL_KEY, UNATTRIBUTED_KEY
from backend.app.services.cost import Tariff, get_tariff
from backend.app.services.energy import EnergyTracker
from backend.app.services.notifications import AlertContext, NotificationEngine
from simulator.appliances import APPLIANCE_CATALOGUE
from simulator.devices import DeviceConfig, RoomConfig, catalogue_devices
from simulator.house import RawWindow, VirtualHouse
from simulator.replay import Recorder, Recording, RecordingPlayer, list_recordings
from simulator.scenarios import SCENARIOS_BY_ID, SimulationMode
from simulator.waveform import MAINS_FREQUENCY_HZ, SAMPLE_RATE_HZ

logger = logging.getLogger(__name__)

_TYPE_NAMES: dict[str, str] = {spec.id: spec.name for spec in APPLIANCE_CATALOGUE}

#: Samples of the raw waveform sent to the dashboard oscilloscope each window.
#: Two complete mains cycles is enough to see the shape without flooding the
#: socket with the full 2000-sample window.
SCOPE_SAMPLES: int = int(2 * SAMPLE_RATE_HZ / MAINS_FREQUENCY_HZ)

#: Windows over which the live precision / recall panel is computed.
ACCURACY_WINDOW: int = 300

#: How many windows an appliance event waits for the model to confirm it.
DETECTION_GRACE_WINDOWS: int = 6

#: A device counts as "on" when it is attributed this fraction of its rating.
#: The classifier only decides *types*; with several devices of one type it is
#: the disaggregator that says which of them is running.
DEVICE_ON_FRACTION: float = 0.3

ALLOWED_SPEEDS: tuple[int, ...] = (1, 2, 5, 10, 20, 60)


class SimulationState(str, Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"


@dataclass
class _PendingEvent:
    """An appliance event waiting to see whether the model notices it."""

    row: dict
    appliance_id: str
    action: str
    windows_left: int
    detected: bool = False
    latency_windows: int = 0


@dataclass
class PipelineStats:
    """Counters shown on the status bar."""

    windows_processed: int = 0
    rows_written: int = 0
    #: Median, not mean. A mean latency is the wrong statistic to publish: one
    #: window where the OS descheduled the process makes the headline figure
    #: wrong by an order of magnitude and tells the reader nothing useful.
    inference_ms_median: float = 0.0
    inference_ms_p95: float = 0.0
    loop_ms_median: float = 0.0
    behind_realtime: bool = False


class NILMPipeline:
    """Owns the simulation, the model and every derived stream."""

    def __init__(
        self,
        settings: Settings,
        devices: list[DeviceConfig] | None = None,
        rooms: list[RoomConfig] | None = None,
    ) -> None:
        self.settings = settings

        # --- simulation --------------------------------------------------- #
        self.mode = SimulationMode(settings.default_mode)
        self.scenario_id = settings.default_scenario
        self.speed = settings.default_speed
        self.state = SimulationState.STOPPED
        self.seed = 20240501
        self.rooms: list[RoomConfig] = list(rooms or [])
        self.house = VirtualHouse(
            scenario_id=self.scenario_id,
            mode=self.mode,
            seed=self.seed,
            devices=devices if devices is not None else catalogue_devices(),
        )

        # --- edge chain --------------------------------------------------- #
        self.extractor = FeatureExtractor()
        self.disaggregator = DeviceDisaggregator(list(self.house.specs.values()))
        self.engine = InferenceEngine(
            artifact_dir=settings.artifact_dir, backend=settings.inference_backend
        )
        self.tariff: Tariff = get_tariff(settings.default_tariff_id)
        self.tracker = EnergyTracker(self.tariff, settings.monthly_baseline_kwh)
        self.notifier = NotificationEngine(
            high_power_threshold_w=settings.high_power_threshold_w,
            daily_cost_alert_inr=settings.daily_cost_alert_inr,
            peak_current_alert_a=settings.peak_current_alert_a,
            sanctioned_load_w=settings.sanctioned_load_w,
        )

        # --- replay ------------------------------------------------------- #
        self.recorder = Recorder(settings.recordings_dir)
        self.player: RecordingPlayer | None = None
        self.recording_name: str | None = None

        # --- streams ------------------------------------------------------ #
        self.run_id = uuid.uuid4().hex
        self.buffer: deque[dict] = deque(maxlen=settings.live_buffer_size)
        self.latest_frame: dict | None = None
        self.recent_alerts: deque[dict] = deque(maxlen=100)
        self.recent_events: deque[dict] = deque(maxlen=200)

        self._subscribers: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

        # --- batching ----------------------------------------------------- #
        self._reading_rows: list[dict] = []
        self._bucket_rows: dict[tuple[datetime, str], dict] = {}
        self._event_rows: list[dict] = []
        self._notification_rows: list[dict] = []
        self._pending_events: list[_PendingEvent] = []

        # --- bookkeeping -------------------------------------------------- #
        self._previous_detected: set[str] = set()
        self._accuracy: deque[tuple[int, int, int]] = deque(maxlen=ACCURACY_WINDOW)
        self._inference_ms: deque[float] = deque(maxlen=120)
        self._loop_ms: deque[float] = deque(maxlen=120)
        self._detection_latencies: deque[int] = deque(maxlen=60)
        self.stats = PipelineStats()

    # ------------------------------------------------------------------ #
    # Subscriptions (WebSocket fan-out)
    # ------------------------------------------------------------------ #

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=8)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def _broadcast(self, message: dict) -> None:
        """Push a frame to every subscriber, dropping for slow consumers.

        A browser tab that has been backgrounded stops draining its queue.
        Blocking the simulation loop on it would stall the whole system, so a
        full queue simply loses the oldest frame -- this is live telemetry, and
        a stale frame is worth less than a current one.
        """
        for queue in list(self._subscribers):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(message)

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        async with self._lock:
            if self.state is SimulationState.RUNNING:
                return
            if self.state is SimulationState.STOPPED:
                self._reset_run_state()
            self.state = SimulationState.RUNNING
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run_loop(), name="nilm-loop")
        self._broadcast_status()

    async def pause(self) -> None:
        async with self._lock:
            if self.state is SimulationState.RUNNING:
                self.state = SimulationState.PAUSED
        self._broadcast_status()

    async def resume(self) -> None:
        async with self._lock:
            if self.state is SimulationState.PAUSED:
                self.state = SimulationState.RUNNING
        self._broadcast_status()

    async def stop(self) -> None:
        async with self._lock:
            self.state = SimulationState.STOPPED
            task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self.flush()
        self._broadcast_status()

    async def reset(
        self,
        scenario_id: str | None = None,
        mode: str | None = None,
        seed: int | None = None,
        clear_history: bool = True,
    ) -> None:
        """Restart the simulation from a clean state."""
        was_running = self.state is SimulationState.RUNNING
        await self.stop()

        if scenario_id is not None:
            self.scenario_id = scenario_id
        if mode is not None:
            self.mode = SimulationMode(mode)
        if seed is not None:
            self.seed = seed

        if clear_history:
            self.run_id = uuid.uuid4().hex

        self.house.reset(
            scenario_id=self.scenario_id, mode=self.mode, seed=self.seed
        )
        self._reset_run_state()

        if was_running:
            await self.start()
        else:
            self._broadcast_status()

    def _reset_run_state(self) -> None:
        self.extractor.reset()
        self.tracker.reset(self.tariff)
        self.notifier.reset()
        self.buffer.clear()
        self.recent_alerts.clear()
        self.recent_events.clear()
        self.latest_frame = None
        self._previous_detected.clear()
        self._accuracy.clear()
        self._inference_ms.clear()
        self._loop_ms.clear()
        self._detection_latencies.clear()
        self._reading_rows.clear()
        self._bucket_rows.clear()
        self._event_rows.clear()
        self._notification_rows.clear()
        self._pending_events.clear()
        self.stats = PipelineStats()
        if self.player is not None:
            self.player.reset()

    # ------------------------------------------------------------------ #
    # Controls
    # ------------------------------------------------------------------ #

    async def set_speed(self, speed: int) -> None:
        if speed not in ALLOWED_SPEEDS:
            raise ValueError(
                f"speed must be one of {ALLOWED_SPEEDS}, got {speed}"
            )
        self.speed = speed
        self._broadcast_status()

    async def set_scenario(self, scenario_id: str) -> None:
        if scenario_id not in SCENARIOS_BY_ID:
            raise KeyError(f"unknown scenario {scenario_id!r}")
        await self.reset(scenario_id=scenario_id, clear_history=False)

    async def set_mode(self, mode: str, recording_file: str | None = None) -> None:
        new_mode = SimulationMode(mode)
        if new_mode is SimulationMode.REPLAY:
            if recording_file is None:
                raise ValueError("replay mode needs a recording file")
            self.load_recording(recording_file)
        else:
            self.player = None
            self.recording_name = None
        await self.reset(mode=mode, clear_history=False)

    def set_appliance(self, appliance_id: str, on: bool) -> dict | None:
        """Manual appliance control from the dashboard."""
        event = self.house.set_appliance(appliance_id, on)
        return event.to_dict() if event else None

    def apply_house(self, rooms: list[RoomConfig], devices: list[DeviceConfig]) -> None:
        """Swap in an edited house configuration without stopping the loop.

        Runs on the event loop thread, between windows, so the loop never sees
        a half-applied configuration.
        """
        self.rooms = list(rooms)
        self.house.configure(devices)
        self.disaggregator = DeviceDisaggregator(list(self.house.specs.values()))
        self._broadcast_status()

    def set_tariff(self, tariff: Tariff) -> None:
        self.tariff = tariff
        self.tracker.set_tariff(tariff)
        self._broadcast_status()

    # ------------------------------------------------------------------ #
    # Recording / replay
    # ------------------------------------------------------------------ #

    def start_recording(self, name: str) -> str:
        path = self.recorder.start(
            name=name,
            scenario_id=self.scenario_id,
            mode=self.mode.value,
            seed=self.seed,
            start_sim_time=self.house.sim_time,
            device_ids=list(self.house.states),
        )
        self.recording_name = name
        return path.name

    def stop_recording(self) -> str | None:
        path = self.recorder.stop()
        return path.name if path else None

    def load_recording(self, file_name: str) -> dict:
        path = Path(self.settings.recordings_dir) / file_name
        if not path.exists():
            raise FileNotFoundError(f"no recording named {file_name}")
        recording = Recording.load(path)
        self.player = RecordingPlayer(recording, loop=True)
        self.recording_name = recording.header.name
        self.scenario_id = recording.header.scenario_id
        return recording.to_summary()

    def available_recordings(self) -> list[dict]:
        return list_recordings(self.settings.recordings_dir)

    # ------------------------------------------------------------------ #
    # The loop
    # ------------------------------------------------------------------ #

    async def _run_loop(self) -> None:
        """Drive the pipeline at ``speed`` simulated seconds per real second."""
        loop = asyncio.get_running_loop()
        next_tick = loop.time()

        try:
            while self.state is not SimulationState.STOPPED:
                if self.state is SimulationState.PAUSED:
                    await asyncio.sleep(0.1)
                    next_tick = loop.time()
                    continue

                started = loop.time()
                try:
                    frame = self._process_window()
                except Exception:  # pragma: no cover - keep the loop alive
                    logger.exception("pipeline window failed")
                    await asyncio.sleep(0.5)
                    continue

                self._broadcast({"type": "frame", "data": frame})

                # Timed region ends here: the batch flush below is disk I/O, not
                # pipeline work, and folding it in made every 25th window look
                # dramatically slower than the computation it actually did.
                elapsed = loop.time() - started
                self._loop_ms.append(elapsed * 1000.0)

                # Alerts are rare and someone may be waiting on the bell, so
                # they are written at once rather than with the next batch.
                if (
                    len(self._reading_rows) >= self.settings.persist_batch_size
                    or self._notification_rows
                ):
                    await self.flush()

                interval = 1.0 / max(self.speed, 1)
                next_tick += interval
                sleep_for = next_tick - loop.time()
                if sleep_for < -1.0:
                    # We have fallen far behind (e.g. the machine was suspended);
                    # resynchronise rather than trying to catch up forever.
                    next_tick = loop.time()
                    self.stats.behind_realtime = True
                elif sleep_for > 0:
                    self.stats.behind_realtime = False
                    await asyncio.sleep(sleep_for)
                else:
                    self.stats.behind_realtime = True
                    await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        finally:
            await self.flush()

    # ------------------------------------------------------------------ #
    # One window
    # ------------------------------------------------------------------ #

    def _process_window(self) -> dict:
        """Run the full edge chain for a single simulated second."""
        # --- 1. acquisition ------------------------------------------------ #
        if self.mode is SimulationMode.REPLAY and self.player is not None:
            frame = self.player.next_frame()
            if frame is not None:
                self.house.apply_recorded_state(frame.scales)
        window: RawWindow = self.house.step(1.0)

        if self.recorder.is_recording:
            self.recorder.append(window.sim_time, self.house.current_scales())

        # --- 2. feature extraction ----------------------------------------- #
        features = self.extractor.process(window.voltage, window.current)
        sequence = self.extractor.sequence()

        # --- 3. inference --------------------------------------------------- #
        result = self.engine.predict(
            sequence, current=window.current, voltage_rms=features.v_rms
        )
        self._inference_ms.append(result.latency_ms)
        detected = set(result.detected)

        # --- 4. disaggregation ---------------------------------------------- #
        specs = self.house.specs
        attribution = self.disaggregator.solve(
            window.current,
            total_power_w=features.real_power_w,
            voltage_rms=features.v_rms,
            probabilities=result.probabilities,
            thresholds=self.engine.thresholds,
        )

        # --- 5. energy and cost ---------------------------------------------- #
        energy = self.tracker.update(
            sim_time=window.sim_time,
            dt_s=1.0,
            total_power_w=features.real_power_w,
            appliance_power_w=attribution.power_w,
            unattributed_w=attribution.unattributed_w,
        )

        # --- 6. events and alerts --------------------------------------------- #
        newly_detected = sorted(detected - self._previous_detected)
        newly_stopped = sorted(self._previous_detected - detected)
        self._previous_detected = detected

        devices_on = {
            device_id
            for device_id, watts in attribution.power_w.items()
            if device_id in specs
            and watts >= DEVICE_ON_FRACTION * specs[device_id].rated_power_w
        }
        self._register_events(window, devices_on)

        alerts = self.notifier.evaluate(
            AlertContext(
                sim_time=window.sim_time,
                sim_seconds=window.sim_seconds,
                power_w=features.real_power_w,
                current_a=features.i_rms,
                peak_current_a=features.i_peak,
                power_factor=features.power_factor,
                detected=sorted(detected),
                newly_detected=newly_detected,
                newly_stopped=newly_stopped,
                appliance_power_w=attribution.power_w,
                appliance_runtime_s={
                    aid: totals.runtime_s_today
                    for aid, totals in energy.per_appliance.items()
                },
                cost_today_inr=energy.cost.today_inr,
                energy_today_wh=energy.energy_wh_today,
                currency_symbol=self.tariff.currency_symbol,
                specs=specs,
            )
        )
        for alert in alerts:
            payload = alert.to_dict()
            self.recent_alerts.appendleft(payload)
            self._notification_rows.append(
                {
                    "sim_time": alert.sim_time,
                    "recorded_at": datetime.now(),
                    "level": alert.level.value,
                    "category": alert.category,
                    "title": alert.title,
                    "message": alert.message,
                    "value": alert.value,
                    "run_id": self.run_id,
                }
            )

        # --- 7. scoring -------------------------------------------------------- #
        # Scored at the level the classifier works at: catalogue types.
        truth = window.ground_truth.drawing_types()
        self._accuracy.append(
            (
                len(detected & truth),
                len(detected - truth),
                len(truth - detected),
            )
        )

        # --- 8. persistence ---------------------------------------------------- #
        self._queue_persistence(
            window, features, attribution, energy, detected, result.probabilities
        )

        # --- 9. the frame ------------------------------------------------------ #
        frame_payload = self._build_frame(
            window, features, result, attribution, energy, alerts, devices_on
        )
        self.buffer.append(frame_payload)
        self.latest_frame = frame_payload
        self.stats.windows_processed += 1
        if self._inference_ms:
            self.stats.inference_ms_median = float(np.median(self._inference_ms))
            self.stats.inference_ms_p95 = float(np.percentile(self._inference_ms, 95))
        self.stats.loop_ms_median = (
            float(np.median(self._loop_ms)) if self._loop_ms else 0.0
        )
        return frame_payload

    # ------------------------------------------------------------------ #

    def _register_events(self, window: RawWindow, devices_on: set[str]) -> None:
        """Queue simulator events and check whether the model confirms them.

        Confirmation is per device: the classifier must have detected the type
        *and* the disaggregator must have given this particular device its
        share, so switching on the study fan is not "confirmed" by the
        bedroom fan already running.
        """
        for event in window.events:
            payload = event.to_dict()
            self.recent_events.appendleft(payload)
            row = {
                "sim_time": event.timestamp,
                "recorded_at": datetime.now(),
                "appliance_id": event.appliance_id,
                "appliance_name": event.appliance_name,
                "action": event.action.value,
                "source": event.source.value,
                "note": event.note,
                "power_w": event.power_w,
                "detected_by_model": False,
                "run_id": self.run_id,
            }
            self._pending_events.append(
                _PendingEvent(
                    row=row,
                    appliance_id=event.appliance_id,
                    action=event.action.value,
                    windows_left=DETECTION_GRACE_WINDOWS,
                )
            )

        # Give the model a few windows to react before recording the verdict:
        # the classifier looks at an eight-second sequence, so expecting it to
        # respond within the same second it was switched would be unfair.
        still_pending: list[_PendingEvent] = []
        for pending in self._pending_events:
            is_on = pending.appliance_id in devices_on
            wanted = is_on if pending.action == "on" else not is_on
            if wanted and not pending.detected:
                pending.detected = True
                pending.row["detected_by_model"] = True
                latency = DETECTION_GRACE_WINDOWS - pending.windows_left
                pending.latency_windows = latency
                if pending.action == "on":
                    self._detection_latencies.append(latency)

            pending.windows_left -= 1
            if pending.windows_left <= 0 or pending.detected:
                self._event_rows.append(pending.row)
            else:
                still_pending.append(pending)
        self._pending_events = still_pending

    # ------------------------------------------------------------------ #

    def _queue_persistence(
        self,
        window: RawWindow,
        features: WindowFeatures,
        attribution,
        energy,
        detected: set[str],
        probabilities: dict[str, float],
    ) -> None:
        """Buffer this window's database rows for the next batch flush."""
        self._reading_rows.append(
            {
                "recorded_at": datetime.now(),
                "sim_time": window.sim_time,
                "current_a": features.i_rms,
                "voltage_v": features.v_rms,
                "power_w": features.real_power_w,
                "reactive_var": features.reactive_power_var,
                "apparent_va": features.apparent_power_va,
                "power_factor": features.power_factor,
                "thd": features.thd,
                "peak_current_a": features.i_peak,
                "energy_wh": features.energy_wh,
                "cumulative_energy_wh": energy.energy_wh_session,
                "cost_inr": energy.cost.session_inr,
                "appliance_power": {
                    aid: round(watts, 2) for aid, watts in attribution.power_w.items()
                },
                "appliance_probability": {
                    aid: round(p, 3) for aid, p in probabilities.items()
                },
                "detected": sorted(detected),
                "unattributed_w": attribution.unattributed_w,
                "inference_ms": self._inference_ms[-1] if self._inference_ms else 0.0,
                "scenario": self.scenario_id,
                "mode": self.mode.value,
                "run_id": self.run_id,
            }
        )

        bucket_start = window.sim_time.replace(minute=0, second=0, microsecond=0)
        hours = 1.0 / 3600.0

        def add_bucket(appliance_id: str, watts: float, cost: float) -> None:
            key = (bucket_start, appliance_id)
            row = self._bucket_rows.get(key)
            if row is None:
                row = {
                    "bucket_start": bucket_start,
                    "appliance_id": appliance_id,
                    "energy_wh": 0.0,
                    "cost_inr": 0.0,
                    "runtime_s": 0.0,
                    "peak_power_w": 0.0,
                    "run_id": self.run_id,
                }
                self._bucket_rows[key] = row
            row["energy_wh"] += max(watts, 0.0) * hours
            row["cost_inr"] += cost
            row["peak_power_w"] = max(row["peak_power_w"], watts)
            if watts > 1.0:
                row["runtime_s"] += 1.0

        window_cost = energy.cost.session_inr
        previous_cost = getattr(self, "_previous_session_cost", 0.0)
        increment = max(window_cost - previous_cost, 0.0)
        self._previous_session_cost = window_cost

        total_power = max(features.real_power_w, 1e-9)
        add_bucket(TOTAL_KEY, features.real_power_w, increment)
        for appliance_id, watts in attribution.power_w.items():
            add_bucket(appliance_id, watts, increment * watts / total_power)
        add_bucket(
            UNATTRIBUTED_KEY,
            attribution.unattributed_w,
            increment * attribution.unattributed_w / total_power,
        )

    # ------------------------------------------------------------------ #

    def _build_frame(
        self,
        window: RawWindow,
        features: WindowFeatures,
        result,
        attribution,
        energy,
        alerts,
        devices_on: set[str],
    ) -> dict:
        """Assemble the JSON frame broadcast to the dashboard."""
        truth = window.ground_truth
        room_names = {room.id: room.name for room in self.rooms}
        detected_types = set(result.detected)
        voltage = max(features.v_rms, 1.0)

        appliances = []
        for device_id, state in self.house.states.items():
            spec = state.spec
            kind = spec.kind
            device = self.house.device_configs.get(device_id)
            totals = energy.per_appliance.get(device_id)
            estimated_w = attribution.power_w.get(device_id, 0.0)
            appliances.append(
                {
                    "id": device_id,
                    "type_id": kind,
                    "type_name": _TYPE_NAMES.get(kind, kind),
                    "name": spec.name,
                    "room_id": device.room_id if device else "",
                    "room_name": room_names.get(device.room_id, "") if device else "",
                    "icon": spec.icon,
                    "category": spec.category,
                    "colour": spec.colour,
                    "rated_power_w": spec.rated_power_w,
                    "power_factor": round(spec.power_factor, 3),
                    # Classifier output is per type, shared by its devices.
                    "probability": round(result.probabilities.get(kind, 0.0), 4),
                    "threshold": round(self.engine.thresholds.get(kind, 0.5), 3),
                    "type_detected": kind in detected_types,
                    "detected": device_id in devices_on,
                    "estimated_power_w": round(estimated_w, 1),
                    "estimated_current_a": round(
                        estimated_w / (voltage * max(spec.power_factor, 0.05)), 4
                    ),
                    # Ground truth travels beside the prediction so the UI can
                    # show both. The model never sees these fields.
                    "actual_power_w": round(truth.power_w.get(device_id, 0.0), 1),
                    "actual_current_a": round(truth.current_a.get(device_id, 0.0), 4),
                    "actually_on": truth.drawing.get(device_id, False),
                    "socket_on": truth.socket_on.get(device_id, False),
                    "energy_wh_today": round(totals.energy_wh_today, 3) if totals else 0.0,
                    "cost_today_inr": round(totals.cost_inr_today, 3) if totals else 0.0,
                    "cost_month_inr": round(totals.cost_inr_month, 3) if totals else 0.0,
                    "runtime_s_today": round(totals.runtime_s_today, 0) if totals else 0.0,
                }
            )

        truth_types = truth.drawing_types()
        device_count: dict[str, int] = {}
        for state in self.house.states.values():
            device_count[state.spec.kind] = device_count.get(state.spec.kind, 0) + 1
        types = [
            {
                "id": spec.id,
                "name": spec.name,
                "icon": spec.icon,
                "colour": spec.colour,
                "probability": round(result.probabilities.get(spec.id, 0.0), 4),
                "threshold": round(self.engine.thresholds.get(spec.id, 0.5), 3),
                "detected": spec.id in detected_types,
                "actually_on": spec.id in truth_types,
                "device_count": device_count.get(spec.id, 0),
            }
            for spec in APPLIANCE_CATALOGUE
        ]

        true_positive = sum(row[0] for row in self._accuracy)
        false_positive = sum(row[1] for row in self._accuracy)
        false_negative = sum(row[2] for row in self._accuracy)
        precision = (
            true_positive / (true_positive + false_positive)
            if (true_positive + false_positive)
            else 0.0
        )
        recall = (
            true_positive / (true_positive + false_negative)
            if (true_positive + false_negative)
            else 0.0
        )
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall)
            else 0.0
        )

        scope = slice(0, SCOPE_SAMPLES)
        return {
            "sim_time": window.sim_time.isoformat(),
            "sim_seconds": window.sim_seconds,
            "wall_time": datetime.now().isoformat(),
            "state": self.state.value,
            "mode": self.mode.value,
            "scenario": self.scenario_id,
            "speed": self.speed,
            "run_id": self.run_id,
            "measurement": {
                "current_a": round(features.i_rms, 4),
                "voltage_v": round(features.v_rms, 2),
                "power_w": round(features.real_power_w, 2),
                "reactive_var": round(features.reactive_power_var, 2),
                "apparent_va": round(features.apparent_power_va, 2),
                "power_factor": round(features.power_factor, 4),
                "thd": round(features.thd, 4),
                "peak_current_a": round(features.i_peak, 3),
                "crest_factor": round(features.crest_factor, 3),
                "frequency_hz": MAINS_FREQUENCY_HZ,
            },
            "energy": {
                "window_wh": round(features.energy_wh, 5),
                "today_wh": round(energy.energy_wh_today, 2),
                "month_wh": round(energy.energy_wh_month, 2),
                "session_wh": round(energy.energy_wh_session, 2),
                "peak_power_w": round(energy.peak_power_w_session, 1),
                "peak_power_today_w": round(energy.peak_power_w_today, 1),
                "average_power_w": round(energy.average_power_w, 1),
                "load_factor": round(energy.load_factor, 3),
                "elapsed_sim_s": energy.elapsed_sim_s,
                "sanctioned_load_w": self.settings.sanctioned_load_w,
            },
            "cost": {
                "today_inr": round(energy.cost.today_inr, 2),
                "month_inr": round(energy.cost.month_inr, 2),
                "session_inr": round(energy.cost.session_inr, 3),
                "projected_month_inr": round(energy.cost.projected_month_inr, 2),
                "monthly_bill_inr": round(energy.cost.monthly_bill_inr, 2),
                "marginal_rate_inr": round(energy.cost.marginal_rate_inr, 2),
                "effective_rate_inr": round(energy.cost.effective_rate_inr, 2),
                "tariff_name": energy.cost.tariff_name,
                "currency_symbol": energy.cost.currency_symbol,
            },
            "appliances": appliances,
            "types": types,
            "rooms": [{"id": room.id, "name": room.name} for room in self.rooms],
            "detected": list(result.detected),
            "unattributed_w": round(attribution.unattributed_w, 1),
            "residual_a": round(attribution.residual_a, 4),
            "inference": {
                "backend": result.backend,
                "latency_ms": round(result.latency_ms, 3),
                "median_latency_ms": round(self.stats.inference_ms_median, 3),
                "p95_latency_ms": round(self.stats.inference_ms_p95, 3),
            },
            "accuracy": {
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
                "window": len(self._accuracy),
                "avg_detection_latency_s": (
                    round(float(np.mean(self._detection_latencies)), 2)
                    if self._detection_latencies
                    else None
                ),
            },
            "events": [event.to_dict() for event in window.events],
            "alerts": [alert.to_dict() for alert in alerts],
            "scope": {
                "sample_rate_hz": SAMPLE_RATE_HZ,
                "current": [round(float(v), 4) for v in window.current[scope]],
                "voltage": [round(float(v), 2) for v in window.voltage[scope]],
            },
        }

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    async def flush(self) -> int:
        """Write buffered rows to SQLite in one transaction, off the loop."""
        if not (
            self._reading_rows
            or self._bucket_rows
            or self._event_rows
            or self._notification_rows
        ):
            return 0

        readings = self._reading_rows
        buckets = list(self._bucket_rows.values())
        events = self._event_rows
        notifications = self._notification_rows
        self._reading_rows = []
        self._bucket_rows = {}
        self._event_rows = []
        self._notification_rows = []

        written = await asyncio.to_thread(
            _write_batch, readings, buckets, events, notifications
        )
        self.stats.rows_written += written
        return written

    # ------------------------------------------------------------------ #
    # Status
    # ------------------------------------------------------------------ #

    def status(self) -> dict[str, Any]:
        scenario = SCENARIOS_BY_ID[self.scenario_id]
        return {
            "state": self.state.value,
            "mode": self.mode.value,
            "speed": self.speed,
            "seed": self.seed,
            "run_id": self.run_id,
            "scenario": {
                "id": scenario.id,
                "name": scenario.name,
                "description": scenario.description,
                "icon": scenario.icon,
                "start_hour": scenario.start_hour,
            },
            "sim_time": self.house.sim_time.isoformat(),
            "recording": {
                "active": self.recorder.is_recording,
                "frames": self.recorder.frame_count,
                "name": self.recording_name,
                "replay_progress": self.player.progress if self.player else None,
            },
            "tariff": self.tariff.to_dict(),
            "model": self.engine.info(),
            "stats": {
                "windows_processed": self.stats.windows_processed,
                "rows_written": self.stats.rows_written,
                "inference_ms_median": round(self.stats.inference_ms_median, 3),
                "inference_ms_p95": round(self.stats.inference_ms_p95, 3),
                "loop_ms_median": round(self.stats.loop_ms_median, 3),
                "behind_realtime": self.stats.behind_realtime,
                "buffered_rows": len(self._reading_rows),
                "subscribers": len(self._subscribers),
            },
        }

    def _broadcast_status(self) -> None:
        self._broadcast({"type": "status", "data": self.status()})


def _write_batch(
    readings: list[dict],
    buckets: list[dict],
    events: list[dict],
    notifications: list[dict],
) -> int:
    """Blocking database write, executed in a worker thread."""
    from backend.app.db.repositories.energy import EnergyRepository
    from backend.app.db.repositories.events import (
        EventRepository,
        NotificationRepository,
    )
    from backend.app.db.repositories.readings import ReadingRepository
    from backend.app.db.session import session_scope

    with session_scope() as session:
        written = ReadingRepository(session).bulk_insert(readings)
        EnergyRepository(session).accumulate(buckets)
        written += EventRepository(session).bulk_insert(events)
        written += NotificationRepository(session).bulk_insert(notifications)
    return written
