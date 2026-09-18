"""Simulation control endpoints (Modules 12 and 15)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.api.deps import PipelineDep
from backend.app.schemas.api import (
    ApplianceToggleRequest,
    MessageResponse,
    ModeRequest,
    RecordingRequest,
    ResetRequest,
    ScenarioRequest,
    SpeedRequest,
)
from simulator.appliances import APPLIANCES_BY_ID

router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.post("/start", response_model=MessageResponse)
async def start(pipeline: PipelineDep) -> MessageResponse:
    await pipeline.start()
    return MessageResponse(message="simulation running", detail=pipeline.status())


@router.post("/pause", response_model=MessageResponse)
async def pause(pipeline: PipelineDep) -> MessageResponse:
    await pipeline.pause()
    return MessageResponse(message="simulation paused", detail=pipeline.status())


@router.post("/resume", response_model=MessageResponse)
async def resume(pipeline: PipelineDep) -> MessageResponse:
    await pipeline.resume()
    return MessageResponse(message="simulation resumed", detail=pipeline.status())


@router.post("/stop", response_model=MessageResponse)
async def stop(pipeline: PipelineDep) -> MessageResponse:
    await pipeline.stop()
    return MessageResponse(message="simulation stopped", detail=pipeline.status())


@router.post("/reset", response_model=MessageResponse)
async def reset(request: ResetRequest, pipeline: PipelineDep) -> MessageResponse:
    try:
        await pipeline.reset(
            scenario_id=request.scenario_id,
            mode=request.mode,
            seed=request.seed,
            clear_history=request.clear_history,
        )
    except (KeyError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MessageResponse(message="simulation reset", detail=pipeline.status())


@router.post("/speed", response_model=MessageResponse)
async def set_speed(request: SpeedRequest, pipeline: PipelineDep) -> MessageResponse:
    await pipeline.set_speed(request.speed)
    return MessageResponse(
        message=f"speed set to {request.speed}x", detail=pipeline.status()
    )


@router.post("/scenario", response_model=MessageResponse)
async def set_scenario(
    request: ScenarioRequest, pipeline: PipelineDep
) -> MessageResponse:
    try:
        await pipeline.set_scenario(request.scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MessageResponse(
        message=f"scenario set to {request.scenario_id}", detail=pipeline.status()
    )


@router.post("/mode", response_model=MessageResponse)
async def set_mode(request: ModeRequest, pipeline: PipelineDep) -> MessageResponse:
    """Switch between Demo, Simulation and Replay mode."""
    try:
        await pipeline.set_mode(request.mode, request.recording_file)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MessageResponse(
        message=f"mode set to {request.mode}", detail=pipeline.status()
    )


@router.post("/appliance", response_model=MessageResponse)
async def toggle_appliance(
    request: ApplianceToggleRequest, pipeline: PipelineDep
) -> MessageResponse:
    """Manually switch an appliance, as if walking over to the wall socket."""
    if request.appliance_id not in APPLIANCES_BY_ID:
        raise HTTPException(
            status_code=404, detail=f"unknown appliance {request.appliance_id!r}"
        )
    event = pipeline.set_appliance(request.appliance_id, request.on)
    name = APPLIANCES_BY_ID[request.appliance_id].name
    return MessageResponse(
        message=f"{name} switched {'on' if request.on else 'off'}",
        detail={"event": event},
    )


# --------------------------------------------------------------------------- #
# Recording / replay
# --------------------------------------------------------------------------- #


@router.get("/recordings")
def list_recordings(pipeline: PipelineDep) -> dict:
    return {"recordings": pipeline.available_recordings()}


@router.post("/recordings/start", response_model=MessageResponse)
def start_recording(
    request: RecordingRequest, pipeline: PipelineDep
) -> MessageResponse:
    file_name = pipeline.start_recording(request.name)
    return MessageResponse(
        message=f"recording to {file_name}", detail={"file": file_name}
    )


@router.post("/recordings/stop", response_model=MessageResponse)
def stop_recording(pipeline: PipelineDep) -> MessageResponse:
    file_name = pipeline.stop_recording()
    if file_name is None:
        return MessageResponse(ok=False, message="no recording was in progress")
    return MessageResponse(
        message=f"recording saved as {file_name}", detail={"file": file_name}
    )
