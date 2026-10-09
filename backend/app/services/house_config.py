"""The configured house: rooms and the devices in them.

Stored in SQLite so the layout survives restarts, seeded on first run with the
default house from :func:`simulator.devices.default_house`. Every mutation is
validated here rather than in the routes, so the rules -- at most
:data:`~simulator.devices.MAX_DEVICES_PER_TYPE` devices of one type, ratings
within the band the classifier can cope with -- hold however the change
arrives.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db.models import AppSetting, Device, Room
from simulator.appliances import APPLIANCES_BY_ID, get_appliance
from simulator.devices import (
    MAX_DEVICES_PER_TYPE,
    DeviceConfig,
    RoomConfig,
    default_device_name,
    default_house,
    next_free_variant,
    rating_bounds,
)

MAX_ROOMS: int = 12
MAX_NAME_LENGTH: int = 48


class HouseConfigError(ValueError):
    """A change that would leave the house in an invalid state."""


class NotFoundError(HouseConfigError):
    """The room or device does not exist."""


@dataclass
class HouseConfig:
    rooms: list[RoomConfig] = field(default_factory=list)
    devices: list[DeviceConfig] = field(default_factory=list)

    def room(self, room_id: str) -> RoomConfig | None:
        return next((r for r in self.rooms if r.id == room_id), None)


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #


def _to_device(row: Device) -> DeviceConfig:
    return DeviceConfig(
        id=row.id,
        type_id=row.type_id,
        room_id=row.room_id,
        name=row.name,
        variant=row.variant,
        rated_power_w=row.rated_power_w,
    )


def seed_if_empty(session: Session) -> bool:
    """Write the default house the first time the application starts."""
    if session.execute(select(func.count()).select_from(Room)).scalar_one():
        return False
    rooms, devices = default_house()
    for order, room in enumerate(rooms):
        session.add(Room(id=room.id, name=room.name, sort_order=order))
    for order, device in enumerate(devices):
        session.add(
            Device(
                id=device.id,
                type_id=device.type_id,
                room_id=device.room_id,
                name=device.name,
                variant=device.variant,
                rated_power_w=device.rated_power_w,
                sort_order=order,
            )
        )
    session.flush()
    return True


def load_house(session: Session) -> HouseConfig:
    rooms = session.execute(select(Room).order_by(Room.sort_order, Room.name)).scalars()
    devices = session.execute(
        select(Device).order_by(Device.sort_order, Device.name)
    ).scalars()
    return HouseConfig(
        rooms=[RoomConfig(id=r.id, name=r.name) for r in rooms],
        devices=[_to_device(d) for d in devices],
    )


# --------------------------------------------------------------------------- #
# Validation helpers
# --------------------------------------------------------------------------- #


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise HouseConfigError("name cannot be empty")
    if len(cleaned) > MAX_NAME_LENGTH:
        raise HouseConfigError(f"name is longer than {MAX_NAME_LENGTH} characters")
    return cleaned


def _check_rating(type_id: str, rated_power_w: float | None) -> float | None:
    if rated_power_w is None:
        return None
    low, high = rating_bounds(type_id)
    if not low <= rated_power_w <= high:
        name = get_appliance(type_id).name
        raise HouseConfigError(
            f"{name} rating must be between {low:g} W and {high:g} W "
            "(50-200% of the catalogue rating the model was trained on)"
        )
    return float(rated_power_w)


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:20]
    return slug or "room"


def _get_room(session: Session, room_id: str) -> Room:
    room = session.get(Room, room_id)
    if room is None:
        raise NotFoundError(f"no room {room_id!r}")
    return room


def _get_device(session: Session, device_id: str) -> Device:
    device = session.get(Device, device_id)
    if device is None:
        raise NotFoundError(f"no device {device_id!r}")
    return device


# --------------------------------------------------------------------------- #
# Rooms
# --------------------------------------------------------------------------- #


def add_room(session: Session, name: str) -> RoomConfig:
    name = _clean_name(name)
    count = session.execute(select(func.count()).select_from(Room)).scalar_one()
    if count >= MAX_ROOMS:
        raise HouseConfigError(f"a house can have at most {MAX_ROOMS} rooms")
    base = _slug(name)
    room_id, suffix = base, 2
    while session.get(Room, room_id) is not None:
        room_id = f"{base}-{suffix}"
        suffix += 1
    order = session.execute(select(func.max(Room.sort_order))).scalar_one() or 0
    session.add(Room(id=room_id, name=name, sort_order=order + 1))
    session.flush()
    return RoomConfig(id=room_id, name=name)


def rename_room(session: Session, room_id: str, name: str) -> RoomConfig:
    room = _get_room(session, room_id)
    room.name = _clean_name(name)
    session.flush()
    return RoomConfig(id=room.id, name=room.name)


def delete_room(session: Session, room_id: str) -> list[str]:
    """Remove a room and every device in it. Returns the removed device ids."""
    room = _get_room(session, room_id)
    devices = list(
        session.execute(select(Device).where(Device.room_id == room_id)).scalars()
    )
    removed = [d.id for d in devices]
    for device in devices:
        session.delete(device)
    session.delete(room)
    session.flush()
    return removed


# --------------------------------------------------------------------------- #
# Devices
# --------------------------------------------------------------------------- #


def add_device(
    session: Session,
    type_id: str,
    room_id: str,
    name: str | None = None,
    rated_power_w: float | None = None,
) -> DeviceConfig:
    if type_id not in APPLIANCES_BY_ID:
        raise HouseConfigError(f"unknown appliance type {type_id!r}")
    room = _get_room(session, room_id)
    current = load_house(session).devices
    variant = next_free_variant(type_id, current)
    if variant is None:
        raise HouseConfigError(
            f"the house already has {MAX_DEVICES_PER_TYPE} "
            f"{get_appliance(type_id).name} devices -- the most a single mains "
            "sensor can tell apart"
        )
    rating = _check_rating(type_id, rated_power_w)
    device_id = f"{type_id}-{uuid.uuid4().hex[:6]}"
    order = session.execute(select(func.max(Device.sort_order))).scalar_one() or 0
    row = Device(
        id=device_id,
        type_id=type_id,
        room_id=room.id,
        name=_clean_name(name) if name else default_device_name(type_id, room.name),
        variant=variant,
        rated_power_w=rating,
        sort_order=order + 1,
    )
    session.add(row)
    session.flush()
    return _to_device(row)


_UNSET = object()


def update_device(
    session: Session,
    device_id: str,
    *,
    name: str | None = None,
    room_id: str | None = None,
    rated_power_w: float | None | object = _UNSET,
) -> DeviceConfig:
    """Change a device. ``rated_power_w=None`` restores the catalogue rating."""
    device = _get_device(session, device_id)
    if name is not None:
        device.name = _clean_name(name)
    if room_id is not None:
        device.room_id = _get_room(session, room_id).id
    if rated_power_w is not _UNSET:
        device.rated_power_w = _check_rating(device.type_id, rated_power_w)  # type: ignore[arg-type]
    session.flush()
    return _to_device(device)


def delete_device(session: Session, device_id: str) -> None:
    session.delete(_get_device(session, device_id))
    session.flush()


# --------------------------------------------------------------------------- #
# Small persisted settings
# --------------------------------------------------------------------------- #


def get_setting(session: Session, key: str) -> dict | None:
    row = session.get(AppSetting, key)
    return row.value if row else None


def set_setting(session: Session, key: str, value: dict) -> None:
    row = session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value))
    else:
        row.value = value
    session.flush()
