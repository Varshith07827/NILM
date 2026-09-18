"""Energy estimation and accounting (Module 6).

Integrates instantaneous power into energy, keeps per-appliance and whole-house
running totals, and rolls those totals over at simulated day and month
boundaries.  Cost is applied at the *marginal* slab rate for the month so far
(see :mod:`backend.app.services.cost`).

All accounting is done against **simulated** time.  Running the simulation at
10x does not make the household consume ten times faster in energy terms -- one
simulated second is always one watt-second, which is what makes the "1 day of
usage in 2.4 minutes" demonstration meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from backend.app.services.cost import CostBreakdown, Tariff


@dataclass
class ApplianceTotals:
    """Running totals for a single appliance."""

    appliance_id: str
    energy_wh_session: float = 0.0
    energy_wh_today: float = 0.0
    energy_wh_month: float = 0.0
    cost_inr_session: float = 0.0
    cost_inr_today: float = 0.0
    cost_inr_month: float = 0.0
    runtime_s_today: float = 0.0
    runtime_s_session: float = 0.0
    peak_power_w: float = 0.0
    last_power_w: float = 0.0


@dataclass
class EnergySnapshot:
    """Everything the dashboard needs about energy for one window."""

    instantaneous_power_w: float = 0.0
    energy_wh_window: float = 0.0
    energy_wh_session: float = 0.0
    energy_wh_today: float = 0.0
    energy_wh_month: float = 0.0
    peak_power_w_session: float = 0.0
    peak_power_w_today: float = 0.0
    average_power_w: float = 0.0
    load_factor: float = 0.0
    elapsed_sim_s: float = 0.0
    per_appliance: dict[str, ApplianceTotals] = field(default_factory=dict)
    cost: CostBreakdown = field(default_factory=CostBreakdown)


class EnergyTracker:
    """Accumulates energy and cost across the run."""

    def __init__(self, tariff: Tariff, monthly_baseline_kwh: float = 0.0) -> None:
        self.tariff = tariff
        self.monthly_baseline_kwh = monthly_baseline_kwh

        self.totals: dict[str, ApplianceTotals] = {}
        self.unattributed = ApplianceTotals(appliance_id="__unattributed__")

        self.energy_wh_session = 0.0
        self.energy_wh_today = 0.0
        self.energy_wh_month = 0.0
        self.cost_inr_session = 0.0
        self.cost_inr_today = 0.0
        self.cost_inr_month = 0.0

        self.peak_power_w_session = 0.0
        self.peak_power_w_today = 0.0
        self.elapsed_sim_s = 0.0

        self._current_day: date | None = None
        self._current_month: tuple[int, int] | None = None

    # ------------------------------------------------------------------ #

    def reset(self, tariff: Tariff | None = None) -> None:
        """Clear every total, optionally switching tariff."""
        if tariff is not None:
            self.tariff = tariff
        self.__init__(self.tariff, self.monthly_baseline_kwh)  # noqa: PLC2801

    def set_tariff(self, tariff: Tariff) -> None:
        """Switch tariff and reprice the accumulated month.

        Repricing rather than leaving history at the old rate is the honest
        behaviour: the figures on screen should always be internally consistent
        with the tariff currently displayed beside them.
        """
        self.tariff = tariff
        month_kwh = self.energy_wh_month / 1000.0
        baseline = self.monthly_baseline_kwh
        self.cost_inr_month = tariff.cost_of(month_kwh, baseline)

        today_kwh = self.energy_wh_today / 1000.0
        self.cost_inr_today = tariff.cost_of(
            today_kwh, baseline + max(month_kwh - today_kwh, 0.0)
        )
        session_kwh = self.energy_wh_session / 1000.0
        self.cost_inr_session = tariff.cost_of(
            session_kwh, baseline + max(month_kwh - session_kwh, 0.0)
        )

        for totals in list(self.totals.values()) + [self.unattributed]:
            share = (
                totals.energy_wh_month / self.energy_wh_month
                if self.energy_wh_month > 0
                else 0.0
            )
            totals.cost_inr_month = self.cost_inr_month * share
            share_today = (
                totals.energy_wh_today / self.energy_wh_today
                if self.energy_wh_today > 0
                else 0.0
            )
            totals.cost_inr_today = self.cost_inr_today * share_today
            share_session = (
                totals.energy_wh_session / self.energy_wh_session
                if self.energy_wh_session > 0
                else 0.0
            )
            totals.cost_inr_session = self.cost_inr_session * share_session

    # ------------------------------------------------------------------ #

    def _roll_over(self, sim_time: datetime) -> None:
        """Reset daily / monthly counters when the simulated clock crosses over."""
        day = sim_time.date()
        month = (sim_time.year, sim_time.month)

        if self._current_day is None:
            self._current_day = day
            self._current_month = month
            return

        if month != self._current_month:
            self._current_month = month
            self.energy_wh_month = 0.0
            self.cost_inr_month = 0.0
            self.monthly_baseline_kwh = 0.0
            for totals in list(self.totals.values()) + [self.unattributed]:
                totals.energy_wh_month = 0.0
                totals.cost_inr_month = 0.0

        if day != self._current_day:
            self._current_day = day
            self.energy_wh_today = 0.0
            self.cost_inr_today = 0.0
            self.peak_power_w_today = 0.0
            for totals in list(self.totals.values()) + [self.unattributed]:
                totals.energy_wh_today = 0.0
                totals.cost_inr_today = 0.0
                totals.runtime_s_today = 0.0

    def _totals_for(self, appliance_id: str) -> ApplianceTotals:
        totals = self.totals.get(appliance_id)
        if totals is None:
            totals = ApplianceTotals(appliance_id=appliance_id)
            self.totals[appliance_id] = totals
        return totals

    # ------------------------------------------------------------------ #

    def update(
        self,
        sim_time: datetime,
        dt_s: float,
        total_power_w: float,
        appliance_power_w: dict[str, float],
        unattributed_w: float = 0.0,
    ) -> EnergySnapshot:
        """Integrate one window of power into the running totals."""
        self._roll_over(sim_time)

        hours = dt_s / 3600.0
        window_wh = max(total_power_w, 0.0) * hours

        # Price this increment at the marginal rate for the month so far.
        month_kwh_before = self.monthly_baseline_kwh + self.energy_wh_month / 1000.0
        window_cost = self.tariff.cost_of(window_wh / 1000.0, month_kwh_before)

        self.energy_wh_session += window_wh
        self.energy_wh_today += window_wh
        self.energy_wh_month += window_wh
        self.cost_inr_session += window_cost
        self.cost_inr_today += window_cost
        self.cost_inr_month += window_cost
        self.elapsed_sim_s += dt_s

        self.peak_power_w_session = max(self.peak_power_w_session, total_power_w)
        self.peak_power_w_today = max(self.peak_power_w_today, total_power_w)

        # Split the window's energy and cost across appliances by power share.
        denominator = max(total_power_w, 1e-9)
        for appliance_id, watts in appliance_power_w.items():
            totals = self._totals_for(appliance_id)
            appliance_wh = max(watts, 0.0) * hours
            share = max(watts, 0.0) / denominator

            totals.energy_wh_session += appliance_wh
            totals.energy_wh_today += appliance_wh
            totals.energy_wh_month += appliance_wh
            totals.cost_inr_session += window_cost * share
            totals.cost_inr_today += window_cost * share
            totals.cost_inr_month += window_cost * share
            totals.last_power_w = watts
            totals.peak_power_w = max(totals.peak_power_w, watts)
            if watts > 1.0:
                totals.runtime_s_today += dt_s
                totals.runtime_s_session += dt_s

        # Anything the disaggregator could not place still costs money.
        unattributed_wh = max(unattributed_w, 0.0) * hours
        self.unattributed.energy_wh_session += unattributed_wh
        self.unattributed.energy_wh_today += unattributed_wh
        self.unattributed.energy_wh_month += unattributed_wh
        unattributed_share = max(unattributed_w, 0.0) / denominator
        self.unattributed.cost_inr_session += window_cost * unattributed_share
        self.unattributed.cost_inr_today += window_cost * unattributed_share
        self.unattributed.cost_inr_month += window_cost * unattributed_share
        self.unattributed.last_power_w = unattributed_w

        return self.snapshot(total_power_w, window_wh)

    # ------------------------------------------------------------------ #

    def snapshot(
        self, instantaneous_power_w: float = 0.0, window_wh: float = 0.0
    ) -> EnergySnapshot:
        """Build the dashboard-facing view of the current totals."""
        average_power = (
            self.energy_wh_session * 3600.0 / self.elapsed_sim_s
            if self.elapsed_sim_s > 0
            else 0.0
        )
        # Load factor is average demand over peak demand, so it is bounded by
        # 1.0 by definition. Clamped because a perfectly flat load accumulates
        # enough floating-point error over thousands of windows to come out at
        # 1.0000000000000022, which then renders as "100.0%" of a gauge that is
        # supposed to top out at 100%.
        load_factor = (
            min(1.0, average_power / self.peak_power_w_session)
            if self.peak_power_w_session > 0
            else 0.0
        )

        month_kwh = self.monthly_baseline_kwh + self.energy_wh_month / 1000.0

        # Project the month from the rate observed so far.  Only meaningful once
        # a reasonable amount of simulated time has elapsed.
        if self.elapsed_sim_s > 60.0:
            daily_wh = self.energy_wh_session * 86400.0 / self.elapsed_sim_s
            projected_kwh = self.monthly_baseline_kwh + daily_wh * 30.0 / 1000.0
        else:
            projected_kwh = month_kwh

        cost = CostBreakdown(
            today_inr=self.cost_inr_today,
            month_inr=self.cost_inr_month,
            session_inr=self.cost_inr_session,
            projected_month_inr=self.tariff.monthly_bill(projected_kwh),
            monthly_bill_inr=self.tariff.monthly_bill(month_kwh),
            marginal_rate_inr=self.tariff.marginal_rate(month_kwh),
            effective_rate_inr=self.tariff.effective_rate(month_kwh),
            per_appliance_inr={
                appliance_id: totals.cost_inr_today
                for appliance_id, totals in self.totals.items()
            },
            slab_breakdown=self.tariff.slab_breakdown(month_kwh),
            tariff_name=self.tariff.name,
            currency_symbol=self.tariff.currency_symbol,
        )

        return EnergySnapshot(
            instantaneous_power_w=instantaneous_power_w,
            energy_wh_window=window_wh,
            energy_wh_session=self.energy_wh_session,
            energy_wh_today=self.energy_wh_today,
            energy_wh_month=self.energy_wh_month,
            peak_power_w_session=self.peak_power_w_session,
            peak_power_w_today=self.peak_power_w_today,
            average_power_w=average_power,
            load_factor=load_factor,
            elapsed_sim_s=self.elapsed_sim_s,
            per_appliance=dict(self.totals),
            cost=cost,
        )
