"""House scenarios and the three simulation modes.

Modes
-----
``DEMO``
    Plays a fixed, hand-authored timeline of appliance events.  Seeded, so
    every run is byte-for-byte identical.  This is the mode to present in.

``SIMULATION``
    Nobody scripts anything.  Each appliance decides for itself when to switch
    on, driven by its hourly usage profile and the scenario's activity level.
    Realistic and different every time.

``REPLAY``
    Re-runs a previously captured recording through the live pipeline, so a
    demonstration can be repeated exactly even after the code has changed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class SimulationMode(str, Enum):
    DEMO = "demo"
    SIMULATION = "simulation"
    REPLAY = "replay"


class EventAction(str, Enum):
    ON = "on"
    OFF = "off"


@dataclass(frozen=True)
class ScriptedEvent:
    """One switch action on the demo timeline."""

    #: Seconds of *simulated* time after the scenario starts.
    offset_s: float
    appliance_id: str
    action: EventAction
    note: str = ""


@dataclass(frozen=True)
class Scenario:
    """A named pattern of household behaviour."""

    id: str
    name: str
    description: str
    icon: str
    #: Hour of day the simulated clock starts at (may be fractional).
    start_hour: float
    #: Global multiplier on how often appliances get switched on.
    activity: float = 1.0
    #: Per-appliance multiplier applied on top of the hourly usage profile.
    probability_scale: Mapping[str, float] = field(default_factory=dict)
    #: Appliances forced on for the whole scenario.
    always_on: tuple[str, ...] = ()
    #: Appliances that never switch on in this scenario.
    never_on: tuple[str, ...] = ()
    #: Deterministic timeline used by DEMO mode.
    script: tuple[ScriptedEvent, ...] = ()

    @property
    def script_duration_s(self) -> float:
        return max((e.offset_s for e in self.script), default=0.0)


def _on(offset: float, appliance: str, note: str = "") -> ScriptedEvent:
    return ScriptedEvent(offset, appliance, EventAction.ON, note)


def _off(offset: float, appliance: str, note: str = "") -> ScriptedEvent:
    return ScriptedEvent(offset, appliance, EventAction.OFF, note)


# --------------------------------------------------------------------------- #
# Scenario definitions
# --------------------------------------------------------------------------- #

MORNING = Scenario(
    id="morning",
    name="Morning Rush",
    description=(
        "06:30 onwards. Lights and tube lights come on, breakfast is cooked on "
        "the induction stove, the mixer runs in short violent bursts, and the "
        "washing machine starts its cycle."
    ),
    icon="Sunrise",
    start_hour=6.5,
    activity=1.3,
    probability_scale={"mixer": 2.0, "induction_stove": 2.0, "washing_machine": 2.5},
    always_on=("refrigerator",),
    never_on=("air_conditioner",),
    script=(
        _on(0, "tube_light", "Kitchen tube light"),
        _on(45, "led_light", "Hall light"),
        _on(120, "induction_stove", "Tea on the stove"),
        _on(240, "mixer", "Chutney"),
        _off(300, "mixer"),
        _on(330, "microwave", "Reheating"),
        _off(420, "induction_stove"),
        _on(480, "mixer", "Batter"),
        _off(525, "mixer"),
        _off(540, "microwave"),
        _on(600, "washing_machine", "Laundry cycle"),
        _on(660, "tv", "Morning news"),
        _off(720, "tube_light"),
        _on(780, "laptop", "Work starts"),
        _off(840, "led_light"),
    ),
)

AFTERNOON = Scenario(
    id="afternoon",
    name="Afternoon Heat",
    description=(
        "13:00 onwards. The hottest part of the day: the air conditioner and "
        "fans dominate the load while someone works on a laptop."
    ),
    icon="Sun",
    start_hour=13.0,
    activity=0.8,
    probability_scale={"air_conditioner": 2.0, "fan": 2.0, "laptop": 1.8},
    always_on=("refrigerator",),
    never_on=("tube_light",),
    script=(
        _on(0, "fan", "Living room fan"),
        _on(30, "laptop", "Back to work"),
        _on(150, "air_conditioner", "Getting too warm"),
        _on(300, "mobile_charger", "Phone on charge"),
        _on(420, "tv", "Background TV"),
        _off(600, "fan", "AC is enough"),
        _on(720, "microwave", "Late lunch"),
        _off(810, "microwave"),
        _on(900, "fan"),
    ),
)

EVENING = Scenario(
    id="evening",
    name="Evening Peak",
    description=(
        "18:00 onwards. The classic Indian household peak - everyone is home, "
        "lights and fans go on, the TV starts, dinner gets cooked, and the "
        "air conditioner kicks in. This is the hardest case for NILM."
    ),
    icon="Sunset",
    start_hour=18.0,
    activity=1.5,
    probability_scale={"tv": 2.0, "led_light": 2.5, "tube_light": 2.0, "fan": 1.8},
    always_on=("refrigerator",),
    script=(
        _on(0, "fan", "Fan on"),
        _on(60, "led_light", "Hall lights"),
        _on(120, "tube_light", "Kitchen light"),
        _on(180, "tv", "Evening TV"),
        _on(300, "air_conditioner", "AC on"),
        _on(420, "mixer", "Dinner prep"),
        _off(480, "mixer"),
        _on(540, "induction_stove", "Cooking dinner"),
        _on(660, "mobile_charger", "Phone charging"),
        _on(780, "laptop"),
        _on(900, "mixer", "Grinding masala"),
        _off(960, "mixer"),
        _on(1020, "microwave", "Warming rotis"),
        _off(1110, "microwave"),
        _off(1200, "induction_stove", "Dinner ready"),
    ),
)

NIGHT = Scenario(
    id="night",
    name="Night",
    description=(
        "22:30 onwards. The house winds down: lights go off one by one, phones "
        "go on charge, and only the fan, AC and refrigerator run through the "
        "night. Excellent for showing low-load disaggregation."
    ),
    icon="Moon",
    start_hour=22.5,
    activity=0.4,
    probability_scale={"mobile_charger": 2.5, "fan": 1.5, "air_conditioner": 1.4},
    always_on=("refrigerator",),
    never_on=("mixer", "washing_machine", "induction_stove", "microwave"),
    script=(
        _on(0, "fan"),
        _on(30, "led_light", "Bedroom light"),
        _on(60, "tv", "Late night show"),
        _on(120, "mobile_charger", "Phone on charge"),
        _on(240, "air_conditioner", "AC for the night"),
        _off(420, "tv", "Going to sleep"),
        _off(480, "led_light", "Lights out"),
        _on(600, "laptop", "Someone is still awake"),
        _off(900, "laptop"),
    ),
)

FESTIVAL = Scenario(
    id="festival",
    name="Festival Evening",
    description=(
        "19:00 onwards. Guests are over, every light is on, the kitchen is "
        "running flat out and the load approaches the sanctioned limit. Use "
        "this to demonstrate high-consumption alerts and peak-load warnings."
    ),
    icon="PartyPopper",
    start_hour=19.0,
    activity=2.2,
    probability_scale={
        "led_light": 3.0,
        "tube_light": 3.0,
        "tv": 2.5,
        "mixer": 2.5,
        "induction_stove": 2.5,
        "microwave": 2.0,
    },
    always_on=("refrigerator", "led_light", "tube_light"),
    script=(
        _on(0, "led_light", "Decorative lights"),
        _on(20, "tube_light"),
        _on(40, "fan"),
        _on(80, "tv", "Music on the TV"),
        _on(140, "air_conditioner", "Guests arriving"),
        _on(200, "induction_stove", "Cooking begins"),
        _on(260, "mixer"),
        _off(320, "mixer"),
        _on(360, "microwave"),
        _on(420, "mixer", "More grinding"),
        _off(470, "mixer"),
        _on(500, "washing_machine", "Everything at once"),
        _on(560, "laptop"),
        _on(600, "mobile_charger"),
        _off(700, "microwave"),
        _on(780, "mixer", "Dessert"),
        _off(840, "mixer"),
    ),
)

VACATION = Scenario(
    id="vacation",
    name="Vacation (Empty House)",
    description=(
        "The family is away. Only the refrigerator cycles, plus the standby "
        "draw of everything left plugged in. Shows that the system correctly "
        "reports a near-empty house instead of hallucinating appliances."
    ),
    icon="Luggage",
    start_hour=10.0,
    activity=0.02,
    always_on=("refrigerator",),
    never_on=(
        "fan",
        "led_light",
        "tube_light",
        "tv",
        "mixer",
        "washing_machine",
        "air_conditioner",
        "laptop",
        "microwave",
        "induction_stove",
    ),
    script=(),
)

CUSTOM = Scenario(
    id="custom",
    name="Custom (Manual Control)",
    description=(
        "Nothing switches itself. You control every appliance by hand from the "
        "dashboard - ideal for showing the detector reacting live to a single "
        "load being toggled."
    ),
    icon="SlidersHorizontal",
    start_hour=12.0,
    activity=0.0,
    always_on=(),
    never_on=(),
    script=(),
)

SCENARIOS: tuple[Scenario, ...] = (
    MORNING,
    AFTERNOON,
    EVENING,
    NIGHT,
    FESTIVAL,
    VACATION,
    CUSTOM,
)

SCENARIOS_BY_ID: dict[str, Scenario] = {s.id: s for s in SCENARIOS}
DEFAULT_SCENARIO_ID: str = EVENING.id


def get_scenario(scenario_id: str) -> Scenario:
    try:
        return SCENARIOS_BY_ID[scenario_id]
    except KeyError:
        raise KeyError(
            f"Unknown scenario {scenario_id!r}. "
            f"Known scenarios: {', '.join(SCENARIOS_BY_ID)}"
        ) from None
