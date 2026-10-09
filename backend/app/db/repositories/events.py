"""Repositories for appliance events and notifications."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update
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

    def page(
        self, limit: int = 50, offset: int = 0, unread_only: bool = False
    ) -> list[Notification]:
        """Across every run, newest first: the notification centre keeps them."""
        statement = select(Notification).order_by(Notification.id.desc())
        if unread_only:
            statement = statement.where(Notification.read.is_(False))
        return list(
            self.session.execute(statement.limit(limit).offset(offset)).scalars()
        )

    def count(self, unread_only: bool = False) -> int:
        statement = select(func.count()).select_from(Notification)
        if unread_only:
            statement = statement.where(Notification.read.is_(False))
        return int(self.session.execute(statement).scalar_one())

    def mark_read(self, ids: list[int] | None = None) -> int:
        """Mark the given notifications read, or all of them when ``ids`` is None."""
        statement = update(Notification).where(Notification.read.is_(False))
        if ids is not None:
            statement = statement.where(Notification.id.in_(ids))
        return int(self.session.execute(statement.values(read=True)).rowcount or 0)

    def delete_run(self, run_id: str) -> int:
        return int(
            self.session.query(Notification)
            .filter(Notification.run_id == run_id)
            .delete()
        )
