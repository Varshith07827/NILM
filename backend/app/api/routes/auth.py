"""Admin login."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from backend.app.api.deps import AdminDep, SessionDep, SettingsDep
from backend.app.core.security import LoginThrottle, create_token, verify_token
from backend.app.schemas.api import LoginRequest, LoginResponse
from backend.app.services.accounts import admin_exists, authenticate

router = APIRouter(prefix="/auth", tags=["auth"])

_throttle = LoginThrottle()


@router.get("/status", summary="Whether an admin account has been set up")
def auth_status(session: SessionDep) -> dict:
    return {
        "admin_configured": admin_exists(session),
        "setup_command": "python -m backend.manage set-admin-password",
    }


@router.post("/login", response_model=LoginResponse)
def login(
    body: LoginRequest, request: Request, session: SessionDep, settings: SettingsDep
) -> LoginResponse:
    """Exchange the admin username and password for a session token.

    A plain ``def`` route: PBKDF2 is deliberately slow, and FastAPI runs sync
    routes in a worker thread, so a login never stalls the simulation loop.
    """
    client = request.client.host if request.client else "unknown"
    if _throttle.blocked(client):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many failed logins; try again in a few minutes",
        )
    if not authenticate(session, body.username, body.password):
        _throttle.record_failure(client)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="wrong username or password",
        )
    _throttle.reset(client)
    token = create_token(body.username.strip(), settings)
    claims = verify_token(token, settings)
    assert claims is not None
    return LoginResponse(
        token=token, username=claims.username, expires_at=claims.expires_at
    )


@router.get("/me", summary="The logged-in admin")
def me(admin: AdminDep) -> dict:
    return {"username": admin.username, "expires_at": admin.expires_at}
