"""Accounts for the web demo: registration, password login and server-side session tokens.

Standard library only: scrypt password hashes with a random salt, random tokens of which only a
SHA-256 hash is stored, and a short lockout after repeated wrong passwords.
"""

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta

from sessions import Storage

USERNAME = re.compile(r"[A-Za-z0-9_]{3,20}")
MIN_PASSWORD_LENGTH = 8
MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=1)
TOKEN_LIFETIME = timedelta(days=7)
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


class AccountError(ValueError):
    """Shown to the person signing in; the message never says which part was wrong."""


class Accounts:
    def __init__(self, storage: Storage, clock=datetime.now):
        self.storage, self.clock = storage, clock
        storage.run(
            "CREATE TABLE IF NOT EXISTS users ("
            "user_id TEXT PRIMARY KEY, password_hash TEXT NOT NULL, failed_logins INTEGER NOT NULL DEFAULT 0, "
            "locked_until TEXT, created_at TEXT NOT NULL)"
        )
        storage.run(
            "CREATE TABLE IF NOT EXISTS auth_tokens ("
            "token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at TEXT NOT NULL)"
        )

    def register(self, username: str, password: str) -> str:
        user_id = username.strip().lower()
        if not USERNAME.fullmatch(user_id):
            raise AccountError("Usernames are 3–20 letters, digits or underscores.")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise AccountError(f"Passwords need at least {MIN_PASSWORD_LENGTH} characters.")
        added = self.storage.run(
            "INSERT INTO users (user_id, password_hash, created_at) VALUES (%s, %s, %s) ON CONFLICT (user_id) DO NOTHING",
            (user_id, _hash_password(password), self._now()),
        )
        if not added:
            raise AccountError("This username is already taken.")
        return user_id

    def login(self, username: str, password: str) -> tuple[str, str]:
        """The user id and a new session token."""
        user_id = username.strip().lower()
        rows = self.storage.rows("SELECT password_hash, failed_logins, locked_until FROM users WHERE user_id = %s", (user_id,))
        if rows and rows[0][2] and rows[0][2] > self._now():
            raise AccountError("Too many wrong passwords. Try again in a minute.")
        if not rows or not _check_password(password, rows[0][0]):
            if rows:
                failures = rows[0][1] + 1
                locked = failures >= MAX_FAILED_LOGINS
                self.storage.run(
                    "UPDATE users SET failed_logins = %s, locked_until = %s WHERE user_id = %s",
                    (0 if locked else failures, self._now(LOCKOUT) if locked else None, user_id),
                )
            raise AccountError("Wrong username or password.")
        self.storage.run("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE user_id = %s", (user_id,))
        token = secrets.token_urlsafe(32)
        self.storage.run(
            "INSERT INTO auth_tokens VALUES (%s, %s, %s)",
            (_token_hash(token), user_id, self._now(TOKEN_LIFETIME)),
        )
        return user_id, token

    def user_for(self, token: str | None) -> str | None:
        if not token:
            return None
        self.storage.run("DELETE FROM auth_tokens WHERE expires_at <= %s", (self._now(),))
        rows = self.storage.rows("SELECT user_id FROM auth_tokens WHERE token_hash = %s", (_token_hash(token),))
        return rows[0][0] if rows else None

    def logout(self, token: str | None) -> None:
        if token:
            self.storage.run("DELETE FROM auth_tokens WHERE token_hash = %s", (_token_hash(token),))

    def sign_out_everywhere(self, user_id: str) -> None:
        self.storage.run("DELETE FROM auth_tokens WHERE user_id = %s", (user_id,))

    def exists(self, user_id: str) -> bool:
        return bool(self.storage.rows("SELECT 1 FROM users WHERE user_id = %s", (user_id,)))

    def _now(self, later: timedelta = timedelta()) -> str:
        return (self.clock() + later).isoformat(timespec="seconds")


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def _check_password(password: str, stored: str) -> bool:
    _, salt, digest = stored.split("$")
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **_SCRYPT)
    return hmac.compare_digest(candidate.hex(), digest)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
