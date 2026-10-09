"""Pydantic request/response models.

Requests are all validated -- they come from outside and are the only place a
bad value can enter the system.

The high-rate live frame is deliberately *not* re-validated through Pydantic.
It is produced by :meth:`NILMPipeline._build_frame` from already-typed internal
objects, it is emitted up to sixty times a second, and its shape is pinned on
the consumer side by the TypeScript interfaces in ``frontend/src/types``.
Round-tripping it through a validator on every window would add latency to the
hot path to re-check data the process just constructed itself.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #


class SpeedRequest(BaseModel):
    speed: int = Field(..., description="Simulated seconds per real second")

    @field_validator("speed")
    @classmethod
    def _allowed(cls, value: int) -> int:
        allowed = (1, 2, 5, 10, 20, 60)
        if value not in allowed:
            raise ValueError(f"speed must be one of {allowed}")
        return value


class ScenarioRequest(BaseModel):
    scenario_id: str = Field(..., min_length=1, max_length=32)


class ModeRequest(BaseModel):
    mode: Literal["demo", "simulation", "replay"]
    recording_file: str | None = None


class ResetRequest(BaseModel):
    scenario_id: str | None = None
    mode: Literal["demo", "simulation", "replay"] | None = None
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)
    clear_history: bool = True


class ApplianceToggleRequest(BaseModel):
    appliance_id: str = Field(..., min_length=1, max_length=32)
    on: bool


class TariffSlabInput(BaseModel):
    up_to_kwh: float | None = Field(default=None, gt=0)
    rate_inr: float = Field(..., ge=0, le=1000)


class TariffRequest(BaseModel):
    """Either select a preset by id, or supply a complete custom tariff."""

    tariff_id: str | None = None
    name: str | None = Field(default=None, max_length=80)
    fixed_charge_inr: float | None = Field(default=None, ge=0, le=100_000)
    slabs: list[TariffSlabInput] | None = None

    @field_validator("slabs")
    @classmethod
    def _ascending(
        cls, slabs: list[TariffSlabInput] | None
    ) -> list[TariffSlabInput] | None:
        if not slabs:
            return slabs
        boundaries = [s.up_to_kwh for s in slabs]
        if any(b is None for b in boundaries[:-1]):
            raise ValueError("only the final slab may be open-ended")
        if boundaries[-1] is not None:
            # Otherwise units beyond the last boundary would be billed at zero.
            raise ValueError("the final slab must be open-ended")
        finite = [b for b in boundaries if b is not None]
        if finite != sorted(finite) or len(set(finite)) != len(finite):
            raise ValueError("slab boundaries must ascend")
        return slabs


class AlertSettingsRequest(BaseModel):
    high_power_threshold_w: float | None = Field(default=None, ge=0, le=100_000)
    daily_cost_alert_inr: float | None = Field(default=None, ge=0, le=1_000_000)
    peak_current_alert_a: float | None = Field(default=None, ge=0, le=1000)
    sanctioned_load_w: float | None = Field(default=None, ge=100, le=100_000)


class RecordingRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


class ReportRequest(BaseModel):
    period: Literal["daily", "weekly", "monthly"] = "daily"
    format: Literal["json", "csv", "pdf"] = "json"


# --------------------------------------------------------------------------- #
# Responses
# --------------------------------------------------------------------------- #


class ApplianceSpecOut(BaseModel):
    """Static description of one appliance in the catalogue."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    icon: str
    category: str
    colour: str
    load_type: str
    rated_power_w: float
    power_factor: float
    rms_current_a: float
    displacement_power_factor: float
    distortion_power_factor: float
    phase_angle_deg: float
    thd_percent: float
    peak_startup_current_a: float
    startup_multiplier: float
    standby_w: float
    has_duty_cycle: bool
    duty_ratio: float | None
    harmonics: dict[str, float]


class ScenarioOut(BaseModel):
    id: str
    name: str
    description: str
    icon: str
    start_hour: float
    activity: float
    always_on: list[str]
    never_on: list[str]
    scripted_events: int
    script_duration_s: float


class TariffOut(BaseModel):
    id: str
    name: str
    description: str
    fixed_charge_inr: float
    currency: str
    currency_symbol: str
    slabs: list[dict[str, Any]]


class HistoryPoint(BaseModel):
    sim_time: datetime
    current_a: float
    voltage_v: float
    power_w: float
    power_factor: float
    thd: float
    energy_wh: float
    cost_inr: float
    detected: list[str]


class HistoryResponse(BaseModel):
    run_id: str
    points: list[HistoryPoint]
    total_rows: int
    decimated: bool


class ApplianceEnergyOut(BaseModel):
    appliance_id: str
    name: str
    colour: str
    energy_wh: float
    energy_kwh: float
    cost_inr: float
    runtime_s: float
    peak_power_w: float
    share: float


class ReportResponse(BaseModel):
    period: str
    generated_at: datetime
    start: datetime | None
    end: datetime | None
    total_energy_kwh: float
    total_cost_inr: float
    peak_power_w: float
    average_power_w: float
    appliances: list[ApplianceEnergyOut]
    hourly: list[dict[str, Any]]
    daily: list[dict[str, Any]]
    tariff: TariffOut


class MessageResponse(BaseModel):
    ok: bool = True
    message: str = ""
    detail: dict[str, Any] | None = None


# --------------------------------------------------------------------------- #
# Admin, house configuration, notifications
# --------------------------------------------------------------------------- #


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class LoginResponse(BaseModel):
    token: str
    username: str
    expires_at: float


class RoomRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=48)


class DeviceCreateRequest(BaseModel):
    type_id: str = Field(..., min_length=1, max_length=32)
    room_id: str = Field(..., min_length=1, max_length=32)
    name: str | None = Field(default=None, max_length=48)
    rated_power_w: float | None = Field(default=None, gt=0, le=10_000)


class DeviceUpdateRequest(BaseModel):
    """Only the fields present are changed.

    ``rated_power_w: null`` restores the catalogue rating; leaving the field
    out keeps the current one.
    """

    name: str | None = Field(default=None, max_length=48)
    room_id: str | None = Field(default=None, max_length=32)
    rated_power_w: float | None = Field(default=None, gt=0, le=10_000)


class NotificationReadRequest(BaseModel):
    ids: list[int] | None = Field(
        default=None, description="Notification ids to mark read; omit for all"
    )
