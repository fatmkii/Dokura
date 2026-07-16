from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from dokura.metadata.database import WriteScheduler
from dokura.metadata.models import LoginFailure, WebSession, utc_now
from dokura.metadata.natural_sort import normalized_casefold


SESSION_COOKIE = "dokura_session"
IDLE_LIFETIME = timedelta(hours=24)
ABSOLUTE_LIFETIME = timedelta(days=7)
FAILURE_WINDOW = timedelta(minutes=15)
LOCKOUT_TIME = timedelta(minutes=15)
MAX_FAILURES = 5
cookie_security = APIKeyCookie(name=SESSION_COOKIE, auto_error=False, scheme_name="WebSession")
bearer_security = HTTPBearer(auto_error=False, scheme_name="AndroidAPIKey")


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _secret_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32
        )
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def _lockout_retry(engine, source_ip: str, username_casefold: str, now: datetime) -> int:
    cutoff = now - FAILURE_WINDOW - LOCKOUT_TIME
    remaining = 0
    with Session(engine) as session:
        for criterion in (
            LoginFailure.source_ip == source_ip,
            LoginFailure.username_casefold == username_casefold,
        ):
            failures = [
                _utc(value) for value in session.scalars(
                    select(LoginFailure.failed_at).where(LoginFailure.failed_at >= cutoff, criterion)
                    .order_by(LoginFailure.failed_at)
                )
            ]
            for index in range(len(failures) - MAX_FAILURES + 1):
                threshold = failures[index + MAX_FAILURES - 1]
                if threshold - failures[index] <= FAILURE_WINDOW and now < threshold + LOCKOUT_TIME:
                    remaining = max(remaining, int((threshold + LOCKOUT_TIME - now).total_seconds()) + 1)
    return remaining


@dataclass(frozen=True, slots=True)
class Principal:
    kind: str
    session_id: str | None = None


class CredentialStore:
    """Small Config-volume secret store; only salted/one-way hashes are persisted."""

    def __init__(self, config_dir: Path) -> None:
        self.path = config_dir / "credentials.json"
        self._lock = Lock()
        if not self.path.exists():
            initial_key = secrets.token_urlsafe(32)
            self._write({
                "username": "admin",
                "password_hash": _password_hash("admin"),
                "api_key_hash": _secret_hash(initial_key),
                "api_key_suffix": initial_key[-4:],
            })

    def _read(self) -> dict[str, str]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict[str, str]) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)

    def verify_admin(self, username: str, password: str) -> bool:
        data = self._read()
        return hmac.compare_digest(normalized_casefold(username), normalized_casefold(data["username"])) and _verify_password(password, data["password_hash"])

    def verify_password(self, password: str) -> bool:
        return _verify_password(password, self._read()["password_hash"])

    def set_password(self, password: str) -> None:
        with self._lock:
            data = self._read()
            data["password_hash"] = _password_hash(password)
            self._write(data)

    def verify_api_key(self, value: str) -> bool:
        return hmac.compare_digest(_secret_hash(value), self._read()["api_key_hash"])

    def rotate_api_key(self) -> tuple[str, str]:
        value = secrets.token_urlsafe(32)
        with self._lock:
            data = self._read()
            data["api_key_hash"] = _secret_hash(value)
            data["api_key_suffix"] = value[-4:]
            self._write(data)
        return value, value[-4:]

    @property
    def api_key_suffix(self) -> str:
        return self._read().get("api_key_suffix", "")


class AuthService:
    def __init__(self, engine, writer: WriteScheduler, credentials: CredentialStore) -> None:
        self.engine = engine
        self.writer = writer
        self.credentials = credentials

    def login(self, username: str, password: str, source_ip: str) -> tuple[str, WebSession]:
        now = utc_now()
        cutoff = now - FAILURE_WINDOW
        folded = normalized_casefold(username)
        retry_after = _lockout_retry(self.engine, source_ip, folded, now)
        if retry_after:
            raise HTTPException(status_code=429, detail="登录尝试过多，请稍后再试", headers={"Retry-After": str(retry_after)})

        if not self.credentials.verify_admin(username, password):
            with self.writer.transaction() as session:
                session.execute(delete(LoginFailure).where(LoginFailure.failed_at < cutoff))
                session.add(LoginFailure(source_ip=source_ip, username_casefold=folded, failed_at=now))
            retry_after = _lockout_retry(self.engine, source_ip, folded, now)
            if retry_after:
                raise HTTPException(status_code=429, detail="登录尝试过多，请稍后再试", headers={"Retry-After": str(retry_after)})
            raise HTTPException(status_code=401, detail="账号或密码错误")

        token = secrets.token_urlsafe(32)
        absolute = now + ABSOLUTE_LIFETIME
        record = WebSession(
            id=secrets.token_hex(16), token_hash=_secret_hash(token), created_at=now,
            last_used_at=now, expires_at=now + IDLE_LIFETIME,
            absolute_expires_at=absolute, revoked=False,
        )
        with self.writer.transaction() as session:
            session.execute(delete(LoginFailure).where(
                or_(LoginFailure.source_ip == source_ip, LoginFailure.username_casefold == folded)
            ))
            session.add(record)
        return token, record

    def authenticate(self, request: Request, *, web_only: bool = False) -> Principal:
        authorization = request.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            if web_only:
                raise HTTPException(status_code=401, detail="Android 凭据无权访问管理接口")
            if self.credentials.verify_api_key(authorization[7:]):
                return Principal("android")
            raise HTTPException(status_code=401, detail="APIkey 无效")

        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            raise HTTPException(status_code=401, detail="需要登录")
        now = utc_now()
        with self.writer.transaction() as session:
            record = session.scalar(select(WebSession).where(WebSession.token_hash == _secret_hash(token)))
            if record is None or record.revoked or _utc(record.expires_at) <= now or _utc(record.absolute_expires_at) <= now:
                if record is not None:
                    record.revoked = True
                raise HTTPException(status_code=401, detail="登录会话已过期")
            record.last_used_at = now
            record.expires_at = min(now + IDLE_LIFETIME, _utc(record.absolute_expires_at))
            return Principal("web", record.id)

    def check_current_password(self, password: str, source_ip: str) -> None:
        now = utc_now()
        cutoff = now - FAILURE_WINDOW
        folded = normalized_casefold("admin")
        retry_after = _lockout_retry(self.engine, source_ip, folded, now)
        if retry_after:
            raise HTTPException(status_code=429, detail="密码尝试过多，请稍后再试", headers={"Retry-After": str(retry_after)})
        if not self.credentials.verify_password(password):
            with self.writer.transaction() as session:
                session.add(LoginFailure(source_ip=source_ip, username_casefold=folded, failed_at=now))
            retry_after = _lockout_retry(self.engine, source_ip, folded, now)
            status = 429 if retry_after else 401
            headers = {"Retry-After": str(retry_after)} if status == 429 else None
            raise HTTPException(status_code=status, detail="当前密码错误", headers=headers)
        with self.writer.transaction() as session:
            session.execute(delete(LoginFailure).where(
                or_(LoginFailure.source_ip == source_ip, LoginFailure.username_casefold == folded)
            ))

    def revoke(self, session_id: str) -> None:
        with self.writer.transaction() as session:
            record = session.get(WebSession, session_id)
            if record is not None:
                record.revoked = True

    def revoke_all(self) -> None:
        with self.writer.transaction() as session:
            session.execute(update(WebSession).values(revoked=True))


def require_same_origin(request: Request) -> None:
    origin = request.headers.get("Origin")
    if not origin:
        raise HTTPException(status_code=403, detail="管理写操作需要 Origin")
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.casefold() != request.headers.get("host", "").casefold():
        raise HTTPException(status_code=403, detail="Origin 校验失败")


async def require_read_access(
    request: Request,
    _cookie: str | None = Security(cookie_security),
    _bearer: HTTPAuthorizationCredentials | None = Security(bearer_security),
) -> Principal:
    return await asyncio.to_thread(request.app.state.auth.authenticate, request)


async def require_web_access(
    request: Request,
    _cookie: str | None = Security(cookie_security),
) -> Principal:
    return await asyncio.to_thread(request.app.state.auth.authenticate, request, web_only=True)


def validate_new_password(current: str, new: str) -> None:
    if not 8 <= len(new) <= 128:
        raise HTTPException(status_code=422, detail="新密码长度必须为 8 至 128 个字符")
    if new == "admin":
        raise HTTPException(status_code=422, detail="新密码不能使用默认密码")
    if hmac.compare_digest(current.encode(), new.encode()):
        raise HTTPException(status_code=422, detail="新密码不能与当前密码相同")
