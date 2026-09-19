"""Password hashing.

Uses `hashlib.scrypt` rather than pulling in passlib/argon2: scrypt is in the
stdlib (OpenSSL-backed), memory-hard, and entirely adequate for the handful
of local operator accounts this app has. The cost parameters are stored
*inside* the encoded hash, so they can be raised later without invalidating
credentials that already exist on deployed cameras.
"""

from __future__ import annotations

import base64
import hmac
import secrets
from hashlib import scrypt

# ~16 MiB of memory per verification (128 * N * r), ~100 ms on a Pi 4.
_N = 2**14
_R = 8
_P = 1
_DKLEN = 32
_SALT_BYTES = 16

_SCHEME = "scrypt"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=_DKLEN)


def hash_password(password: str) -> str:
    """Encode as `scrypt$<n>$<r>$<p>$<salt>$<hash>` (both fields base64url)."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _derive(password, salt, _N, _R, _P)
    return f"{_SCHEME}${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time check of `password` against an encoded hash.

    Returns False rather than raising on a malformed/unknown-scheme hash, so
    a corrupted auth.json locks people out instead of letting them in.
    """
    try:
        scheme, n_s, r_s, p_s, salt_s, digest_s = encoded.split("$")
        if scheme != _SCHEME:
            return False
        expected = _unb64(digest_s)
        actual = _derive(password, _unb64(salt_s), int(n_s), int(r_s), int(p_s))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def needs_rehash(encoded: str) -> bool:
    """True when `encoded` was produced with weaker parameters than current."""
    try:
        scheme, n_s, r_s, p_s, _salt, _digest = encoded.split("$")
    except ValueError:
        return True
    return scheme != _SCHEME or (int(n_s), int(r_s), int(p_s)) != (_N, _R, _P)
