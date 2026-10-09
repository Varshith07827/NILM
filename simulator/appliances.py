"""Appliance catalogue for the virtual house.

Every appliance is described by the electrical quantities a real non-intrusive
load monitor would actually see at the mains: an RMS current, a *displacement*
phase angle, and a harmonic signature.

The important modelling decision here is that the nameplate power factor is
NOT applied as a single phase shift.  A real load's total power factor is the
product of two independent effects::

    PF_total = PF_displacement * PF_distortion

    PF_distortion = 1 / sqrt(1 + THD^2)

A ceiling fan (induction motor) draws an almost perfect sinusoid that lags the
voltage, so its poor-ish PF is almost entirely *displacement*.  A cheap LED
driver or a TV's SMPS draws a spiky, non-sinusoidal current that is roughly in
phase with the voltage, so its poor PF is almost entirely *distortion*.

Those two loads can have an identical RMS current and an identical power factor
and still be trivially separable in the harmonic domain -- which is precisely
what makes appliance-level disaggregation possible from a single clamp sensor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

# --------------------------------------------------------------------------- #
# Mains constants (Indian domestic single-phase supply)
# --------------------------------------------------------------------------- #

NOMINAL_VOLTAGE_V: float = 230.0
MAINS_FREQUENCY_HZ: float = 50.0


class LoadType(str, Enum):
    """Physical class of the load -- drives transient and harmonic behaviour."""

    RESISTIVE = "resistive"
    INDUCTION_MOTOR = "induction_motor"
    UNIVERSAL_MOTOR = "universal_motor"
    COMPRESSOR = "compressor"
    SMPS = "smps"
    ELECTRONIC_BALLAST = "electronic_ballast"
    INDUCTION_HEATING = "induction_heating"


@dataclass(frozen=True)
class StartupProfile:
    """Inrush behaviour at switch-on.

    ``multiplier`` is the peak inrush expressed as a multiple of the steady
    running current; it decays exponentially over ``decay_cycles`` mains cycles.
    """

    multiplier: float = 1.0
    decay_cycles: float = 2.0

    @property
    def duration_s(self) -> float:
        # Decayed to <2% after ~4 time constants.
        return 4.0 * self.decay_cycles / MAINS_FREQUENCY_HZ


@dataclass(frozen=True)
class DutyCycle:
    """Thermostatic / mechanical cycling while the appliance is switched on.

    A refrigerator that is "on" at the socket is only *drawing* its compressor
    current for part of the time.  This is a major source of realism -- and a
    major source of difficulty for naive NILM algorithms.
    """

    on_s: float
    off_s: float
    jitter: float = 0.15
    #: Fraction of rated power drawn during the "off" part of the cycle
    #: (control board, lamp, standby electronics).
    idle_fraction: float = 0.0

    @property
    def ratio(self) -> float:
        return self.on_s / (self.on_s + self.off_s)


@dataclass(frozen=True)
class ApplianceSpec:
    """Complete electrical + behavioural signature of one appliance."""

    id: str
    name: str
    icon: str
    category: str
    load_type: LoadType
    rated_power_w: float
    power_factor: float
    #: Relative amplitude of each odd harmonic, fundamental normalised to 1.0.
    harmonics: Mapping[int, float]
    startup: StartupProfile = field(default_factory=StartupProfile)
    duty: DutyCycle | None = None
    #: Slow random walk of the load, as a fraction of rated power.
    fluctuation_pct: float = 0.02
    #: Fast per-sample sensor/load noise, as a fraction of rated current.
    noise_pct: float = 0.01
    #: Standby draw in watts while switched "off" at the socket (vampire load).
    standby_w: float = 0.0
    #: Typical minimum / maximum uninterrupted run time in seconds.
    min_runtime_s: float = 60.0
    max_runtime_s: float = 4 * 3600.0
    #: Probability the appliance is in use during each hour of the day.
    hourly_probability: tuple[float, ...] = tuple([0.1] * 24)
    colour: str = "#38bdf8"
    #: Catalogue type this spec is an instance of. Empty for the catalogue
    #: entries themselves, whose ``id`` *is* the type; set on the per-device
    #: specs built by :mod:`simulator.devices`.
    type_id: str = ""
    #: Signature variant within the type: 0 is the catalogue signature, 1.. are
    #: perturbed signatures that keep same-type devices separable (see
    #: :func:`simulator.devices.variant_spec`). Internal only, never displayed.
    variant: int = 0

    @property
    def kind(self) -> str:
        """The catalogue type -- what the classifier is able to recognise."""
        return self.type_id or self.id

    # ------------------------------------------------------------------ #
    # Derived electrical quantities
    # ------------------------------------------------------------------ #

    @property
    def rms_current_a(self) -> float:
        """Steady-state RMS current at nominal voltage."""
        return self.rated_power_w / (NOMINAL_VOLTAGE_V * self.power_factor)

    @property
    def harmonic_norm(self) -> float:
        """sqrt(sum of squared harmonic amplitudes), fundamental included."""
        total = 1.0
        for amplitude in self.harmonics.values():
            total += amplitude * amplitude
        return math.sqrt(total)

    @property
    def thd(self) -> float:
        """Total harmonic distortion of the current waveform (ratio, not %)."""
        total = sum(a * a for a in self.harmonics.values())
        return math.sqrt(total)

    @property
    def distortion_power_factor(self) -> float:
        """PF component caused purely by harmonic content."""
        return 1.0 / self.harmonic_norm

    @property
    def displacement_power_factor(self) -> float:
        """PF component caused purely by the fundamental phase shift."""
        return min(1.0, self.power_factor / self.distortion_power_factor)

    @property
    def phase_angle_rad(self) -> float:
        """Fundamental current lag behind the voltage, in radians."""
        return math.acos(max(-1.0, min(1.0, self.displacement_power_factor)))

    @property
    def reactive_power_var(self) -> float:
        """Fundamental reactive power drawn by the appliance."""
        fundamental_rms = self.rms_current_a * self.distortion_power_factor
        return NOMINAL_VOLTAGE_V * fundamental_rms * math.sin(self.phase_angle_rad)

    @property
    def peak_startup_current_a(self) -> float:
        return self.rms_current_a * self.startup.multiplier

    @property
    def average_duty(self) -> float:
        """Mean fraction of rated power drawn while switched on."""
        if self.duty is None:
            return 1.0
        return self.duty.ratio + (1.0 - self.duty.ratio) * self.duty.idle_fraction


# --------------------------------------------------------------------------- #
# Hourly usage profiles (index = hour of day, value = probability of being used)
# --------------------------------------------------------------------------- #

_ALWAYS = tuple([1.0] * 24)
_EVENING_LIGHTING = (
    0.05, 0.02, 0.02, 0.02, 0.05, 0.25, 0.45, 0.35, 0.15, 0.05, 0.02, 0.02,
    0.02, 0.02, 0.02, 0.05, 0.20, 0.65, 0.95, 0.95, 0.90, 0.75, 0.45, 0.15,
)
_LIVING_HOURS = (
    0.02, 0.01, 0.01, 0.01, 0.02, 0.10, 0.35, 0.55, 0.45, 0.30, 0.25, 0.30,
    0.40, 0.35, 0.30, 0.35, 0.45, 0.70, 0.85, 0.90, 0.85, 0.70, 0.40, 0.10,
)
_COOKING = (
    0.00, 0.00, 0.00, 0.00, 0.00, 0.05, 0.35, 0.55, 0.40, 0.10, 0.05, 0.20,
    0.45, 0.35, 0.05, 0.05, 0.10, 0.25, 0.50, 0.60, 0.35, 0.10, 0.02, 0.00,
)
_HOT_HOURS = (
    0.35, 0.30, 0.25, 0.20, 0.15, 0.10, 0.05, 0.05, 0.10, 0.20, 0.35, 0.50,
    0.65, 0.75, 0.80, 0.75, 0.65, 0.55, 0.55, 0.65, 0.75, 0.80, 0.70, 0.50,
)
_WORK_HOURS = (
    0.02, 0.01, 0.01, 0.01, 0.01, 0.02, 0.10, 0.25, 0.40, 0.65, 0.75, 0.75,
    0.60, 0.70, 0.75, 0.75, 0.70, 0.55, 0.45, 0.50, 0.55, 0.50, 0.30, 0.08,
)
_LAUNDRY = (
    0.00, 0.00, 0.00, 0.00, 0.00, 0.02, 0.15, 0.30, 0.35, 0.30, 0.20, 0.10,
    0.05, 0.05, 0.05, 0.05, 0.08, 0.10, 0.08, 0.05, 0.03, 0.02, 0.00, 0.00,
)
_OVERNIGHT_CHARGE = (
    0.55, 0.55, 0.55, 0.50, 0.40, 0.25, 0.20, 0.25, 0.20, 0.20, 0.25, 0.25,
    0.30, 0.30, 0.30, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60, 0.70, 0.75, 0.65,
)


# --------------------------------------------------------------------------- #
# The catalogue
# --------------------------------------------------------------------------- #

APPLIANCE_CATALOGUE: tuple[ApplianceSpec, ...] = (
    ApplianceSpec(
        id="fan",
        name="Ceiling Fan",
        icon="Fan",
        category="Comfort",
        load_type=LoadType.INDUCTION_MOTOR,
        rated_power_w=75.0,
        power_factor=0.95,
        # Capacitor-run induction motor: near-sinusoidal, slight slot harmonics.
        harmonics={3: 0.035, 5: 0.018, 7: 0.008},
        startup=StartupProfile(multiplier=2.6, decay_cycles=6.0),
        fluctuation_pct=0.015,
        noise_pct=0.012,
        min_runtime_s=600.0,
        max_runtime_s=8 * 3600.0,
        hourly_probability=_HOT_HOURS,
        colour="#38bdf8",
    ),
    ApplianceSpec(
        id="led_light",
        name="LED Light",
        icon="Lightbulb",
        category="Lighting",
        load_type=LoadType.SMPS,
        rated_power_w=9.0,
        power_factor=0.52,
        # Non-PFC capacitive-dropper driver: very spiky current, huge THD.
        harmonics={3: 0.78, 5: 0.55, 7: 0.36, 9: 0.22, 11: 0.14, 13: 0.09},
        startup=StartupProfile(multiplier=4.0, decay_cycles=0.5),
        fluctuation_pct=0.004,
        noise_pct=0.02,
        min_runtime_s=300.0,
        max_runtime_s=8 * 3600.0,
        hourly_probability=_EVENING_LIGHTING,
        colour="#fbbf24",
    ),
    ApplianceSpec(
        id="tube_light",
        name="Tube Light",
        icon="Lamp",
        category="Lighting",
        load_type=LoadType.ELECTRONIC_BALLAST,
        rated_power_w=40.0,
        power_factor=0.58,
        harmonics={3: 0.62, 5: 0.38, 7: 0.21, 9: 0.12, 11: 0.07},
        startup=StartupProfile(multiplier=3.2, decay_cycles=1.5),
        fluctuation_pct=0.006,
        noise_pct=0.015,
        min_runtime_s=300.0,
        max_runtime_s=8 * 3600.0,
        hourly_probability=_EVENING_LIGHTING,
        colour="#a3e635",
    ),
    ApplianceSpec(
        id="tv",
        name="Television",
        icon="Tv",
        category="Entertainment",
        load_type=LoadType.SMPS,
        rated_power_w=95.0,
        power_factor=0.66,
        harmonics={3: 0.58, 5: 0.31, 7: 0.16, 9: 0.09, 11: 0.05},
        startup=StartupProfile(multiplier=3.5, decay_cycles=1.0),
        fluctuation_pct=0.06,  # backlight tracks scene brightness
        noise_pct=0.02,
        standby_w=0.5,
        min_runtime_s=900.0,
        max_runtime_s=5 * 3600.0,
        hourly_probability=_LIVING_HOURS,
        colour="#c084fc",
    ),
    ApplianceSpec(
        id="refrigerator",
        name="Refrigerator",
        icon="Refrigerator",
        category="Kitchen",
        load_type=LoadType.COMPRESSOR,
        rated_power_w=150.0,
        power_factor=0.72,
        harmonics={3: 0.09, 5: 0.05, 7: 0.03},
        # Locked-rotor inrush of a hermetic compressor is brutal but brief.
        startup=StartupProfile(multiplier=7.5, decay_cycles=5.0),
        duty=DutyCycle(on_s=780.0, off_s=1320.0, jitter=0.2, idle_fraction=0.04),
        fluctuation_pct=0.02,
        noise_pct=0.01,
        min_runtime_s=24 * 3600.0,
        max_runtime_s=24 * 3600.0,
        hourly_probability=_ALWAYS,
        colour="#22d3ee",
    ),
    ApplianceSpec(
        id="mixer",
        name="Mixer Grinder",
        icon="Blend",
        category="Kitchen",
        load_type=LoadType.UNIVERSAL_MOTOR,
        rated_power_w=500.0,
        power_factor=0.88,
        # Brushed universal motor: commutation noise -> broad odd harmonics.
        harmonics={3: 0.14, 5: 0.09, 7: 0.06, 9: 0.04},
        startup=StartupProfile(multiplier=4.2, decay_cycles=8.0),
        fluctuation_pct=0.18,  # load varies wildly with what is being ground
        noise_pct=0.03,
        min_runtime_s=20.0,
        max_runtime_s=240.0,
        hourly_probability=_COOKING,
        colour="#fb7185",
    ),
    ApplianceSpec(
        id="washing_machine",
        name="Washing Machine",
        icon="WashingMachine",
        category="Utility",
        load_type=LoadType.INDUCTION_MOTOR,
        rated_power_w=450.0,
        power_factor=0.78,
        harmonics={3: 0.11, 5: 0.07, 7: 0.04},
        startup=StartupProfile(multiplier=5.0, decay_cycles=7.0),
        # Wash agitation: tumble one way, pause, tumble the other way.
        duty=DutyCycle(on_s=22.0, off_s=8.0, jitter=0.25, idle_fraction=0.06),
        fluctuation_pct=0.12,
        noise_pct=0.02,
        standby_w=1.2,
        min_runtime_s=1800.0,
        max_runtime_s=4500.0,
        hourly_probability=_LAUNDRY,
        colour="#60a5fa",
    ),
    ApplianceSpec(
        id="air_conditioner",
        name="Air Conditioner",
        icon="AirVent",
        category="Comfort",
        load_type=LoadType.COMPRESSOR,
        rated_power_w=1500.0,
        power_factor=0.91,
        harmonics={3: 0.07, 5: 0.04, 7: 0.02},
        startup=StartupProfile(multiplier=6.0, decay_cycles=9.0),
        duty=DutyCycle(on_s=600.0, off_s=300.0, jitter=0.18, idle_fraction=0.08),
        fluctuation_pct=0.04,
        noise_pct=0.01,
        standby_w=2.0,
        min_runtime_s=1800.0,
        max_runtime_s=8 * 3600.0,
        hourly_probability=_HOT_HOURS,
        colour="#2dd4bf",
    ),
    ApplianceSpec(
        id="laptop",
        name="Laptop",
        icon="Laptop",
        category="Electronics",
        load_type=LoadType.SMPS,
        rated_power_w=65.0,
        power_factor=0.61,
        harmonics={3: 0.64, 5: 0.36, 7: 0.19, 9: 0.11, 11: 0.06},
        startup=StartupProfile(multiplier=2.8, decay_cycles=0.8),
        fluctuation_pct=0.22,  # CPU load swings the draw a lot
        noise_pct=0.03,
        standby_w=0.3,
        min_runtime_s=1200.0,
        max_runtime_s=6 * 3600.0,
        hourly_probability=_WORK_HOURS,
        colour="#818cf8",
    ),
    ApplianceSpec(
        id="mobile_charger",
        name="Mobile Charger",
        icon="Smartphone",
        category="Electronics",
        load_type=LoadType.SMPS,
        rated_power_w=12.0,
        power_factor=0.50,
        harmonics={3: 0.82, 5: 0.58, 7: 0.39, 9: 0.25, 11: 0.16, 13: 0.10},
        startup=StartupProfile(multiplier=3.0, decay_cycles=0.4),
        # Fast charge -> taper -> trickle.
        fluctuation_pct=0.25,
        noise_pct=0.04,
        standby_w=0.1,
        min_runtime_s=1800.0,
        max_runtime_s=5 * 3600.0,
        hourly_probability=_OVERNIGHT_CHARGE,
        colour="#f472b6",
    ),
    ApplianceSpec(
        id="microwave",
        name="Microwave Oven",
        icon="Microwave",
        category="Kitchen",
        load_type=LoadType.RESISTIVE,
        rated_power_w=1200.0,
        power_factor=0.93,
        # Magnetron + HV transformer: notable 3rd harmonic.
        harmonics={3: 0.19, 5: 0.08, 7: 0.04},
        startup=StartupProfile(multiplier=3.8, decay_cycles=3.0),
        # Below full power the magnetron is pulsed on and off.
        duty=DutyCycle(on_s=18.0, off_s=6.0, jitter=0.1, idle_fraction=0.02),
        fluctuation_pct=0.03,
        noise_pct=0.015,
        standby_w=2.5,
        min_runtime_s=30.0,
        max_runtime_s=600.0,
        hourly_probability=_COOKING,
        colour="#f59e0b",
    ),
    ApplianceSpec(
        id="induction_stove",
        name="Induction Stove",
        icon="CookingPot",
        category="Kitchen",
        load_type=LoadType.INDUCTION_HEATING,
        rated_power_w=2000.0,
        power_factor=0.97,
        # Active PFC front end keeps the current clean despite the inverter.
        harmonics={3: 0.06, 5: 0.04, 7: 0.03, 9: 0.02},
        startup=StartupProfile(multiplier=2.2, decay_cycles=2.0),
        duty=DutyCycle(on_s=12.0, off_s=4.0, jitter=0.12, idle_fraction=0.03),
        fluctuation_pct=0.05,
        noise_pct=0.012,
        standby_w=1.0,
        min_runtime_s=120.0,
        max_runtime_s=2400.0,
        hourly_probability=_COOKING,
        colour="#ef4444",
    ),
)

APPLIANCES_BY_ID: dict[str, ApplianceSpec] = {a.id: a for a in APPLIANCE_CATALOGUE}
APPLIANCE_IDS: tuple[str, ...] = tuple(a.id for a in APPLIANCE_CATALOGUE)
NUM_APPLIANCES: int = len(APPLIANCE_CATALOGUE)

#: Highest harmonic order modelled anywhere in the catalogue.
MAX_HARMONIC: int = max(
    (max(a.harmonics) if a.harmonics else 1) for a in APPLIANCE_CATALOGUE
)


def get_appliance(appliance_id: str) -> ApplianceSpec:
    """Look up an appliance by id, raising a helpful error if unknown."""
    try:
        return APPLIANCES_BY_ID[appliance_id]
    except KeyError:
        raise KeyError(
            f"Unknown appliance {appliance_id!r}. "
            f"Known appliances: {', '.join(APPLIANCE_IDS)}"
        ) from None
