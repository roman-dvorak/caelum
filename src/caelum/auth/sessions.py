"""Stateless, HMAC-signed session tokens.

Sessions are not stored anywhere: the token carries its own claims and a
signature over them. That keeps login working across a caelum restart and
across a Redis flush without a session table, which matters on a device
whose Redis is often configured without persistence.

Revocation is handled by `token_version`: it is embedded in the token and
compared against the user record on every request, so bumping a user's
`token_version` (which `change_password` does) invalidates every token
previously issued to them.
"""

from __future__ import annotations

import base64
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

SESSION_COOKIE = "caelum_session"


@dataclass(frozen=True)
class SessionClaims:
    username: str
    role: str
    token_version: int
    expires_at: datetime


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: bytes, payload: bytes) -> bytes:
    return hmac.new(secret, payload, sha256).digest()


def issue(secret: bytes, *, username: str, role: str, token_version: int, ttl: timedelta) -> str:
    expires_at = datetime.now(UTC) + ttl
    payload = json.dumps(
        {"u": username, "r": role, "v": token_version, "exp": int(expires_at.timestamp())},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"{_b64(payload)}.{_b64(_sign(secret, payload))}"


def verify(secret: bytes, token: str) -> SessionClaims | None:
    """Decode and validate a token; None for anything untrusted or expired."""
    try:
        payload_s, signature_s = token.split(".", 1)
        payload = _unb64(payload_s)
        if not hmac.compare_digest(_sign(secret, payload), _unb64(signature_s)):
            return None
        claims = json.loads(payload)
        expires_at = datetime.fromtimestamp(int(claims["exp"]), tz=UTC)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None

    if expires_at <= datetime.now(UTC):
        return None
    return SessionClaims(
        username=str(claims["u"]),
        role=str(claims["r"]),
        token_version=int(claims["v"]),
        expires_at=expires_at,
    )
