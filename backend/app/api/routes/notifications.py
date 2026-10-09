"""The notification centre: persisted alerts with read / unread state."""

from __future__ import annotations

from fastapi import APIRouter, Query

from backend.app.api.deps import PipelineDep, SessionDep
from backend.app.db.repositories.events import NotificationRepository
from backend.app.schemas.api import MessageResponse, NotificationReadRequest

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", summary="Notifications, newest first")
async def list_notifications(
    pipeline: PipelineDep,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    unread_only: bool = Query(default=False),
) -> dict:
    await pipeline.flush()
    repository = NotificationRepository(session)
    rows = repository.page(limit=limit, offset=offset, unread_only=unread_only)
    return {
        "items": [
            {
                "id": row.id,
                "sim_time": row.sim_time.isoformat(),
                "recorded_at": row.recorded_at.isoformat(),
                "level": row.level,
                "category": row.category,
                "title": row.title,
                "message": row.message,
                "value": row.value,
                "read": row.read,
            }
            for row in rows
        ],
        "total": repository.count(),
        "unread": repository.count(unread_only=True),
    }


@router.post("/read", response_model=MessageResponse)
def mark_read(body: NotificationReadRequest, session: SessionDep) -> MessageResponse:
    changed = NotificationRepository(session).mark_read(body.ids)
    session.commit()
    return MessageResponse(message=f"{changed} notification(s) marked read")
