"""Repository for the per-second time series."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db.models import Reading


class ReadingRepository:
    """Data access for :class:`~backend.app.db.models.Reading`."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def bulk_insert(self, rows: list[dict]) -> int:
        """Insert a batch of readings in one statement."""
        if not rows:
            return 0
        self.session.bulk_insert_mappings(Reading, rows)
        return len(rows)

    def latest(self, run_id: str) -> Reading | None:
        statement = (
            select(Reading)
            .where(Reading.run_id == run_id)
            .order_by(Reading.id.desc())
            .limit(1)
        )
        return self.session.execute(statement).scalar_one_or_none()

    def recent(self, run_id: str, limit: int = 300) -> list[Reading]:
        statement = (
            select(Reading)
            .where(Reading.run_id == run_id)
            .order_by(Reading.id.desc())
            .limit(limit)
        )
        rows = list(self.session.execute(statement).scalars())
        rows.reverse()
        return rows

    def between(
        self,
        run_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
        max_points: int = 2000,
    ) -> list[Reading]:
        """Fetch a time range, decimated to at most ``max_points`` rows.

        Decimation happens in SQL with a modulo on the row id rather than by
        fetching everything and thinning it in Python, so asking for a month of
        history does not pull a million rows across the process boundary.
        """
        conditions = [Reading.run_id == run_id]
        if start is not None:
            conditions.append(Reading.sim_time >= start)
        if end is not None:
            conditions.append(Reading.sim_time <= end)

        count = self.session.execute(
            select(func.count()).select_from(Reading).where(*conditions)
        ).scalar_one()
        if count == 0:
            return []

        stride = max(1, count // max_points)
        statement = select(Reading).where(*conditions)
        if stride > 1:
            statement = statement.where(Reading.id % stride == 0)
        statement = statement.order_by(Reading.sim_time.asc()).limit(max_points)
        return list(self.session.execute(statement).scalars())

    def count(self, run_id: str) -> int:
        return int(
            self.session.execute(
                select(func.count()).select_from(Reading).where(Reading.run_id == run_id)
            ).scalar_one()
        )

    def delete_run(self, run_id: str) -> int:
        rows = self.session.query(Reading).filter(Reading.run_id == run_id).delete()
        return int(rows)
