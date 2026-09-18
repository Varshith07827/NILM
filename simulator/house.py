"""The virtual house.

Holds one runtime state object per appliance, decides when appliances switch
on and off, and aggregates their individual current waveforms into the single
mains signal that the "clamp sensor" would see.

Everything downstream of this module sees only the aggregate waveform -- the
per-appliance truth is kept aside purely so the AI can be scored against it.
That separation is what makes the demonstration honest: the detector never
gets to peek at the answer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

import numpy as np

from .appliances import (
    APPLIANCE_CATALOGUE,
    APPLIANCE_IDS,
    NOMINAL_VOLTAGE_V,
    ApplianceSpec,
    get_appliance,
)
from .scenarios import (
    DEFAULT_SCENARIO_ID,
    EventAction,
    Scenario,
    SimulationMode,
    get_scenario,
)
from .waveform import (
    SAMPLES_PER_WINDOW,
    HarmonicKernel,
    inrush_gain_vector,
    sagged_voltage_rms,
    sensor_noise,
    synthesise_voltage,
    time_axis,
)

#: Mean interval between switch-ons for an appliance whose usage probability is
#: exactly 1.0.  Scaled down by the scenario activity and the hourly profile.
BASE_SWITCH_ON_INTERVAL_S: float = 2400.0

#: How long a manual toggle from the dashboard suppresses autonomous control.
MANUAL_HOLD_S: float = 600.0

#: Correlation of the slow load random walk between consecutive seconds.
FLUCTUATION_MEMORY: float = 0.92

#: Random walk of the supply voltage caused by loads outside this house.
GRID_DRIFT_MEMORY: float = 0.995
GRID_DRIFT_SIGMA_V: float = 1.4


class EventSource(str, Enum):
    """Why an appliance changed state."""

    SCRIPT = "script"
    AUTONOMOUS = "autonomous"
    MANUAL = "manual"
    SCENARIO = "scenario"
    REPLAY = "replay"


@dataclass
class ApplianceEvent:
    """A single switch-on / switch-off, for the dashboard event log."""

    timestamp: datetime
    appliance_id: str
    appliance_name: str
    action: EventAction
    source: EventSource
    note: str = ""
    power_w: float = 0.0

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "appliance_id": self.appliance_id,
            "appliance_name": self.appliance_name,
            "action": self.action.value,
            "source": self.source.value,
            "note": self.note,
            "power_w": round(self.power_w, 2),
        }


@dataclass
class ApplianceState:
    """Mutable runtime state of one appliance."""

    spec: ApplianceSpec
    kernel: HarmonicKernel

    #: Switched on at the socket.
    socket_on: bool = False
    #: Simulated time (seconds since epoch of the run) of the last switch-on.
    switched_on_at: float = -1e9
    #: When autonomous control intends to switch it off again.
    scheduled_off_at: float = math.inf
    #: Duty (thermostat / agitation) sub-state while switched on.
    duty_on: bool = True
    duty_next_toggle_at: float = math.inf
    #: Slow multiplicative load fluctuation, centred on zero.
    fluctuation: float = 0.0
    #: Sim time until which manual control overrides autonomous behaviour.
    manual_hold_until: float = -1e9

    #: Filled in each window: true real power actually drawn, in watts.
    true_power_w: float = 0.0
    #: Filled in each window: true RMS current contribution, in amps.
    true_current_a: float = 0.0

    @property
    def power_scale(self) -> float:
        """Fraction of rated power being drawn right now, before inrush."""
        if not self.socket_on:
            if self.spec.rated_power_w <= 0.0:
                return 0.0
            return self.spec.standby_w / self.spec.rated_power_w
        base = 1.0
        if self.spec.duty is not None and not self.duty_on:
            base = self.spec.duty.idle_fraction
        return max(0.0, base * (1.0 + self.fluctuation))

    @property
    def is_drawing(self) -> bool:
        """True when the appliance is drawing more than standby power."""
        return self.socket_on and self.power_scale > 0.05


@dataclass
class GroundTruth:
    """What is *actually* running -- never shown to the detector."""

    socket_on: dict[str, bool] = field(default_factory=dict)
    drawing: dict[str, bool] = field(default_factory=dict)
    power_w: dict[str, float] = field(default_factory=dict)
    current_a: dict[str, float] = field(default_factory=dict)

    @property
    def active_ids(self) -> list[str]:
        return [aid for aid, on in self.drawing.items() if on]


@dataclass
class RawWindow:
    """One second of raw acquisition, plus the hidden ground truth."""

    sim_time: datetime
    sim_seconds: float
    t: np.ndarray
    voltage: np.ndarray
    current: np.ndarray
    voltage_rms: float
    ground_truth: GroundTruth
    events: list[ApplianceEvent] = field(default_factory=list)


class VirtualHouse:
    """A simulated household with twelve appliances on one mains feed."""

    def __init__(
        self,
        scenario_id: str = DEFAULT_SCENARIO_ID,
        mode: SimulationMode = SimulationMode.DEMO,
        seed: int = 20240501,
        start_date: datetime | None = None,
    ) -> None:
        self.scenario: Scenario = get_scenario(scenario_id)
        self.mode: SimulationMode = mode
        self.seed = seed
        self._rng = np.random.default_rng(seed)
        self._start_date = start_date or datetime.now().replace(
            microsecond=0, second=0, minute=0, hour=0
        )

        self.states: dict[str, ApplianceState] = {
            spec.id: ApplianceState(spec=spec, kernel=HarmonicKernel.from_spec(spec))
            for spec in APPLIANCE_CATALOGUE
        }

        self.sim_seconds: float = 0.0
        self._grid_drift_v: float = 0.0
        self._script_cursor: int = 0
        self._pending_events: list[ApplianceEvent] = []

        self._apply_scenario_defaults()

    # ------------------------------------------------------------------ #
    # Clock helpers
    # ------------------------------------------------------------------ #

    @property
    def sim_time(self) -> datetime:
        """Wall-clock time inside the simulation."""
        return (
            self._start_date
            + timedelta(hours=self.scenario.start_hour)
            + timedelta(seconds=self.sim_seconds)
        )

    # ------------------------------------------------------------------ #
    # Scenario / lifecycle
    # ------------------------------------------------------------------ #

    def _apply_scenario_defaults(self) -> None:
        """Put the house into a plausible state for the start of the scenario."""
        hour = int(self.scenario.start_hour) % 24
        for aid, state in self.states.items():
            state.socket_on = False
            state.switched_on_at = -1e9
            state.scheduled_off_at = math.inf
            state.duty_on = True
            state.duty_next_toggle_at = math.inf
            state.fluctuation = 0.0
            state.manual_hold_until = -1e9

            if aid in self.scenario.never_on:
                continue
            if aid in self.scenario.always_on:
                self._switch_on(state, EventSource.SCENARIO, log=False)
                continue
            # In free-running simulation, seed the house so it does not start
            # implausibly empty: appliances likely to be in use at this hour
            # are already running.
            if self.mode is SimulationMode.SIMULATION:
                probability = (
                    state.spec.hourly_probability[hour]
                    * self.scenario.probability_scale.get(aid, 1.0)
                    * self.scenario.activity
                )
                if self._rng.random() < min(0.85, probability * 0.5):
                    self._switch_on(state, EventSource.SCENARIO, log=False)
                    # Stagger the inrush transients into the past so the very
                    # first window is not a wall of simultaneous startups.
                    state.switched_on_at = -float(self._rng.uniform(30.0, 900.0))

    def reset(
        self,
        scenario_id: str | None = None,
        mode: SimulationMode | None = None,
        seed: int | None = None,
    ) -> None:
        """Restart the house, optionally with a new scenario / mode / seed."""
        if scenario_id is not None:
            self.scenario = get_scenario(scenario_id)
        if mode is not None:
            self.mode = mode
        if seed is not None:
            self.seed = seed
        self._rng = np.random.default_rng(self.seed)
        self.sim_seconds = 0.0
        self._grid_drift_v = 0.0
        self._script_cursor = 0
        self._pending_events.clear()
        self._apply_scenario_defaults()

    # ------------------------------------------------------------------ #
    # Switching
    # ------------------------------------------------------------------ #

    def _switch_on(
        self,
        state: ApplianceState,
        source: EventSource,
        note: str = "",
        log: bool = True,
    ) -> None:
        if state.socket_on:
            return
        state.socket_on = True
        state.switched_on_at = self.sim_seconds
        state.duty_on = True
        if state.spec.duty is not None:
            state.duty_next_toggle_at = self.sim_seconds + self._duty_length(
                state, on_phase=True
            )
        runtime = float(
            self._rng.uniform(state.spec.min_runtime_s, state.spec.max_runtime_s)
        )
        state.scheduled_off_at = self.sim_seconds + runtime
        if log:
            self._pending_events.append(
                ApplianceEvent(
                    timestamp=self.sim_time,
                    appliance_id=state.spec.id,
                    appliance_name=state.spec.name,
                    action=EventAction.ON,
                    source=source,
                    note=note,
                    power_w=state.spec.rated_power_w,
                )
            )

    def _switch_off(
        self,
        state: ApplianceState,
        source: EventSource,
        note: str = "",
        log: bool = True,
    ) -> None:
        if not state.socket_on:
            return
        state.socket_on = False
        state.scheduled_off_at = math.inf
        state.duty_next_toggle_at = math.inf
        if log:
            self._pending_events.append(
                ApplianceEvent(
                    timestamp=self.sim_time,
                    appliance_id=state.spec.id,
                    appliance_name=state.spec.name,
                    action=EventAction.OFF,
                    source=source,
                    note=note,
                    power_w=0.0,
                )
            )

    def set_appliance(self, appliance_id: str, on: bool) -> ApplianceEvent | None:
        """Manual control from the dashboard."""
        spec = get_appliance(appliance_id)
        state = self.states[spec.id]
        before = len(self._pending_events)
        if on:
            self._switch_on(state, EventSource.MANUAL, note="Switched from dashboard")
        else:
            self._switch_off(state, EventSource.MANUAL, note="Switched from dashboard")
        state.manual_hold_until = self.sim_seconds + MANUAL_HOLD_S
        return self._pending_events[before] if len(self._pending_events) > before else None

    def _duty_length(self, state: ApplianceState, on_phase: bool) -> float:
        duty = state.spec.duty
        assert duty is not None
        nominal = duty.on_s if on_phase else duty.off_s
        jitter = 1.0 + float(self._rng.uniform(-duty.jitter, duty.jitter))
        return max(1.0, nominal * jitter)

    # ------------------------------------------------------------------ #
    # Behaviour update
    # ------------------------------------------------------------------ #

    def _advance_script(self) -> None:
        """Fire every DEMO-mode event whose time has arrived."""
        script = self.scenario.script
        while (
            self._script_cursor < len(script)
            and script[self._script_cursor].offset_s <= self.sim_seconds
        ):
            event = script[self._script_cursor]
            self._script_cursor += 1
            state = self.states.get(event.appliance_id)
            if state is None:
                continue
            if event.action is EventAction.ON:
                self._switch_on(state, EventSource.SCRIPT, event.note)
            else:
                self._switch_off(state, EventSource.SCRIPT, event.note)

    def _advance_autonomous(self, dt: float) -> None:
        """Let each appliance decide for itself (SIMULATION mode)."""
        hour = self.sim_time.hour
        for aid, state in self.states.items():
            if aid in self.scenario.never_on:
                self._switch_off(state, EventSource.SCENARIO, log=False)
                continue
            if aid in self.scenario.always_on:
                self._switch_on(state, EventSource.SCENARIO, log=False)
                continue
            if self.sim_seconds < state.manual_hold_until:
                continue

            probability = (
                state.spec.hourly_probability[hour]
                * self.scenario.probability_scale.get(aid, 1.0)
                * self.scenario.activity
            )

            if not state.socket_on:
                if probability <= 0.0:
                    continue
                tau = BASE_SWITCH_ON_INTERVAL_S / probability
                if self._rng.random() < 1.0 - math.exp(-dt / tau):
                    self._switch_on(state, EventSource.AUTONOMOUS)
            else:
                if self.sim_seconds >= state.scheduled_off_at:
                    self._switch_off(state, EventSource.AUTONOMOUS)
                    continue
                # Appliances also get switched off early when the household
                # stops wanting them (the hour has moved on).
                if probability < 0.05:
                    tau = BASE_SWITCH_ON_INTERVAL_S * 0.25
                    if self._rng.random() < 1.0 - math.exp(-dt / tau):
                        self._switch_off(state, EventSource.AUTONOMOUS)

    def _advance_duty_and_noise(self, dt: float) -> None:
        """Update thermostat cycling and the slow load random walk."""
        for state in self.states.values():
            # --- duty cycling -------------------------------------------- #
            if state.socket_on and state.spec.duty is not None:
                if self.sim_seconds >= state.duty_next_toggle_at:
                    state.duty_on = not state.duty_on
                    state.duty_next_toggle_at = self.sim_seconds + self._duty_length(
                        state, on_phase=state.duty_on
                    )
                    if state.duty_on:
                        # A compressor restarting draws its inrush all over
                        # again -- the single most useful transient in NILM.
                        state.switched_on_at = self.sim_seconds

            # --- slow fluctuation ---------------------------------------- #
            sigma = state.spec.fluctuation_pct
            if sigma > 0.0:
                innovation = float(self._rng.normal(0.0, 1.0))
                state.fluctuation = FLUCTUATION_MEMORY * state.fluctuation + (
                    math.sqrt(1.0 - FLUCTUATION_MEMORY**2) * sigma * innovation
                )
                state.fluctuation = float(np.clip(state.fluctuation, -0.6, 0.6))

        # --- supply voltage wander --------------------------------------- #
        self._grid_drift_v = GRID_DRIFT_MEMORY * self._grid_drift_v + math.sqrt(
            1.0 - GRID_DRIFT_MEMORY**2
        ) * GRID_DRIFT_SIGMA_V * float(self._rng.normal(0.0, 1.0))

    # ------------------------------------------------------------------ #
    # Acquisition
    # ------------------------------------------------------------------ #

    def _synthesise(self) -> RawWindow:
        """Generate one second of voltage and aggregate current."""
        t = time_axis(self.sim_seconds, SAMPLES_PER_WINDOW)

        # First pass: how much current is flowing, so the sag can be applied.
        scales = {aid: s.power_scale for aid, s in self.states.items()}
        approx_total_a = sum(
            self.states[aid].spec.rms_current_a * scale for aid, scale in scales.items()
        )
        v_rms = sagged_voltage_rms(approx_total_a, drift_v=self._grid_drift_v)
        voltage = synthesise_voltage(t, v_rms)

        # Second pass: synthesise each appliance and measure its true power.
        total_current = np.zeros(SAMPLES_PER_WINDOW, dtype=np.float64)
        truth = GroundTruth()
        for aid, state in self.states.items():
            scale = scales[aid]
            spec = state.spec
            if scale <= 0.0:
                current = np.zeros(SAMPLES_PER_WINDOW)
            else:
                # Voltage sag reduces the current of resistive-ish loads and is
                # a second-order effect for regulated ones; applying it to all
                # keeps the aggregate self-consistent.
                target_rms = spec.rms_current_a * scale * (v_rms / NOMINAL_VOLTAGE_V)
                current = state.kernel.synthesise(t, target_rms)
                if state.socket_on:
                    current = current * inrush_gain_vector(
                        t, state.switched_on_at, spec
                    )
                if spec.noise_pct > 0.0:
                    current = current + self._rng.normal(
                        0.0,
                        spec.noise_pct * spec.rms_current_a * max(scale, 0.0),
                        size=SAMPLES_PER_WINDOW,
                    )

            total_current += current

            true_power = float(np.mean(voltage * current))
            true_current = float(np.sqrt(np.mean(current**2)))
            state.true_power_w = true_power
            state.true_current_a = true_current

            truth.socket_on[aid] = state.socket_on
            truth.drawing[aid] = state.is_drawing
            truth.power_w[aid] = true_power
            truth.current_a[aid] = true_current

        # Analogue front-end noise sits on the aggregate, not on each load.
        total_current += sensor_noise(SAMPLES_PER_WINDOW, self._rng)

        events = self._pending_events
        self._pending_events = []

        return RawWindow(
            sim_time=self.sim_time,
            sim_seconds=self.sim_seconds,
            t=t,
            voltage=voltage,
            current=total_current,
            voltage_rms=v_rms,
            ground_truth=truth,
            events=events,
        )

    # ------------------------------------------------------------------ #
    # Public stepping API
    # ------------------------------------------------------------------ #

    def step(self, dt: float = 1.0) -> RawWindow:
        """Advance the house by ``dt`` seconds and return one acquisition window."""
        if self.mode is SimulationMode.DEMO:
            self._advance_script()
        elif self.mode is SimulationMode.SIMULATION:
            self._advance_autonomous(dt)

        self._advance_duty_and_noise(dt)
        window = self._synthesise()
        self.sim_seconds += dt
        return window

    def apply_recorded_state(self, scales: dict[str, float]) -> None:
        """Force the house into a recorded state (REPLAY mode)."""
        for aid, scale in scales.items():
            state = self.states.get(aid)
            if state is None:
                continue
            was_on = state.socket_on
            now_on = scale > (state.spec.standby_w / max(state.spec.rated_power_w, 1e-9))
            state.socket_on = now_on
            if now_on and not was_on:
                state.switched_on_at = self.sim_seconds
                self._pending_events.append(
                    ApplianceEvent(
                        timestamp=self.sim_time,
                        appliance_id=aid,
                        appliance_name=state.spec.name,
                        action=EventAction.ON,
                        source=EventSource.REPLAY,
                        power_w=state.spec.rated_power_w,
                    )
                )
            elif was_on and not now_on:
                self._pending_events.append(
                    ApplianceEvent(
                        timestamp=self.sim_time,
                        appliance_id=aid,
                        appliance_name=state.spec.name,
                        action=EventAction.OFF,
                        source=EventSource.REPLAY,
                    )
                )
            # Reproduce the exact amplitude that was recorded.
            state.duty_on = True
            state.fluctuation = (scale - 1.0) if now_on else 0.0

    def current_scales(self) -> dict[str, float]:
        """Snapshot of every appliance amplitude, for recording."""
        return {aid: state.power_scale for aid, state in self.states.items()}

    def snapshot(self) -> list[dict]:
        """Per-appliance state for the dashboard."""
        out = []
        for aid in APPLIANCE_IDS:
            state = self.states[aid]
            spec = state.spec
            out.append(
                {
                    "id": aid,
                    "name": spec.name,
                    "icon": spec.icon,
                    "category": spec.category,
                    "colour": spec.colour,
                    "rated_power_w": spec.rated_power_w,
                    "socket_on": state.socket_on,
                    "drawing": state.is_drawing,
                    "true_power_w": round(state.true_power_w, 2),
                    "true_current_a": round(state.true_current_a, 4),
                }
            )
        return out
