"""Login, session lifecycle and account administration."""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status

from caelum.api.deps import get_config_manager
from caelum.api.schemas import (
    AuthContextResponse,
    ChangePasswordRequest,
    CreateUserRequest,
    LoginRequest,
    UpdateUserRequest,
)
from caelum.api.security import (
    Principal,
    get_auth_config,
    get_user_store,
    require_admin,
    resolve_principal,
)
from caelum.auth import SESSION_COOKIE, AuthError, UserStore, sessions
from caelum.config.manager import ConfigManager
from caelum.config.schema import AuthConfig

logger = logging.getLogger(__name__)

router = APIRouter()


def _set_session_cookie(response: Response, token: str, ttl: timedelta) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(ttl.total_seconds()),
        httponly=True,
        samesite="lax",
        path="/",
        # Not `secure=True`: the overwhelmingly common deployment is plain
        # HTTP on a LAN address, where a secure-only cookie would simply
        # never be sent and nobody could log in. Put caelum behind a TLS
        # reverse proxy if the network is not trusted — see the docs.
    )


@router.get("/auth/context", response_model=AuthContextResponse)
def auth_context(
    principal: Principal | None = Depends(resolve_principal),
    auth_cfg: AuthConfig = Depends(get_auth_config),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> AuthContextResponse:
    """First call the web UI makes: what does this deployment require of me?"""
    return AuthContextResponse(
        auth_enabled=auth_cfg.enabled,
        preview_access=auth_cfg.preview_access,
        terminal_enabled=auth_cfg.terminal_enabled,
        docs_url=config_manager.current.docs.base_url,
        authenticated=principal is not None,
        username=principal.username if principal else None,
        role=principal.role if principal else None,
    )


@router.post("/auth/login", response_model=AuthContextResponse)
def login(
    body: LoginRequest,
    response: Response,
    store: UserStore = Depends(get_user_store),
    auth_cfg: AuthConfig = Depends(get_auth_config),
    config_manager: ConfigManager = Depends(get_config_manager),
) -> AuthContextResponse:
    user = store.authenticate(body.username, body.password)
    if user is None:
        logger.warning("Failed login attempt for username %r", body.username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    ttl = timedelta(hours=auth_cfg.session_ttl_hours)
    token = sessions.issue(
        store.session_secret,
        username=user.username,
        role=user.role,
        token_version=user.token_version,
        ttl=ttl,
    )
    _set_session_cookie(response, token, ttl)
    return AuthContextResponse(
        auth_enabled=auth_cfg.enabled,
        preview_access=auth_cfg.preview_access,
        terminal_enabled=auth_cfg.terminal_enabled,
        docs_url=config_manager.current.docs.base_url,
        authenticated=True,
        username=user.username,
        role=user.role,
    )


@router.post("/auth/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.post("/auth/password")
def change_own_password(
    body: ChangePasswordRequest,
    response: Response,
    principal: Principal | None = Depends(resolve_principal),
    store: UserStore = Depends(get_user_store),
    auth_cfg: AuthConfig = Depends(get_auth_config),
) -> dict:
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    if store.authenticate(principal.username, body.current_password) is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Current password is incorrect")

    try:
        store.set_password(principal.username, body.new_password)
    except AuthError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # set_password bumps token_version, which just invalidated the cookie the
    # caller is holding. Re-issue one so changing your own password does not
    # log you out of the tab you did it in (it does log out every other one).
    user = store.get(principal.username)
    assert user is not None
    ttl = timedelta(hours=auth_cfg.session_ttl_hours)
    _set_session_cookie(
        response,
        sessions.issue(
            store.session_secret,
            username=user.username,
            role=user.role,
            token_version=user.token_version,
            ttl=ttl,
        ),
        ttl,
    )
    return {"ok": True}


# ---- account administration ---------------------------------------------


@router.get("/auth/users")
def list_users(_: Principal = Depends(require_admin), store: UserStore = Depends(get_user_store)) -> list[dict]:
    return store.list_users()


@router.post("/auth/users", status_code=status.HTTP_201_CREATED)
def create_user(
    body: CreateUserRequest,
    _: Principal = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
) -> dict:
    try:
        return store.create_user(body.username, body.password, body.role).public()
    except AuthError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/auth/users/{username}")
def update_user(
    username: str,
    body: UpdateUserRequest,
    _: Principal = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
) -> dict:
    try:
        if body.password is not None:
            store.set_password(username, body.password)
        if body.role is not None:
            store.set_role(username, body.role)
    except AuthError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    user = store.get(username)
    if user is None:
        raise HTTPException(status_code=404, detail=f"Unknown user {username!r}")
    return user.public()


@router.delete("/auth/users/{username}")
def delete_user(
    username: str,
    principal: Principal = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
) -> dict:
    if username == principal.username:
        raise HTTPException(status_code=422, detail="Refusing to delete the account you are signed in as")
    try:
        store.delete_user(username)
    except AuthError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True}
