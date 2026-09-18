"""WebSocket endpoint for real-time updates (Module 9).

Protocol
--------
On connect the server immediately sends a ``status`` frame and a ``snapshot``
frame containing the in-memory ring buffer, so a client that joins mid-run has
populated charts before the next tick arrives.  After that it streams ``frame``
messages, one per processed window, plus ``status`` messages whenever a control
changes.

Clients may send ``{"type": "ping"}`` to keep the connection warm, or
``{"type": "resync"}`` to request a fresh snapshot.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.app.services.pipeline import NILMPipeline

logger = logging.getLogger(__name__)

router = APIRouter()


def _snapshot_message(pipeline: NILMPipeline, limit: int = 300) -> dict:
    frames = list(pipeline.buffer)[-limit:]
    return {
        "type": "snapshot",
        "data": {
            "frames": frames,
            "alerts": list(pipeline.recent_alerts)[:50],
            "events": list(pipeline.recent_events)[:100],
        },
    }


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    pipeline: NILMPipeline = websocket.app.state.pipeline
    queue = pipeline.subscribe()

    async def pump() -> None:
        """Forward broadcast frames to this client."""
        while True:
            message = await queue.get()
            await websocket.send_json(message)

    pump_task = asyncio.create_task(pump())

    try:
        await websocket.send_json({"type": "status", "data": pipeline.status()})
        await websocket.send_json(_snapshot_message(pipeline))

        while True:
            # Reading is what detects a disconnect; the client is not required
            # to say anything meaningful.
            message = await websocket.receive_json()
            kind = message.get("type") if isinstance(message, dict) else None

            if kind == "ping":
                await websocket.send_json({"type": "pong"})
            elif kind == "resync":
                await websocket.send_json({"type": "status", "data": pipeline.status()})
                await websocket.send_json(_snapshot_message(pipeline))
    except WebSocketDisconnect:
        pass
    except Exception:  # pragma: no cover - transport level noise
        logger.debug("websocket closed unexpectedly", exc_info=True)
    finally:
        pump_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump_task
        pipeline.unsubscribe(queue)
