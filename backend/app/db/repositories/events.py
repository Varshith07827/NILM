"""Repositories for appliance events and notifications."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import ApplianceEvent, Notification


class EventRepository:
    """Data access for the appliance switching timeline."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def bulk_insert(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        self.session.bulk_insert_mappings(ApplianceEvent, rows)
        return len(rows)

    def recent(self, run_id: str, limit: int = 100) -> list[ApplianceEvent]:
        statement = (
            select(ApplianceEvent)
            .where(ApplianceEvent.run_id == run_id)
            .order_by(ApplianceEvent.id.desc())
            .limit(limit)
        )
        return list(self.session.execute(statement).scalars())

    def between(
        self, run_id: str, start: datetime, end: datetime
    ) -> list[ApplianceEvent]:
        statement = (
            select(ApplianceEvent)
            .where(
                ApplianceEvent.run_id == run_id,
                ApplianceEvent.sim_time >= start,
                ApplianceEvent.sim_time < end,
            )
            .order_by(ApplianceEvent.sim_time.asc())
        )
        return list(self.session.execute(statement).scalars())

    def delete_run(self, run_id: str) -> int:
        return int(
            self.session.query(ApplianceEvent)
            .filter(ApplianceEvent.run_id == run_id)
            .delete()
        )


class NotificationRepository:
    """Data access for the alert panel."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def bulk_insert(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        self.session.bulk_insert_mappings(Notification, rows)
        return len(rows)

    def recent(self, run_id: str, limit: int = 50) -> list[Notification]:
        statement = (
            select(Notification)
            .where(Notification.run_id == run_id)
            .order_by(Notification.id.desc())
            .limit(limit)
        )
        return list(self.session.execute(statement).scalars())

    def delete_run(self, run_id: str) -> int:
        return int(
            self.session.query(Notification)
            .filter(Notification.run_id == run_id)
            .delete()
        )
