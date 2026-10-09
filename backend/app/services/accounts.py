"""Admin accounts."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.core.security import hash_password, verify_password
from backend.app.db.models import AdminUser

MIN_PASSWORD_LENGTH: int = 8

#: Compared against when the username does not exist, so a wrong username
#: takes as long to reject as a wrong password.
_DUMMY_HASH = hash_password("not-a-real-password")


class AccountError(ValueError):
    pass


def admin_exists(session: Session) -> bool:
    return bool(session.execute(select(func.count()).select_from(AdminUser)).scalar_one())


def set_admin_password(session: Session, username: str, password: str) -> None:
    """Create the account, or change its password if it exists."""
    username = username.strip()
    if not username:
        raise AccountError("username cannot be empty")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AccountError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    user = session.get(AdminUser, username)
    if user is None:
        session.add(
            AdminUser(
                username=username,
                password_hash=hash_password(password),
                created_at=datetime.now(),
            )
        )
    else:
        user.password_hash = hash_password(password)
    session.flush()


def authenticate(session: Session, username: str, password: str) -> bool:
    user = session.get(AdminUser, username.strip())
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return False
    return verify_password(password, user.password_hash)


def bootstrap_admin(session: Session, settings: Settings) -> bool:
    """Create the admin from ``NILM_ADMIN_PASSWORD`` if no account exists yet."""
    if settings.admin_password is None or admin_exists(session):
        return False
    set_admin_password(
        session, settings.admin_username, settings.admin_password.get_secret_value()
    )
    return True
