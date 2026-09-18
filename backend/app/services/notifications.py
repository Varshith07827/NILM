"""Alerting rules (Module 14).

A small rules engine that watches each window and raises notifications for the
things a householder would actually want to be told about: the load approaching
the sanctioned limit, a heavy appliance starting, the daily cost crossing a
budget, or something being left running all night.

Every rule carries a cooldown measured in *simulated* seconds.  Without one, a
threshold rule fires every single window for as long as the condition holds and
buries the panel in a thousand identical alerts -- the classic way a demo
alerting system embarrasses itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from simulator.appliances import APPLIANCES_BY_ID


class AlertLevel(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Alert:
    """One raised notification."""

    sim_time: datetime
    level: AlertLevel
    category: str
    title: str
    message: str
    value: float = 0.0

    def to_dict(self) -> dict:
        return {
            "sim_time": self.sim_time.isoformat(),
            "level": self.level.value,
            "category": self.category,
            "title": self.title,
            "message": self.message,
            "value": round(self.value, 2),
        }


@dataclass
class AlertContext:
    """Everything the rules need to look at for one window."""

    sim_time: datetime
    sim_seconds: float
    power_w: float
    current_a: float
    peak_current_a: float
    power_factor: float
    detected: list[str]
    newly_detected: list[str]
    newly_stopped: list[str]
    appliance_power_w: dict[str, float]
    appliance_runtime_s: dict[str, float]
    cost_today_inr: float
    energy_today_wh: float
    currency_symbol: str = "₹"


class NotificationEngine:
    """Evaluates the alert rules against each window."""

    #: Rule id -> cooldown in simulated seconds.
    COOLDOWNS: dict[str, float] = {
        "high_power": 300.0,
        "peak_current": 300.0,
        "sanctioned_load": 180.0,
        "cost_budget": 3600.0,
        "poor_power_factor": 900.0,
        "heavy_appliance_start": 30.0,
        "appliance_stopped": 30.0,
        "long_running": 3600.0,
        "standby_drain": 7200.0,
    }

    #: Appliances big enough that starting one is worth announcing.
    HEAVY_LOAD_W: float = 400.0

    def __init__(
        self,
        high_power_threshold_w: float,
        daily_cost_alert_inr: float,
        peak_current_alert_a: float,
        sanctioned_load_w: float,
    ) -> None:
        self.high_power_threshold_w = high_power_threshold_w
        self.daily_cost_alert_inr = daily_cost_alert_inr
        self.peak_current_alert_a = peak_current_alert_a
        self.sanctioned_load_w = sanctioned_load_w
        self._last_fired: dict[str, float] = {}
        self._cost_budget_announced = False

    def reset(self) -> None:
        self._last_fired.clear()
        self._cost_budget_announced = False

    # ------------------------------------------------------------------ #

    def _ready(self, rule_id: str, sim_seconds: float) -> bool:
        """True when the rule is off cooldown."""
        cooldown = self.COOLDOWNS.get(rule_id, 60.0)
        last = self._last_fired.get(rule_id)
        if last is not None and sim_seconds - last < cooldown:
            return False
        self._last_fired[rule_id] = sim_seconds
        return True

    # ------------------------------------------------------------------ #

    def evaluate(self, context: AlertContext) -> list[Alert]:
        """Run every rule and return the alerts that fired."""
        alerts: list[Alert] = []
        symbol = context.currency_symbol

        # --- whole-house load ------------------------------------------ #
        if context.power_w >= self.sanctioned_load_w * 0.9:
            if self._ready("sanctioned_load", context.sim_seconds):
                alerts.append(
                    Alert(
                        sim_time=context.sim_time,
                        level=AlertLevel.CRITICAL,
                        category="load",
                        title="Approaching sanctioned load",
                        message=(
                            f"Drawing {context.power_w:,.0f} W against a sanctioned "
                            f"{self.sanctioned_load_w:,.0f} W. Turn something off "
                            "before the main breaker trips."
                        ),
                        value=context.power_w,
                    )
                )
        elif context.power_w >= self.high_power_threshold_w:
            if self._ready("high_power", context.sim_seconds):
                alerts.append(
                    Alert(
                        sim_time=context.sim_time,
                        level=AlertLevel.WARNING,
                        category="load",
                        title="High power consumption",
                        message=(
                            f"The house is drawing {context.power_w:,.0f} W, above "
                            f"the {self.high_power_threshold_w:,.0f} W alert level."
                        ),
                        value=context.power_w,
                    )
                )

        if context.peak_current_a >= self.peak_current_alert_a:
            if self._ready("peak_current", context.sim_seconds):
                alerts.append(
                    Alert(
                        sim_time=context.sim_time,
                        level=AlertLevel.WARNING,
                        category="load",
                        title="Current surge detected",
                        message=(
                            f"Instantaneous current peaked at "
                            f"{context.peak_current_a:.1f} A, most likely a motor "
                            "or compressor inrush."
                        ),
                        value=context.peak_current_a,
                    )
                )

        # --- power quality --------------------------------------------- #
        if 0.0 < context.power_factor < 0.7 and context.power_w > 200.0:
            if self._ready("poor_power_factor", context.sim_seconds):
                alerts.append(
                    Alert(
                        sim_time=context.sim_time,
                        level=AlertLevel.INFO,
                        category="quality",
                        title="Poor power factor",
                        message=(
                            f"Power factor is {context.power_factor:.2f}. The load "
                            "is dominated by switched-mode supplies and lighting "
                            "drivers rather than motors."
                        ),
                        value=context.power_factor,
                    )
                )

        # --- cost ------------------------------------------------------- #
        if (
            context.cost_today_inr >= self.daily_cost_alert_inr
            and not self._cost_budget_announced
        ):
            self._cost_budget_announced = True
            alerts.append(
                Alert(
                    sim_time=context.sim_time,
                    level=AlertLevel.WARNING,
                    category="cost",
                    title="Daily budget exceeded",
                    message=(
                        f"Today's electricity cost has reached "
                        f"{symbol}{context.cost_today_inr:,.2f}, past your "
                        f"{symbol}{self.daily_cost_alert_inr:,.0f} budget."
                    ),
                    value=context.cost_today_inr,
                )
            )

        # --- appliance events ------------------------------------------- #
        for appliance_id in context.newly_detected:
            spec = APPLIANCES_BY_ID.get(appliance_id)
            if spec is None:
                continue
            watts = context.appliance_power_w.get(appliance_id, spec.rated_power_w)
            if spec.rated_power_w >= self.HEAVY_LOAD_W:
                if self._ready(f"heavy_appliance_start", context.sim_seconds):
                    alerts.append(
                        Alert(
                            sim_time=context.sim_time,
                            level=AlertLevel.INFO,
                            category="appliance",
                            title=f"{spec.name} started",
                            message=(
                                f"Detected from the current signature, drawing "
                                f"about {watts:,.0f} W."
                            ),
                            value=watts,
                        )
                    )

        for appliance_id in context.newly_stopped:
            spec = APPLIANCES_BY_ID.get(appliance_id)
            if spec is None or spec.rated_power_w < self.HEAVY_LOAD_W:
                continue
            if self._ready("appliance_stopped", context.sim_seconds):
                alerts.append(
                    Alert(
                        sim_time=context.sim_time,
                        level=AlertLevel.SUCCESS,
                        category="appliance",
                        title=f"{spec.name} stopped",
                        message=f"{spec.name} is no longer drawing power.",
                        value=0.0,
                    )
                )

        # --- behavioural ------------------------------------------------ #
        for appliance_id, runtime in context.appliance_runtime_s.items():
            if runtime < 6 * 3600.0:
                continue
            spec = APPLIANCES_BY_ID.get(appliance_id)
            if spec is None or spec.duty is not None:
                continue  # thermostatic loads are meant to run all day
            if appliance_id not in context.detected:
                continue
            if self._ready(f"long_running", context.sim_seconds):
                alerts.append(
                    Alert(
                        sim_time=context.sim_time,
                        level=AlertLevel.INFO,
                        category="behaviour",
                        title=f"{spec.name} running a long time",
                        message=(
                            f"{spec.name} has been on for "
                            f"{runtime / 3600.0:.1f} hours today."
                        ),
                        value=runtime,
                    )
                )

        if 0.0 < context.power_w < 30.0 and self._ready(
            "standby_drain", context.sim_seconds
        ):
            alerts.append(
                Alert(
                    sim_time=context.sim_time,
                    level=AlertLevel.INFO,
                    category="behaviour",
                    title="Standby load only",
                    message=(
                        f"Only {context.power_w:.1f} W is flowing -- this is the "
                        "vampire draw of appliances left plugged in."
                    ),
                    value=context.power_w,
                )
            )

        return alerts
