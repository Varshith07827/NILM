"""Devices: concrete appliances placed in rooms.

The catalogue in :mod:`simulator.appliances` describes appliance *types*. A
house is made of *devices* -- a ceiling fan in the bedroom, another in the
study -- each an instance of a type with its own room, name and rating.

Why same-type devices need distinct signatures
----------------------------------------------
Two identical fans draw identical waveforms. Their harmonic phasors are the
same vector, so from a single mains measurement "fan A on" and "fan B on" are
literally the same signal. No amount of computation can separate them.

Real fans are not identical, though. Different models use different run
capacitors and windings, which shows up as a different displacement angle and
a slightly different harmonic mix. :func:`variant_spec` gives each additional
device of a type such a difference: its current is shifted by a multiple of
:data:`VARIANT_PHASE_STEP_DEG` and its harmonics mildly rescaled. Rated power
is unchanged; only the *shape* of the current differs.

How the system tells them apart
-------------------------------
In steady state the differences are too small to trust: neighbouring fan
variants are ~10 degrees apart, and a microwave running beside them wanders by
more current than separates two fans. At a *switch*, everything else cancels,
so :mod:`ai.device_tracker` attributes each switching step to the device whose
signature it matches and keeps per-device on/off state from that.

Measured with ``python -m ai.evaluate_devices`` on the default house (a ceiling
fan in each of five rooms), the right fan is identified in ~98% of windows when
the type itself is detected correctly and loads are quiet (night scenario,
perfect type detection), and in ~73-80% with the shipped classifier. The gap
is the classifier: it was trained with one device per type, so several fans
together read to it partly as a refrigerator compressor. Retraining on
multi-device houses is the fix; see ``docs/MODEL-CARD.md``.

Variants are spread over a limited range of angles, which is what caps
:data:`MAX_DEVICES_PER_TYPE` at five.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .appliances import APPLIANCE_CATALOGUE, ApplianceSpec, get_appliance

#: Phase shift between successive variants of one type.
VARIANT_PHASE_STEP_DEG: float = 10.0

#: Harmonic rescaling per variant index (index 0 is the catalogue signature).
VARIANT_HARMONIC_SCALES: tuple[float, ...] = (1.0, 1.4, 0.7, 1.8, 0.5)

#: Displacement angle limits for a variant, in degrees.
_MIN_PHASE_DEG: float = 2.0
_MAX_PHASE_DEG: float = 75.0

#: How many devices of one type can share the mains and still be separated.
MAX_DEVICES_PER_TYPE: int = 5

#: Allowed rating as a fraction of the catalogue rating. The classifier was
#: trained on catalogue ratings; far outside this band its features drift into
#: territory it has never seen.
RATING_MIN_FACTOR: float = 0.5
RATING_MAX_FACTOR: float = 2.0


@dataclass(frozen=True)
class RoomConfig:
    id: str
    name: str


@dataclass(frozen=True)
class DeviceConfig:
    """One device as stored in the house configuration."""

    id: str
    type_id: str
    room_id: str
    name: str
    variant: int = 0
    #: ``None`` means the catalogue rating.
    rated_power_w: float | None = None


#: The five rooms of the default house, matching the 3-D floor plan.
DEFAULT_ROOMS: tuple[RoomConfig, ...] = (
    RoomConfig("living", "Living Room"),
    RoomConfig("kitchen", "Kitchen"),
    RoomConfig("bedroom", "Bedroom"),
    RoomConfig("study", "Study"),
    RoomConfig("utility", "Utility"),
)

#: Room of each catalogue appliance in the default house.
DEFAULT_ROOM_OF_TYPE: dict[str, str] = {
    "fan": "living",
    "led_light": "living",
    "tv": "living",
    "tube_light": "kitchen",
    "refrigerator": "kitchen",
    "microwave": "kitchen",
    "mixer": "kitchen",
    "induction_stove": "kitchen",
    "air_conditioner": "bedroom",
    "mobile_charger": "bedroom",
    "laptop": "study",
    "washing_machine": "utility",
}


def variant_spec(base: ApplianceSpec, variant: int) -> ApplianceSpec:
    """The electrical signature of the ``variant``-th device of a type.

    Variant 0 is the catalogue signature unchanged. Higher variants alternate
    +1, -1, +2, -2 ... steps around the catalogue angle. A step that would go
    below the physical minimum is clamped to it rather than skipped, which
    keeps variants on the low-angle side. That matters: most catalogue loads
    sit between 35 and 45 degrees, and a fan pushed up into that band starts to
    look like a refrigerator to the classifier. (Measured: clamping low gives
    a type-level F1 of 0.83 on the five-fan house in the afternoon, against
    0.75 for always stepping upward.)
    """
    if variant <= 0:
        return base
    angles = _variant_angles(math.degrees(base.phase_angle_rad))
    new_phase = angles[min(variant, len(angles) - 1)]
    scale = VARIANT_HARMONIC_SCALES[variant % len(VARIANT_HARMONIC_SCALES)]
    harmonics = {order: min(0.95, amp * scale) for order, amp in base.harmonics.items()}
    norm = math.sqrt(1.0 + sum(a * a for a in harmonics.values()))
    power_factor = math.cos(math.radians(new_phase)) / norm
    return replace(base, harmonics=harmonics, power_factor=power_factor, variant=variant)


def _variant_angles(phase_deg: float) -> list[float]:
    """Displacement angles of variants 0..MAX-1 of a type."""
    min_gap = VARIANT_PHASE_STEP_DEG * 0.5
    angles = [phase_deg]
    for variant in range(1, MAX_DEVICES_PER_TYPE):
        magnitude = VARIANT_PHASE_STEP_DEG * ((variant + 1) // 2)
        sign = 1 if variant % 2 else -1
        angle = min(_MAX_PHASE_DEG, max(_MIN_PHASE_DEG, phase_deg + sign * magnitude))
        if any(abs(angle - other) < min_gap for other in angles):
            # Clamping put it on top of an earlier variant; go above them all.
            angle = min(_MAX_PHASE_DEG, max(angles) + VARIANT_PHASE_STEP_DEG)
        angles.append(angle)
    return angles


def device_spec(device: DeviceConfig) -> ApplianceSpec:
    """Full electrical + behavioural spec for one configured device."""
    base = get_appliance(device.type_id)
    spec = variant_spec(base, device.variant)
    rating = device.rated_power_w if device.rated_power_w else base.rated_power_w
    return replace(
        spec,
        id=device.id,
        name=device.name,
        type_id=base.id,
        rated_power_w=float(rating),
    )


def rating_bounds(type_id: str) -> tuple[float, float]:
    rated = get_appliance(type_id).rated_power_w
    return rated * RATING_MIN_FACTOR, rated * RATING_MAX_FACTOR


def default_device_name(type_id: str, room_name: str) -> str:
    return f"{room_name} {get_appliance(type_id).name}"


def catalogue_devices() -> list[DeviceConfig]:
    """One device per catalogue type, with ids equal to the type ids.

    This is the house the model was trained on, and what the simulator uses
    when no configuration is given. Keeping the ids identical to the type ids
    means demo scripts and old recordings address it unchanged.
    """
    return [
        DeviceConfig(
            id=spec.id,
            type_id=spec.id,
            room_id=DEFAULT_ROOM_OF_TYPE.get(spec.id, "living"),
            name=spec.name,
        )
        for spec in APPLIANCE_CATALOGUE
    ]


def default_house() -> tuple[list[RoomConfig], list[DeviceConfig]]:
    """The house the dashboard starts with: the catalogue plus a fan per room."""
    rooms = list(DEFAULT_ROOMS)
    names = {room.id: room.name for room in rooms}
    devices = [
        # Once there is a fan in every room, "Ceiling Fan" alone is ambiguous.
        replace(d, name=default_device_name("fan", names[d.room_id]))
        if d.type_id == "fan"
        else d
        for d in catalogue_devices()
    ]
    variant = 1
    for room in rooms:
        if room.id == DEFAULT_ROOM_OF_TYPE["fan"]:
            continue
        devices.append(
            DeviceConfig(
                id=f"fan-{room.id}",
                type_id="fan",
                room_id=room.id,
                name=default_device_name("fan", names[room.id]),
                variant=variant,
            )
        )
        variant += 1
    return rooms, devices


def next_free_variant(type_id: str, devices: list[DeviceConfig]) -> int | None:
    """Lowest variant index not yet used by a device of this type."""
    used = {d.variant for d in devices if d.type_id == type_id}
    for variant in range(MAX_DEVICES_PER_TYPE):
        if variant not in used:
            return variant
    return None
