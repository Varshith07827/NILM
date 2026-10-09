"""Admin authentication.

Deliberately dependency-free: passwords are hashed with PBKDF2-SHA256 from the
standard library, and sessions are stateless tokens signed with HMAC-SHA256.
There is one kind of account -- admin -- and the only thing it unlocks is
changing the house: rooms, devices, ratings, the tariff and alert thresholds.
Watching the dashboard needs no login.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from backend.app.core.config import Settings

PBKDF2_ITERATIONS: int = 390_000
_ALGORITHM = "pbkdf2_sha256"

#: File, beside the database, holding a generated signing key when none is
#: configured.
SECRET_KEY_FILE_NAME = ".secret_key"


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
    return f"{_ALGORITHM}${iterations}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored.split("$")
    except ValueError:
        return False
    if algorithm != _ALGORITHM:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), int(iterations)
    )
    return hmac.compare_digest(digest.hex(), expected)


# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def signing_key(settings: Settings) -> bytes:
    """The configured key, or a generated one persisted beside the database."""
    if settings.secret_key is not None:
        return settings.secret_key.get_secret_value().encode()
    path = settings.database_path.parent / SECRET_KEY_FILE_NAME
    if path.exists():
        return path.read_text(encoding="utf-8").strip().encode()
    key = secrets.token_hex(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key, encoding="utf-8")
    return key.encode()


@dataclass(frozen=True)
class TokenClaims:
    username: str
    expires_at: float


def create_token(username: str, settings: Settings, now: float | None = None) -> str:
    issued = time.time() if now is None else now
    payload = {
        "sub": username,
        "exp": issued + settings.token_ttl_hours * 3600.0,
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(signing_key(settings), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(signature)}"


def verify_token(
    token: str, settings: Settings, now: float | None = None
) -> TokenClaims | None:
    """The token's claims if the signature is valid and it has not expired."""
    try:
        body, signature = token.split(".")
        expected = hmac.new(
            signing_key(settings), body.encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_unb64(signature), expected):
            return None
        payload = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    claims = TokenClaims(username=str(payload.get("sub", "")), expires_at=float(payload.get("exp", 0)))
    if not claims.username or claims.expires_at < (time.time() if now is None else now):
        return None
    return claims


# --------------------------------------------------------------------------- #
# Login throttling
# --------------------------------------------------------------------------- #


class LoginThrottle:
    """Slows down password guessing: N failures per client per window."""

    def __init__(self, max_failures: int = 5, window_s: float = 300.0) -> None:
        self.max_failures = max_failures
        self.window_s = window_s
        self._failures: dict[str, list[float]] = {}

    def _recent(self, client: str, now: float) -> list[float]:
        recent = [t for t in self._failures.get(client, []) if now - t < self.window_s]
        self._failures[client] = recent
        return recent

    def blocked(self, client: str, now: float | None = None) -> bool:
        return len(self._recent(client, time.time() if now is None else now)) >= self.max_failures

    def record_failure(self, client: str, now: float | None = None) -> None:
        stamp = time.time() if now is None else now
        self._recent(client, stamp).append(stamp)

    def reset(self, client: str) -> None:
        self._failures.pop(client, None)
