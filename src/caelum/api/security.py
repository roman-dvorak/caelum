"""Request authentication and the two access levels the API exposes.

Two levels, not a permission matrix — the deployment this serves is one
operator plus, optionally, people they want to show the sky to:

* **admin** — everything: config, camera control, plugins, deletes, terminal.
* **preview** — the read-only live view (status, sky state, latest frame,
  the stream, browsing stored output). Who this is open to is policy, set by
  `auth.preview_access`: ``public`` (no login at all), ``viewer`` (any
  account) or ``admin`` (hidden from viewer accounts).

Setting `auth.enabled = false` turns the whole thing off and treats every
caller as an admin — the escape hatch for a trusted LAN or for recovering
from a lost password, not the default.

WebSocket routes cannot raise `HTTPException` usefully (the handshake has
already completed by the time a dependency runs), so they call
`authorize_websocket()` explicitly and close with a policy-violation code.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from starlette.requests import HTTPConnection
from starlette.websockets import WebSocket

from caelum.auth import SESSION_COOKIE, UserStore, sessions
from caelum.config.schema import AuthConfig

from .deps import get_config_manager


@dataclass(frozen=True)
class Principal:
    username: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


#: Stand-in identity used when `auth.enabled` is false, so downstream code
#: never has to special-case "no authentication configured".
ANONYMOUS_ADMIN = Principal(username="anonymous", role="admin")


def get_user_store(conn: HTTPConnection) -> UserStore:
    return conn.app.state.user_store


def get_auth_config(conn: HTTPConnection) -> AuthConfig:
    return get_config_manager(conn).current.auth


def _bearer_token(conn: HTTPConnection) -> str | None:
    header = conn.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def resolve_principal(conn: HTTPConnection) -> Principal | None:
    """Identify the caller, or None when the request carries no valid session.

    Accepts the session cookie (what the browser sends) or a
    `Authorization: Bearer <token>` header (what curl/scripts send). A token
    whose `token_version` no longer matches the account is rejected, which
    is how a password change logs out every other device.
    """
    auth_cfg = get_auth_config(conn)
    if not auth_cfg.enabled:
        return ANONYMOUS_ADMIN

    raw = conn.cookies.get(SESSION_COOKIE) or _bearer_token(conn)
    if not raw:
        return None

    store = get_user_store(conn)
    claims = sessions.verify(store.session_secret, raw)
    if claims is None:
        return None

    user = store.get(claims.username)
    if user is None or user.token_version != claims.token_version:
        return None
    # The role is re-read from the store rather than trusted from the token,
    # so a demotion takes effect immediately.
    return Principal(username=user.username, role=user.role)


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


def _forbidden() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")


def require_admin(principal: Principal | None = Depends(resolve_principal)) -> Principal:
    if principal is None:
        raise _unauthorized()
    if not principal.is_admin:
        raise _forbidden()
    return principal


def require_preview(
    principal: Principal | None = Depends(resolve_principal),
    auth_cfg: AuthConfig = Depends(get_auth_config),
) -> Principal:
    if auth_cfg.preview_access == "public":
        return principal or Principal(username="public", role="viewer")
    if principal is None:
        raise _unauthorized()
    if auth_cfg.preview_access == "admin" and not principal.is_admin:
        raise _forbidden()
    return principal


# ---- websocket equivalents ----------------------------------------------

WS_POLICY_VIOLATION = 1008


async def authorize_websocket(websocket: WebSocket, *, admin: bool) -> Principal | None:
    """Authorize a websocket before `accept()`; closes and returns None on failure.

    Callers must return immediately when this returns None — the socket is
    already closed at that point.
    """
    auth_cfg = get_auth_config(websocket)
    principal = resolve_principal(websocket)

    if admin:
        allowed = principal is not None and principal.is_admin
    elif auth_cfg.preview_access == "public":
        allowed = True
        principal = principal or Principal(username="public", role="viewer")
    elif principal is None:
        allowed = False
    else:
        allowed = auth_cfg.preview_access != "admin" or principal.is_admin

    if not allowed:
        await websocket.close(code=WS_POLICY_VIOLATION, reason="Authentication required")
        return None
    return principal
