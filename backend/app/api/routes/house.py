"""House configuration: rooms and devices, plus per-device history.

Reading is open; changing anything needs an admin token. Every change is
written to SQLite and then applied to the running simulation, so new devices
start drawing current (and being disaggregated) on the next window.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.deps import AdminDep, PipelineDep, SessionDep
from backend.app.db.repositories.energy import EnergyRepository
from backend.app.db.repositories.readings import ReadingRepository
from backend.app.db.session import session_scope
from backend.app.schemas.api import (
    DeviceCreateRequest,
    DeviceUpdateRequest,
    MessageResponse,
    RoomRequest,
)
from backend.app.services import house_config
from backend.app.services.house_config import HouseConfigError, NotFoundError
from backend.app.services.pipeline import NILMPipeline
from simulator.appliances import APPLIANCE_CATALOGUE, APPLIANCES_BY_ID
from simulator.devices import MAX_DEVICES_PER_TYPE, rating_bounds

router = APIRouter(tags=["house"])

T = TypeVar("T")


async def _mutate(pipeline: NILMPipeline, change: Callable[[Session], T]) -> T:
    """Apply a configuration change in a worker thread, then to the pipeline."""

    def run() -> tuple[T, house_config.HouseConfig]:
        with session_scope() as session:
            result = change(session)
            return result, house_config.load_house(session)

    try:
        result, config = await asyncio.to_thread(run)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except HouseConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="the house changed at the same time; reload and try again",
        ) from exc
    pipeline.apply_house(config.rooms, config.devices)
    return result


def _house_payload(pipeline: NILMPipeline) -> dict:
    devices = list(pipeline.house.device_configs.values())
    specs = pipeline.house.specs
    count: dict[str, int] = {}
    for device in devices:
        count[device.type_id] = count.get(device.type_id, 0) + 1
    return {
        "rooms": [
            {
                "id": room.id,
                "name": room.name,
                "device_ids": [d.id for d in devices if d.room_id == room.id],
            }
            for room in pipeline.rooms
        ],
        "devices": [
            {
                "id": d.id,
                "type_id": d.type_id,
                "room_id": d.room_id,
                "name": d.name,
                "rated_power_w": specs[d.id].rated_power_w,
                "catalogue_power_w": APPLIANCES_BY_ID[d.type_id].rated_power_w,
                "custom_rating": d.rated_power_w is not None,
                "power_factor": round(specs[d.id].power_factor, 3),
            }
            for d in devices
        ],
        "types": [
            {
                "id": spec.id,
                "name": spec.name,
                "icon": spec.icon,
                "category": spec.category,
                "colour": spec.colour,
                "rated_power_w": spec.rated_power_w,
                "min_power_w": rating_bounds(spec.id)[0],
                "max_power_w": rating_bounds(spec.id)[1],
                "device_count": count.get(spec.id, 0),
                "max_devices": MAX_DEVICES_PER_TYPE,
            }
            for spec in APPLIANCE_CATALOGUE
        ],
    }


@router.get("/house", summary="Rooms, devices and the types that can be added")
def get_house(pipeline: PipelineDep) -> dict:
    return _house_payload(pipeline)


# --------------------------------------------------------------------------- #
# Rooms
# --------------------------------------------------------------------------- #


@router.post("/house/rooms", response_model=MessageResponse, status_code=201)
async def create_room(
    body: RoomRequest, pipeline: PipelineDep, _: AdminDep
) -> MessageResponse:
    room = await _mutate(pipeline, lambda s: house_config.add_room(s, body.name))
    return MessageResponse(
        message=f"room {room.name!r} added", detail={"room_id": room.id}
    )


@router.patch("/house/rooms/{room_id}", response_model=MessageResponse)
async def rename_room(
    room_id: str, body: RoomRequest, pipeline: PipelineDep, _: AdminDep
) -> MessageResponse:
    room = await _mutate(
        pipeline, lambda s: house_config.rename_room(s, room_id, body.name)
    )
    return MessageResponse(message=f"room renamed to {room.name!r}")


@router.delete("/house/rooms/{room_id}", response_model=MessageResponse)
async def delete_room(
    room_id: str, pipeline: PipelineDep, _: AdminDep
) -> MessageResponse:
    removed = await _mutate(pipeline, lambda s: house_config.delete_room(s, room_id))
    return MessageResponse(
        message=f"room removed with {len(removed)} device(s)",
        detail={"removed_device_ids": removed},
    )


# --------------------------------------------------------------------------- #
# Devices
# --------------------------------------------------------------------------- #


@router.post("/house/devices", response_model=MessageResponse, status_code=201)
async def create_device(
    body: DeviceCreateRequest, pipeline: PipelineDep, _: AdminDep
) -> MessageResponse:
    device = await _mutate(
        pipeline,
        lambda s: house_config.add_device(
            s, body.type_id, body.room_id, body.name, body.rated_power_w
        ),
    )
    return MessageResponse(
        message=f"{device.name} added", detail={"device_id": device.id}
    )


@router.patch("/house/devices/{device_id}", response_model=MessageResponse)
async def update_device(
    device_id: str, body: DeviceUpdateRequest, pipeline: PipelineDep, _: AdminDep
) -> MessageResponse:
    changes: dict = {}
    if "name" in body.model_fields_set and body.name is not None:
        changes["name"] = body.name
    if "room_id" in body.model_fields_set and body.room_id is not None:
        changes["room_id"] = body.room_id
    if "rated_power_w" in body.model_fields_set:
        changes["rated_power_w"] = body.rated_power_w
    device = await _mutate(
        pipeline, lambda s: house_config.update_device(s, device_id, **changes)
    )
    return MessageResponse(message=f"{device.name} updated")


@router.delete("/house/devices/{device_id}", response_model=MessageResponse)
async def delete_device(
    device_id: str, pipeline: PipelineDep, _: AdminDep
) -> MessageResponse:
    await _mutate(pipeline, lambda s: house_config.delete_device(s, device_id))
    return MessageResponse(message="device removed")


# --------------------------------------------------------------------------- #
# Per-device history
# --------------------------------------------------------------------------- #


@router.get("/devices/{device_id}/history", summary="One device's power and cost history")
async def device_history(
    device_id: str,
    pipeline: PipelineDep,
    session: SessionDep,
    max_points: int = Query(default=600, ge=10, le=5000),
) -> dict:
    """Estimated power and current per second, and energy and cost per hour.

    Current is derived from the attributed power with the device's power
    factor -- the meter measures only the house total.
    """
    spec = pipeline.house.specs.get(device_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"no device {device_id!r}")
    await pipeline.flush()

    readings = ReadingRepository(session).between(pipeline.run_id, max_points=max_points)
    power_factor = max(spec.power_factor, 0.05)
    points = []
    for row in readings:
        watts = float((row.appliance_power or {}).get(device_id, 0.0))
        points.append(
            {
                "sim_time": row.sim_time.isoformat(),
                "power_w": round(watts, 2),
                "current_a": round(watts / (max(row.voltage_v, 1.0) * power_factor), 4),
            }
        )
    hourly = EnergyRepository(session).hourly_series(
        pipeline.run_id, appliance_id=device_id
    )
    return {
        "device_id": device_id,
        "name": spec.name,
        "points": points,
        "hourly": hourly,
    }
