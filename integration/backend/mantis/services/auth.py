"""Email and password accounts with server-side sessions.

Passwords are stored as scrypt hashes. The browser only ever receives a random
session token in an HttpOnly cookie; the database stores the SHA-256 of that token,
so a leaked table cannot be replayed as a cookie.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import psycopg
from psycopg.errors import UniqueViolation

from mantis import db
from mantis.errors import Conflict, InvalidInput, NotSignedIn

SESSION_COOKIE = "session"
SESSION_DAYS = 14
MIN_PASSWORD = 8
MAX_PASSWORD = 128


@dataclass(frozen=True)
class User:
    id: int
    email: str

    def to_api(self) -> dict[str, object]:
        return {"id": self.id, "email": self.email}


def normalize_email(email: str) -> str:
    cleaned = email.strip().lower()
    local, _, domain = cleaned.partition("@")
    if not local or not domain or any(character.isspace() for character in cleaned):
        raise InvalidInput("Enter a valid email address")
    return cleaned


def check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise InvalidInput(f"Password must be at least {MIN_PASSWORD} characters")
    if len(password) > MAX_PASSWORD:
        raise InvalidInput(f"Password must be at most {MAX_PASSWORD} characters")


def hash_password(password: str) -> str:
    """``scrypt$n$r$p$salt$digest`` so the cost parameters travel with the hash."""
    check_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, n, r, p, salt_hex, digest_hex = stored.split("$")
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(digest_hex)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def register(email: str, password: str) -> tuple[User, str]:
    """Create an account and its first session. Returns the user and the session token."""
    normalized = normalize_email(email)
    password_hash = hash_password(password)
    try:
        with db.session() as conn, conn.transaction():
            row = conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id, email",
                (normalized, password_hash),
            ).fetchone()
            user = User(int(row[0]), str(row[1]))
            return user, _insert_session(conn, user.id)
    except UniqueViolation as exc:
        raise Conflict("An account with that email already exists") from exc


def login(email: str, password: str) -> tuple[User, str]:
    normalized = normalize_email(email)
    check_password(password)
    with db.session() as conn:
        row = conn.execute(
            "SELECT id, email, password_hash FROM users WHERE email = %s",
            (normalized,),
        ).fetchone()
        # Hash even for an unknown email so response time doesn't reveal which emails exist.
        stored_hash = str(row[2]) if row is not None else _dummy_hash()
        if row is None or not verify_password(password, stored_hash):
            raise NotSignedIn("Invalid email or password")
        user = User(int(row[0]), str(row[1]))
        with conn.transaction():
            return user, _insert_session(conn, user.id)


def logout(token: str) -> None:
    if not token:
        return
    with db.session() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = %s", (_token_hash(token),))


def user_from_token(token: str) -> User | None:
    if not token:
        return None
    with db.session() as conn:
        row = conn.execute(
            """
            SELECT users.id, users.email
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = %s AND sessions.expires_at > now()
            """,
            (_token_hash(token),),
        ).fetchone()
    return None if row is None else User(int(row[0]), str(row[1]))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _insert_session(conn: psycopg.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
        (_token_hash(token), user_id, expires_at),
    )
    return token


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return hash_password("dummy-password")
