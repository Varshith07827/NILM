"""Historical time-series endpoint."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query

from backend.app.api.deps import PipelineDep, SessionDep
from backend.app.db.repositories.readings import ReadingRepository
from backend.app.schemas.api import HistoryPoint, HistoryResponse

router = APIRouter(tags=["history"])


@router.get("/history", response_model=HistoryResponse)
def get_history(
    session: SessionDep,
    pipeline: PipelineDep,
    start: datetime | None = Query(default=None, description="Simulated start time"),
    end: datetime | None = Query(default=None, description="Simulated end time"),
    max_points: int = Query(default=1500, ge=10, le=10_000),
    run_id: str | None = Query(default=None),
) -> HistoryResponse:
    """Persisted readings for a simulated time range.

    Results are decimated in SQL to at most ``max_points`` rows, so asking for
    a month of history returns a chart-sized response instead of millions of
    rows.
    """
    target_run = run_id or pipeline.run_id
    repository = ReadingRepository(session)
    total = repository.count(target_run)
    rows = repository.between(target_run, start, end, max_points)

    return HistoryResponse(
        run_id=target_run,
        total_rows=total,
        decimated=total > len(rows),
        points=[
            HistoryPoint(
                sim_time=row.sim_time,
                current_a=row.current_a,
                voltage_v=row.voltage_v,
                power_w=row.power_w,
                power_factor=row.power_factor,
                thd=row.thd,
                energy_wh=row.cumulative_energy_wh,
                cost_inr=row.cost_inr,
                detected=row.detected or [],
            )
            for row in rows
        ],
    )
