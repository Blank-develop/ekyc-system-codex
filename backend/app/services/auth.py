"""Per-user authentication: PBKDF2 password hashing + HS256 JWT access tokens.

Implemented with the standard library only (hashlib / hmac / base64) so the
service adds no dependencies and no build risk. Tokens are stateless: the signed
claims carry the subject and role, verified on each request.

Disabled by default (no LALIGENCE_JWT_SECRET) so the public demo stays open.
Users are seeded from config: LALIGENCE_AUTH_USERS = "name:pbkdf2_hash:role,...".
Generate a password hash with scripts/hash_password.py.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass

PBKDF2_ALGO = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 200_000


@dataclass(frozen=True)
class AuthUser:
    username: str
    role: str
    password_hash: str = ""


# --- Password hashing (PBKDF2-HMAC-SHA256) -----------------------------------

def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS, salt: bytes | None = None) -> str:
    salt = salt if salt is not None else os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"{PBKDF2_ALGO}${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != PBKDF2_ALGO:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# --- User directory (seeded from config) -------------------------------------

def load_users(entries: tuple[str, ...]) -> dict[str, AuthUser]:
    """Parse "username:pbkdf2_hash:role" entries. The hash uses '$' separators
    (no ':'), so the first field is the username and the last is the role."""
    users: dict[str, AuthUser] = {}
    for entry in entries:
        parts = entry.split(":")
        if len(parts) < 3:
            continue
        username, role = parts[0].strip(), parts[-1].strip()
        password_hash = ":".join(parts[1:-1]).strip()
        if username and password_hash and role:
            users[username] = AuthUser(username=username, role=role, password_hash=password_hash)
    return users


def authenticate(users: dict[str, AuthUser], username: str, password: str) -> AuthUser | None:
    user = users.get(username)
    if user and verify_password(password, user.password_hash):
        return user
    return None


# --- HS256 JWT ----------------------------------------------------------------

def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64u_decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def create_access_token(secret: str, subject: str, role: str, expires_minutes: int) -> str:
    now = int(time.time())
    header = _b64u(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64u(json.dumps(
        {"sub": subject, "role": role, "iat": now, "exp": now + expires_minutes * 60},
        separators=(",", ":"),
    ).encode())
    signing_input = f"{header}.{payload}"
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64u(signature)}"


def decode_token(secret: str | list[str] | tuple[str, ...], token: str) -> dict | None:
    """Verify signature + expiry against one secret or a rotation set (primary +
    retired). Returns the claims, or None if none verify / expired."""
    secrets = [secret] if isinstance(secret, str) else list(secret)
    for candidate in secrets:
        if not candidate:
            continue
        payload = _decode_one(candidate, token)
        if payload is not None:
            return payload
    return None


def _decode_one(secret: str, token: str) -> dict | None:
    try:
        signing_input, signature = token.rsplit(".", 1)
        expected = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64u_decode(signature)):
            return None
        payload = json.loads(_b64u_decode(signing_input.split(".")[1]))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None
