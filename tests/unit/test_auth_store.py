from __future__ import annotations

import json
import stat
from datetime import timedelta

import pytest

from caelum.auth import AuthError, UserStore, sessions
from caelum.auth.passwords import hash_password, needs_rehash, verify_password
from caelum.auth.store import BOOTSTRAP_PASSWORD_FILE


def test_password_roundtrip_and_rejection():
    encoded = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong password", encoded)
    assert not needs_rehash(encoded)


def test_verify_password_rejects_malformed_hash():
    # A corrupted auth.json must lock people out, never let them through.
    for broken in ("", "nonsense", "argon2$1$2$3$4$5", "scrypt$notanumber$8$1$aa$bb"):
        assert not verify_password("anything", broken)


def test_bootstrap_creates_admin_and_password_file(tmp_path):
    store = UserStore(tmp_path / "auth.json")
    store.load()

    assert store.bootstrap_password is not None
    admin = store.get("admin")
    assert admin is not None and admin.role == "admin"
    assert verify_password(store.bootstrap_password, admin.password_hash)

    password_file = tmp_path / BOOTSTRAP_PASSWORD_FILE
    assert password_file.read_text().strip() == store.bootstrap_password
    assert stat.S_IMODE(password_file.stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "auth.json").stat().st_mode) == 0o600


def test_reload_preserves_accounts_and_secret(tmp_path):
    first = UserStore(tmp_path / "auth.json")
    first.load()
    first.create_user("observer", "viewer-password", "viewer")

    second = UserStore(tmp_path / "auth.json")
    second.load()

    assert second.bootstrap_password is None  # did not re-bootstrap
    assert second.session_secret == first.session_secret
    assert {u["username"] for u in second.list_users()} == {"admin", "observer"}


def test_password_hashes_never_reach_the_public_view(tmp_path):
    store = UserStore(tmp_path / "auth.json")
    store.load()
    assert all("password_hash" not in user for user in store.list_users())


def test_authenticate_rejects_unknown_user_and_wrong_password(tmp_path):
    store = UserStore(tmp_path / "auth.json")
    store.load()
    store.set_password("admin", "the-real-password")

    assert store.authenticate("admin", "the-real-password") is not None
    assert store.authenticate("admin", "nope") is None
    assert store.authenticate("ghost", "the-real-password") is None


def test_password_change_bumps_token_version(tmp_path):
    store = UserStore(tmp_path / "auth.json")
    store.load()
    before = store.get("admin").token_version
    store.set_password("admin", "a-new-password")
    assert store.get("admin").token_version == before + 1


def test_last_admin_is_protected(tmp_path):
    store = UserStore(tmp_path / "auth.json")
    store.load()
    with pytest.raises(AuthError):
        store.delete_user("admin")
    with pytest.raises(AuthError):
        store.set_role("admin", "viewer")

    store.create_user("admin2", "another-password", "admin")
    store.delete_user("admin")  # now permitted — a second admin exists
    assert store.get("admin") is None


def test_rejects_weak_password_and_bad_username(tmp_path):
    store = UserStore(tmp_path / "auth.json")
    store.load()
    with pytest.raises(AuthError):
        store.create_user("ok", "short", "viewer")
    with pytest.raises(AuthError):
        store.create_user("bad name!", "a-long-enough-password", "viewer")


def test_bootstrap_recovers_from_an_empty_user_map(tmp_path):
    path = tmp_path / "auth.json"
    path.write_text(json.dumps({"version": 1, "session_secret": "00" * 32, "users": {}}))
    store = UserStore(path)
    store.load()
    assert store.get("admin") is not None


def test_removing_the_admin_entry_recreates_it_without_losing_viewers(tmp_path):
    """The documented password-recovery path: delete the admin from
    auth.json, restart, and get a fresh bootstrap password — while any
    viewer accounts survive."""
    path = tmp_path / "auth.json"
    first = UserStore(path)
    first.load()
    first.create_user("observer", "viewer-password", "viewer")

    document = json.loads(path.read_text())
    del document["users"]["admin"]
    path.write_text(json.dumps(document))

    second = UserStore(path)
    second.load()

    assert second.bootstrap_password is not None
    assert second.get("admin").role == "admin"
    assert second.get("observer") is not None
    assert second.authenticate("observer", "viewer-password") is not None


# ---- session tokens ------------------------------------------------------


def test_session_token_roundtrip():
    secret = b"x" * 32
    token = sessions.issue(secret, username="admin", role="admin", token_version=3, ttl=timedelta(hours=1))
    claims = sessions.verify(secret, token)
    assert claims is not None
    assert (claims.username, claims.role, claims.token_version) == ("admin", "admin", 3)


def test_session_token_rejects_tampering_and_wrong_secret():
    secret = b"x" * 32
    token = sessions.issue(secret, username="viewer", role="viewer", token_version=1, ttl=timedelta(hours=1))

    assert sessions.verify(b"y" * 32, token) is None

    # Keep the signature, swap in a payload that claims the admin role —
    # this is the privilege escalation the HMAC exists to stop.
    _payload, signature = token.split(".", 1)
    escalated = sessions.issue(
        b"attacker-secret", username="viewer", role="admin", token_version=1, ttl=timedelta(hours=1)
    )
    assert sessions.verify(secret, f"{escalated.split('.')[0]}.{signature}") is None

    assert sessions.verify(secret, f"{_payload}.garbage") is None
    assert sessions.verify(secret, "not-a-token") is None


def test_expired_session_token_is_rejected():
    secret = b"x" * 32
    token = sessions.issue(secret, username="a", role="admin", token_version=1, ttl=timedelta(seconds=-1))
    assert sessions.verify(secret, token) is None
