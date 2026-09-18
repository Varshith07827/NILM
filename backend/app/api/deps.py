"""FastAPI dependencies (Module 16: dependency injection).

The pipeline is a single long-lived object created during application startup
and stored on ``app.state``.  Routes receive it through
:func:`get_pipeline` rather than importing a module-level global, which keeps
them testable: a test can build an app with a stub pipeline and the routes are
none the wiser.
"""

from __future__ import annotations

from typing import Annotated, Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.db.session import SessionFactory
from backend.app.services.pipeline import NILMPipeline


def get_pipeline(request: Request) -> NILMPipeline:
    """The application-wide simulation pipeline."""
    pipeline: NILMPipeline | None = getattr(request.app.state, "pipeline", None)
    if pipeline is None:  # pragma: no cover - only during a failed startup
        raise RuntimeError("pipeline is not initialised")
    return pipeline


def get_db() -> Iterator[Session]:
    """A request-scoped database session."""
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()


PipelineDep = Annotated[NILMPipeline, Depends(get_pipeline)]
SessionDep = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
