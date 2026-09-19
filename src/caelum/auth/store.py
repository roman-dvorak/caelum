"""Account storage — `<config_dir>/auth.json`, deliberately outside AppConfig.

Keeping accounts out of the Redis-synced `AppConfig` is not incidental:
`/api/config` returns the whole config document and the web UI renders it as
an editable JSON tree, so password hashes and the session signing key would
be handed to anyone who opens the Settings page. They live here instead, in
a 0600 file that is only ever reachable through the `/api/auth/*` routes.

The file is small and written rarely (account changes only), so it is held
in memory and rewritten wholesale under a lock — no partial-update logic.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .passwords import hash_password, needs_rehash, verify_password

logger = logging.getLogger(__name__)

Role = Literal["admin", "viewer"]
ROLES: tuple[Role, ...] = ("admin", "viewer")

BOOTSTRAP_USERNAME = "admin"
BOOTSTRAP_PASSWORD_FILE = "initial-admin-password.txt"


class AuthError(Exception):
    """Rejected account operation — the message is safe to show a user."""


@dataclass
class UserRecord:
    username: str
    role: Role
    password_hash: str
    token_version: int = 1
    created_at: str = ""
    last_login_at: str | None = None

    def to_json(self) -> dict:
        return {
            "role": self.role,
            "password_hash": self.password_hash,
            "token_version": self.token_version,
            "created_at": self.created_at,
            "last_login_at": self.last_login_at,
        }

    def public(self) -> dict:
        """Everything about this account *except* the credential material."""
        return {
            "username": self.username,
            "role": self.role,
            "created_at": self.created_at,
            "last_login_at": self.last_login_at,
        }


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class UserStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._users: dict[str, UserRecord] = {}
        self._session_secret: bytes = b""
        #: Set by `load()` when it had to create the first admin account.
        self.bootstrap_password: str | None = None

    # ---- persistence ----------------------------------------------------

    def load(self) -> None:
        """Read auth.json, creating a bootstrap admin if there isn't one.

        The trigger is "no admin account", not "no file": a store with only
        viewer accounts left in it cannot be administered through the web UI
        at all, so it would be unrecoverable without this. It is also the
        documented way to reset a forgotten admin password without losing
        the other accounts — delete the admin entry and restart.
        """
        with self._lock:
            if self._path.exists():
                self._read()
                if self._admin_count_locked() > 0:
                    return
                logger.warning("%s has no admin account — creating a bootstrap admin", self._path)
            else:
                self._session_secret = secrets.token_bytes(32)
            self._bootstrap()

    def _read(self) -> None:
        raw = json.loads(self._path.read_text())
        self._session_secret = bytes.fromhex(raw["session_secret"])
        self._users = {
            username: UserRecord(username=username, **fields) for username, fields in raw.get("users", {}).items()
        }

    def _write_locked(self) -> None:
        document = {
            "version": 1,
            "session_secret": self._session_secret.hex(),
            "users": {username: user.to_json() for username, user in self._users.items()},
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        # Create 0600 up front: writing then chmod'ing would leave the hashes
        # world-readable for the moment in between.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(document, handle, indent=2)
        os.replace(tmp, self._path)

    def _bootstrap(self) -> None:
        password = secrets.token_urlsafe(18)
        # Added to whatever is already there rather than replacing it, so
        # recovering a lost admin does not take the viewer accounts with it.
        self._users[BOOTSTRAP_USERNAME] = UserRecord(
            username=BOOTSTRAP_USERNAME,
            role="admin",
            password_hash=hash_password(password),
            created_at=_now(),
        )
        self._write_locked()
        self.bootstrap_password = password

        password_file = self._path.parent / BOOTSTRAP_PASSWORD_FILE
        fd = os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(f"{password}\n")
        logger.warning(
            "No accounts found — created admin account %r. Password written to %s (delete it once you have logged in).",
            BOOTSTRAP_USERNAME,
            password_file,
        )

    # ---- reads ----------------------------------------------------------

    @property
    def session_secret(self) -> bytes:
        return self._session_secret

    def get(self, username: str) -> UserRecord | None:
        with self._lock:
            return self._users.get(username)

    def list_users(self) -> list[dict]:
        with self._lock:
            return [user.public() for user in sorted(self._users.values(), key=lambda u: u.username)]

    # ---- writes ---------------------------------------------------------

    def authenticate(self, username: str, password: str) -> UserRecord | None:
        """Verify credentials; None on any failure (unknown user included).

        Unknown usernames still pay the cost of a hash verification so that
        response timing does not reveal which accounts exist.
        """
        with self._lock:
            user = self._users.get(username)
            reference = user.password_hash if user else _DUMMY_HASH
            ok = verify_password(password, reference)
            if not ok or user is None:
                return None

            user.last_login_at = _now()
            if needs_rehash(user.password_hash):
                user.password_hash = hash_password(password)
            self._write_locked()
            return user

    def create_user(self, username: str, password: str, role: Role) -> UserRecord:
        _validate_username(username)
        _validate_password(password)
        if role not in ROLES:
            raise AuthError(f"Unknown role {role!r}")
        with self._lock:
            if username in self._users:
                raise AuthError(f"User {username!r} already exists")
            user = UserRecord(
                username=username, role=role, password_hash=hash_password(password), created_at=_now()
            )
            self._users[username] = user
            self._write_locked()
            return user

    def set_password(self, username: str, password: str) -> None:
        """Change a password and invalidate that user's existing sessions."""
        _validate_password(password)
        with self._lock:
            user = self._users.get(username)
            if user is None:
                raise AuthError(f"Unknown user {username!r}")
            user.password_hash = hash_password(password)
            user.token_version += 1
            self._write_locked()

    def set_role(self, username: str, role: Role) -> None:
        if role not in ROLES:
            raise AuthError(f"Unknown role {role!r}")
        with self._lock:
            user = self._users.get(username)
            if user is None:
                raise AuthError(f"Unknown user {username!r}")
            if user.role == "admin" and role != "admin" and self._admin_count_locked() == 1:
                raise AuthError("Refusing to demote the last admin account")
            user.role = role
            user.token_version += 1
            self._write_locked()

    def delete_user(self, username: str) -> None:
        with self._lock:
            user = self._users.get(username)
            if user is None:
                raise AuthError(f"Unknown user {username!r}")
            if user.role == "admin" and self._admin_count_locked() == 1:
                raise AuthError("Refusing to delete the last admin account")
            del self._users[username]
            self._write_locked()

    def _admin_count_locked(self) -> int:
        return sum(1 for user in self._users.values() if user.role == "admin")


def _validate_username(username: str) -> None:
    if not 1 <= len(username) <= 32 or not all(c.isalnum() or c in "-_." for c in username):
        raise AuthError("Username must be 1-32 characters of letters, digits, '-', '_' or '.'")


def _validate_password(password: str) -> None:
    if len(password) < 8:
        raise AuthError("Password must be at least 8 characters")


# Verified against when the username is unknown, purely to equalise timing.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
