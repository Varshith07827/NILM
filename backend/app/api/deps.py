"""FastAPI dependencies (Module 16: dependency injection).

The pipeline is a single long-lived object created during application startup
and stored on ``app.state``.  Routes receive it through
:func:`get_pipeline` rather than importing a module-level global, which keeps
them testable: a test can build an app with a stub pipeline and the routes are
none the wiser.
"""

from __future__ import annotations

from typing import Annotated, Iterator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.core.security import TokenClaims, verify_token
from backend.app.db.session import SessionFactory
from backend.app.services.pipeline import NILMPipeline

_bearer = HTTPBearer(auto_error=False)


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


def require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenClaims:
    """Reject the request unless it carries a valid admin token."""
    claims = (
        verify_token(credentials.credentials, settings) if credentials else None
    )
    if claims is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="admin login required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return claims


PipelineDep = Annotated[NILMPipeline, Depends(get_pipeline)]
SessionDep = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
AdminDep = Annotated[TokenClaims, Depends(require_admin)]
