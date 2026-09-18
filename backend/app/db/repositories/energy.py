"""Repository for hourly per-appliance energy buckets."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from backend.app.db.models import EnergyBucket

TOTAL_KEY = "__total__"
UNATTRIBUTED_KEY = "__unattributed__"


class EnergyRepository:
    """Data access for :class:`~backend.app.db.models.EnergyBucket`."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def accumulate(self, rows: list[dict]) -> None:
        """Add energy into hourly buckets, creating them as needed.

        Uses SQLite's ``ON CONFLICT DO UPDATE`` so the whole batch is one
        statement and concurrent flushes cannot lose an increment.
        """
        if not rows:
            return
        statement = sqlite_insert(EnergyBucket).values(rows)
        statement = statement.on_conflict_do_update(
            index_elements=["run_id", "bucket_start", "appliance_id"],
            set_={
                "energy_wh": EnergyBucket.energy_wh + statement.excluded.energy_wh,
                "cost_inr": EnergyBucket.cost_inr + statement.excluded.cost_inr,
                "runtime_s": EnergyBucket.runtime_s + statement.excluded.runtime_s,
                "peak_power_w": func.max(
                    EnergyBucket.peak_power_w, statement.excluded.peak_power_w
                ),
            },
        )
        self.session.execute(statement)

    def totals_by_appliance(
        self,
        run_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[dict]:
        """Aggregate energy, cost and runtime per appliance over a period."""
        conditions = [EnergyBucket.run_id == run_id]
        if start is not None:
            conditions.append(EnergyBucket.bucket_start >= start)
        if end is not None:
            conditions.append(EnergyBucket.bucket_start < end)

        statement = (
            select(
                EnergyBucket.appliance_id,
                func.sum(EnergyBucket.energy_wh).label("energy_wh"),
                func.sum(EnergyBucket.cost_inr).label("cost_inr"),
                func.sum(EnergyBucket.runtime_s).label("runtime_s"),
                func.max(EnergyBucket.peak_power_w).label("peak_power_w"),
            )
            .where(*conditions)
            .group_by(EnergyBucket.appliance_id)
            .order_by(func.sum(EnergyBucket.energy_wh).desc())
        )
        return [
            {
                "appliance_id": row.appliance_id,
                "energy_wh": float(row.energy_wh or 0.0),
                "cost_inr": float(row.cost_inr or 0.0),
                "runtime_s": float(row.runtime_s or 0.0),
                "peak_power_w": float(row.peak_power_w or 0.0),
            }
            for row in self.session.execute(statement)
        ]

    def hourly_series(
        self,
        run_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
        appliance_id: str | None = None,
    ) -> list[dict]:
        """Energy per hour, optionally filtered to a single appliance."""
        conditions = [EnergyBucket.run_id == run_id]
        if start is not None:
            conditions.append(EnergyBucket.bucket_start >= start)
        if end is not None:
            conditions.append(EnergyBucket.bucket_start < end)
        if appliance_id is not None:
            conditions.append(EnergyBucket.appliance_id == appliance_id)
        else:
            conditions.append(EnergyBucket.appliance_id == TOTAL_KEY)

        statement = (
            select(
                EnergyBucket.bucket_start,
                func.sum(EnergyBucket.energy_wh).label("energy_wh"),
                func.sum(EnergyBucket.cost_inr).label("cost_inr"),
            )
            .where(*conditions)
            .group_by(EnergyBucket.bucket_start)
            .order_by(EnergyBucket.bucket_start.asc())
        )
        return [
            {
                "bucket_start": row.bucket_start,
                "energy_wh": float(row.energy_wh or 0.0),
                "cost_inr": float(row.cost_inr or 0.0),
            }
            for row in self.session.execute(statement)
        ]

    def daily_series(
        self,
        run_id: str,
        appliance_id: str = TOTAL_KEY,
    ) -> list[dict]:
        """Energy per simulated day."""
        day = func.date(EnergyBucket.bucket_start)
        statement = (
            select(
                day.label("day"),
                func.sum(EnergyBucket.energy_wh).label("energy_wh"),
                func.sum(EnergyBucket.cost_inr).label("cost_inr"),
            )
            .where(
                EnergyBucket.run_id == run_id,
                EnergyBucket.appliance_id == appliance_id,
            )
            .group_by(day)
            .order_by(day.asc())
        )
        return [
            {
                "day": row.day,
                "energy_wh": float(row.energy_wh or 0.0),
                "cost_inr": float(row.cost_inr or 0.0),
            }
            for row in self.session.execute(statement)
        ]

    def total_energy_wh(self, run_id: str) -> float:
        value = self.session.execute(
            select(func.sum(EnergyBucket.energy_wh)).where(
                EnergyBucket.run_id == run_id,
                EnergyBucket.appliance_id == TOTAL_KEY,
            )
        ).scalar()
        return float(value or 0.0)

    def delete_run(self, run_id: str) -> int:
        return int(
            self.session.query(EnergyBucket)
            .filter(EnergyBucket.run_id == run_id)
            .delete()
        )
