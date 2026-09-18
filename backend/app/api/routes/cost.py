"""Cost, tariff and settings endpoints (Modules 7 and 15)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.api.deps import PipelineDep
from backend.app.schemas.api import (
    AlertSettingsRequest,
    MessageResponse,
    TariffOut,
    TariffRequest,
)
from backend.app.services.cost import TARIFF_PRESETS, Tariff, TariffSlab, get_tariff

router = APIRouter(tags=["cost"])


@router.get("/cost", summary="Current cost breakdown")
def get_cost(pipeline: PipelineDep) -> dict:
    """Live cost figures, plus the slab arithmetic behind the monthly bill."""
    snapshot = pipeline.tracker.snapshot()
    cost = snapshot.cost
    return {
        "today_inr": round(cost.today_inr, 2),
        "month_inr": round(cost.month_inr, 2),
        "session_inr": round(cost.session_inr, 3),
        "projected_month_inr": round(cost.projected_month_inr, 2),
        "monthly_bill_inr": round(cost.monthly_bill_inr, 2),
        "marginal_rate_inr": round(cost.marginal_rate_inr, 2),
        "effective_rate_inr": round(cost.effective_rate_inr, 2),
        "energy_today_kwh": round(snapshot.energy_wh_today / 1000.0, 4),
        "energy_month_kwh": round(snapshot.energy_wh_month / 1000.0, 4),
        "per_appliance": [
            {
                "appliance_id": appliance_id,
                "cost_today_inr": round(totals.cost_inr_today, 3),
                "cost_month_inr": round(totals.cost_inr_month, 3),
                "energy_today_wh": round(totals.energy_wh_today, 2),
                "energy_month_wh": round(totals.energy_wh_month, 2),
                "runtime_s_today": round(totals.runtime_s_today, 0),
            }
            for appliance_id, totals in snapshot.per_appliance.items()
        ],
        "slab_breakdown": cost.slab_breakdown,
        "tariff": pipeline.tariff.to_dict(),
    }


@router.get("/tariffs", response_model=list[TariffOut], summary="Built-in tariffs")
def get_tariffs() -> list[TariffOut]:
    return [TariffOut(**tariff.to_dict()) for tariff in TARIFF_PRESETS]


@router.post("/settings/tariff", response_model=MessageResponse)
def set_tariff(request: TariffRequest, pipeline: PipelineDep) -> MessageResponse:
    """Select a preset tariff, or install a fully custom slab structure."""
    if request.tariff_id and not request.slabs:
        try:
            tariff = get_tariff(request.tariff_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    elif request.slabs:
        tariff = Tariff(
            id=request.tariff_id or "custom",
            name=request.name or "Custom Tariff",
            description="User-defined tariff",
            slabs=tuple(
                TariffSlab(up_to_kwh=slab.up_to_kwh, rate_inr=slab.rate_inr)
                for slab in request.slabs
            ),
            fixed_charge_inr=request.fixed_charge_inr or 0.0,
        )
    else:
        raise HTTPException(
            status_code=400, detail="supply either tariff_id or a list of slabs"
        )

    pipeline.set_tariff(tariff)
    return MessageResponse(
        message=f"tariff set to {tariff.name}", detail={"tariff": tariff.to_dict()}
    )


@router.post("/settings/alerts", response_model=MessageResponse)
def set_alert_settings(
    request: AlertSettingsRequest, pipeline: PipelineDep
) -> MessageResponse:
    """Adjust the alert thresholds without restarting the simulation."""
    notifier = pipeline.notifier
    settings = pipeline.settings

    if request.high_power_threshold_w is not None:
        notifier.high_power_threshold_w = request.high_power_threshold_w
        settings.high_power_threshold_w = request.high_power_threshold_w
    if request.daily_cost_alert_inr is not None:
        notifier.daily_cost_alert_inr = request.daily_cost_alert_inr
        settings.daily_cost_alert_inr = request.daily_cost_alert_inr
    if request.peak_current_alert_a is not None:
        notifier.peak_current_alert_a = request.peak_current_alert_a
        settings.peak_current_alert_a = request.peak_current_alert_a
    if request.sanctioned_load_w is not None:
        notifier.sanctioned_load_w = request.sanctioned_load_w
        settings.sanctioned_load_w = request.sanctioned_load_w

    return MessageResponse(
        message="alert thresholds updated",
        detail={
            "high_power_threshold_w": notifier.high_power_threshold_w,
            "daily_cost_alert_inr": notifier.daily_cost_alert_inr,
            "peak_current_alert_a": notifier.peak_current_alert_a,
            "sanctioned_load_w": notifier.sanctioned_load_w,
        },
    )


@router.get("/settings", summary="Current settings")
def get_settings_endpoint(pipeline: PipelineDep) -> dict:
    settings = pipeline.settings
    return {
        "tariff": pipeline.tariff.to_dict(),
        "alerts": {
            "high_power_threshold_w": settings.high_power_threshold_w,
            "daily_cost_alert_inr": settings.daily_cost_alert_inr,
            "peak_current_alert_a": settings.peak_current_alert_a,
            "sanctioned_load_w": settings.sanctioned_load_w,
        },
        "simulation": {
            "mode": pipeline.mode.value,
            "scenario": pipeline.scenario_id,
            "speed": pipeline.speed,
            "seed": pipeline.seed,
        },
    }
