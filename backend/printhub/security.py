"""Accounts, password hashing, sessions and login throttling."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass

from .db import Database, now

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
MIN_PASSWORD_LENGTH = 8


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=len(digest) // 2
        )
        return hmac.compare_digest(candidate.hex(), digest)
    except (ValueError, TypeError):
        return False


# A real hash to compare against when the username does not exist, so the
# response time does not reveal which usernames are valid.
_DUMMY_HASH = hash_password(secrets.token_hex(8))


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > 256:
        return "Password is too long."
    return None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class User:
    id: int
    username: str
    display_name: str
    role: str
    must_change_password: bool
    station: bool = False

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def public(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
            "must_change_password": self.must_change_password,
            "station": self.station,
        }


class LoginThrottle:
    """In-memory failed-login counter keyed by username and client address."""

    def __init__(self, max_failures: int, window_s: float):
        self.max_failures = max_failures
        self.window_s = window_s
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        cutoff = time.monotonic() - self.window_s
        times = [t for t in self._failures.get(key, []) if t > cutoff]
        self._failures[key] = times
        return times

    def locked_for(self, *keys: str) -> float:
        with self._lock:
            worst = 0.0
            for key in keys:
                times = self._recent(key)
                if len(times) >= self.max_failures:
                    worst = max(worst, times[0] + self.window_s - time.monotonic())
            return max(0.0, worst)

    def fail(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._recent(key).append(time.monotonic())

    def clear(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._failures.pop(key, None)


class Accounts:
    def __init__(self, db: Database, session_hours: int):
        self.db = db
        self.session_seconds = session_hours * 3600

    # --- users -----------------------------------------------------------
    def create_user(self, username: str, display_name: str, password: str, role: str, must_change: bool = True) -> int:
        username = username.strip()
        if not username or len(username) > 64 or not all(c.isalnum() or c in "._-@" for c in username):
            raise ValueError("Usernames may contain letters, numbers and . _ - @")
        if role not in ("employee", "admin"):
            raise ValueError("Unknown role")
        problem = password_problem(password)
        if problem:
            raise ValueError(problem)
        if self.db.one("SELECT 1 FROM users WHERE username = ?", (username,)):
            raise ValueError("That username is already taken.")
        cur = self.db.execute(
            "INSERT INTO users (username, display_name, password_hash, role, must_change_password, created_at) VALUES (?,?,?,?,?,?)",
            (username, display_name.strip() or username, hash_password(password), role, int(must_change), now()),
        )
        return int(cur.lastrowid)

    def set_password(self, user_id: int, password: str, must_change: bool) -> None:
        problem = password_problem(password)
        if problem:
            raise ValueError(problem)
        with self.db.tx() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, must_change_password = ? WHERE id = ?",
                (hash_password(password), int(must_change), user_id),
            )
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def authenticate(self, username: str, password: str) -> dict | None:
        row = self.db.one("SELECT * FROM users WHERE username = ?", (username.strip(),))
        if not row or not row["active"]:
            verify_password(password, _DUMMY_HASH)
            return None
        if not verify_password(password, row["password_hash"]):
            return None
        return row

    def admin_count(self) -> int:
        return self.db.one("SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND active = 1")["n"]

    # --- sessions --------------------------------------------------------
    def create_session(self, user_id: int, station: bool) -> str:
        token = secrets.token_urlsafe(32)
        t = now()
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, last_seen_at, station) VALUES (?,?,?,?,?,?)",
                (_token_hash(token), user_id, t, t + self.session_seconds, t, int(station)),
            )
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (t, user_id))
        return token

    def resolve(self, token: str | None) -> User | None:
        if not token or len(token) > 200:
            return None
        row = self.db.one(
            "SELECT s.token_hash, s.expires_at, s.last_seen_at, s.station, u.* FROM sessions s JOIN users u ON u.id = s.user_id"
            " WHERE s.token_hash = ?",
            (_token_hash(token),),
        )
        t = now()
        if not row or row["expires_at"] < t or not row["active"]:
            return None
        if t - row["last_seen_at"] > 60:
            self.db.execute("UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?", (t, row["token_hash"]))
        return User(
            id=row["id"],
            username=row["username"],
            display_name=row["display_name"],
            role=row["role"],
            must_change_password=bool(row["must_change_password"]),
            station=bool(row["station"]),
        )

    def end_session(self, token: str | None) -> None:
        if token:
            self.db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))

    def purge_expired(self) -> int:
        return self.db.execute("DELETE FROM sessions WHERE expires_at < ?", (now(),)).rowcount
