"""Email and password accounts with server-side sessions.

Passwords are stored as scrypt hashes. The browser only receives a random
session token; the database stores the SHA-256 of that token.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.errors import UniqueViolation

from helpers.db import connect

SESSION_COOKIE = "session"
SESSION_DAYS = 14
_SQL_PATH = Path(__file__).resolve().parents[2] / "database" / "sql" / "users.sql"
_schema_lock = threading.Lock()
_schema_ready = False
_DUMMY_HASH = ""


class EmailTaken(Exception):
    pass


class InvalidCredentials(Exception):
    pass


@dataclass(frozen=True)
class User:
    id: int
    email: str


def normalize_email(email: str) -> str:
    cleaned = email.strip().lower()
    if "@" not in cleaned or cleaned.startswith("@") or cleaned.endswith("@") or any(
        character.isspace() for character in cleaned
    ):
        raise ValueError("Enter a valid email address")
    return cleaned


def hash_password(password: str) -> str:
    _check_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, n_text, r_text, p_text, salt_hex, digest_hex = stored.split("$")
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(n_text),
            r=int(r_text),
            p=int(p_text),
            dklen=len(bytes.fromhex(digest_hex)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def register_user(email: str, password: str) -> tuple[User, str]:
    normalized = normalize_email(email)
    password_hash = hash_password(password)
    conn = _connect()
    try:
        with conn.transaction():
            row = conn.execute(
                """
                INSERT INTO users (email, password_hash)
                VALUES (%s, %s)
                RETURNING id, email
                """,
                (normalized, password_hash),
            ).fetchone()
            user = User(int(row[0]), str(row[1]))
            token = _insert_session(conn, user.id)
        return user, token
    except UniqueViolation as exc:
        raise EmailTaken(normalized) from exc
    finally:
        conn.close()


def login(email: str, password: str) -> tuple[User, str]:
    normalized = normalize_email(email)
    _check_password(password)
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, email, password_hash FROM users WHERE email = %s",
            (normalized,),
        ).fetchone()
        stored_hash = str(row[2]) if row is not None else _dummy_hash()
        if row is None or not verify_password(password, stored_hash):
            raise InvalidCredentials()
        user = User(int(row[0]), str(row[1]))
        with conn.transaction():
            token = _insert_session(conn, user.id)
        return user, token
    finally:
        conn.close()


def logout(token: str) -> None:
    if not token:
        return
    conn = _connect()
    try:
        with conn.transaction():
            conn.execute(
                "DELETE FROM sessions WHERE token_hash = %s",
                (_token_hash(token),),
            )
    finally:
        conn.close()


def user_from_token(token: str) -> User | None:
    if not token:
        return None
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT users.id, users.email
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = %s
              AND sessions.expires_at > now()
            """,
            (_token_hash(token),),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return User(int(row[0]), str(row[1]))


def _check_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    if len(password) > 128:
        raise ValueError("Password must be at most 128 characters")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _insert_session(conn: psycopg.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    conn.execute(
        """
        INSERT INTO sessions (token_hash, user_id, expires_at)
        VALUES (%s, %s, %s)
        """,
        (_token_hash(token), user_id, expires_at),
    )
    return token


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if not _DUMMY_HASH:
        _DUMMY_HASH = hash_password("dummy-password")
    return _DUMMY_HASH


def _connect() -> psycopg.Connection:
    global _schema_ready
    conn = connect()
    with _schema_lock:
        if not _schema_ready:
            try:
                for statement in _SQL_PATH.read_text().split(";"):
                    sql = statement.strip()
                    if sql:
                        conn.execute(sql)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            _schema_ready = True
    return conn
