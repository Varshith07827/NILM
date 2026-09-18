"""Live state, catalogue and model-introspection endpoints."""

from __future__ import annotations

import math

from fastapi import APIRouter, HTTPException, Query

from ai.disaggregate import signature_table
from backend.app.api.deps import PipelineDep
from backend.app.schemas.api import ApplianceSpecOut, ScenarioOut
from simulator.appliances import APPLIANCE_CATALOGUE
from simulator.scenarios import SCENARIOS

router = APIRouter(tags=["live"])


@router.get("/live", summary="Most recent processed window")
def get_live(pipeline: PipelineDep) -> dict:
    """The latest frame, identical in shape to what the WebSocket pushes.

    Useful for a first paint before the socket connects, and for clients that
    poll rather than stream.
    """
    if pipeline.latest_frame is None:
        return {
            "available": False,
            "status": pipeline.status(),
            "message": "the simulation has not produced a window yet",
        }
    return {"available": True, "frame": pipeline.latest_frame}


@router.get("/status", summary="Simulation and model status")
def get_status(pipeline: PipelineDep) -> dict:
    return pipeline.status()


@router.get("/buffer", summary="In-memory ring buffer of recent frames")
def get_buffer(
    pipeline: PipelineDep,
    limit: int = Query(default=300, ge=1, le=3600),
    fields: str = Query(
        default="compact",
        description="'compact' returns chart-ready series; 'full' returns whole frames",
    ),
) -> dict:
    """Recent frames straight from memory, for instant chart hydration.

    The dashboard calls this once on load so its charts are already populated
    before the first WebSocket frame arrives, instead of drawing themselves in
    from an empty axis.
    """
    frames = list(pipeline.buffer)[-limit:]
    if fields == "full":
        return {"count": len(frames), "frames": frames}

    return {
        "count": len(frames),
        "series": {
            "sim_time": [f["sim_time"] for f in frames],
            "current_a": [f["measurement"]["current_a"] for f in frames],
            "voltage_v": [f["measurement"]["voltage_v"] for f in frames],
            "power_w": [f["measurement"]["power_w"] for f in frames],
            "power_factor": [f["measurement"]["power_factor"] for f in frames],
            "thd": [f["measurement"]["thd"] for f in frames],
            "energy_wh": [f["energy"]["today_wh"] for f in frames],
            "cost_inr": [f["cost"]["today_inr"] for f in frames],
        },
    }


@router.get(
    "/appliances",
    response_model=list[ApplianceSpecOut],
    summary="The appliance catalogue and every derived electrical quantity",
)
def get_appliances() -> list[ApplianceSpecOut]:
    """Static catalogue.

    Everything here is *derived* from the nameplate values in
    :mod:`simulator.appliances` -- the phase angle, the distortion power
    factor, the THD -- so the numbers on screen are the same ones driving the
    waveform synthesis.
    """
    return [
        ApplianceSpecOut(
            id=spec.id,
            name=spec.name,
            icon=spec.icon,
            category=spec.category,
            colour=spec.colour,
            load_type=spec.load_type.value,
            rated_power_w=spec.rated_power_w,
            power_factor=spec.power_factor,
            rms_current_a=round(spec.rms_current_a, 4),
            displacement_power_factor=round(spec.displacement_power_factor, 4),
            distortion_power_factor=round(spec.distortion_power_factor, 4),
            phase_angle_deg=round(math.degrees(spec.phase_angle_rad), 2),
            thd_percent=round(spec.thd * 100.0, 1),
            peak_startup_current_a=round(spec.peak_startup_current_a, 3),
            startup_multiplier=spec.startup.multiplier,
            standby_w=spec.standby_w,
            has_duty_cycle=spec.duty is not None,
            duty_ratio=round(spec.duty.ratio, 3) if spec.duty else None,
            harmonics={str(k): v for k, v in spec.harmonics.items()},
        )
        for spec in APPLIANCE_CATALOGUE
    ]


@router.get(
    "/scenarios",
    response_model=list[ScenarioOut],
    summary="Available household scenarios",
)
def get_scenarios() -> list[ScenarioOut]:
    return [
        ScenarioOut(
            id=scenario.id,
            name=scenario.name,
            description=scenario.description,
            icon=scenario.icon,
            start_hour=scenario.start_hour,
            activity=scenario.activity,
            always_on=list(scenario.always_on),
            never_on=list(scenario.never_on),
            scripted_events=len(scenario.script),
            script_duration_s=scenario.script_duration_s,
        )
        for scenario in SCENARIOS
    ]


@router.get("/model", summary="Model card for the loaded classifier")
def get_model(pipeline: PipelineDep) -> dict:
    """What is actually running inference, and how well it scored."""
    info = pipeline.engine.info()
    info["thresholds"] = pipeline.engine.thresholds
    return info


@router.get("/model/signatures", summary="Harmonic signature matrix")
def get_signatures() -> dict:
    """The per-appliance harmonic fingerprints used by the disaggregator.

    This is the physical basis of the whole project: if two appliances had
    identical rows here, no amount of machine learning could separate them from
    a single-point measurement.
    """
    return {"orders": [1, 3, 5, 7, 9, 11, 13], "appliances": signature_table()}


@router.get("/alerts", summary="Recent notifications")
def get_alerts(
    pipeline: PipelineDep,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    return {"alerts": list(pipeline.recent_alerts)[:limit]}


@router.get("/events", summary="Recent appliance switching events")
def get_events(
    pipeline: PipelineDep,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    return {"events": list(pipeline.recent_events)[:limit]}
