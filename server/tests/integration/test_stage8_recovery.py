from __future__ import annotations

import shutil
from pathlib import Path
from threading import Event

from fastapi.testclient import TestClient

from dokura.main import create_app
from dokura.metadata.scanning import ScanCoordinator
from dokura.sqlite_check import SQLiteCapabilities


ORIGIN = {"Origin": "http://testserver"}


def _sqlite_ok() -> SQLiteCapabilities:
    return SQLiteCapabilities(version="3.51.3", fts5_trigram=True)


def _login_token(client: TestClient, password: str = "admin") -> str:
    response = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": password}
    )
    assert response.status_code == 200
    token = response.cookies.get("dokura_session")
    assert token
    client.cookies.clear()
    return token


def _cookie(token: str) -> dict[str, str]:
    return {"Cookie": f"dokura_session={token}"}


def test_logout_and_password_change_revoke_the_required_sessions(settings) -> None:
    with TestClient(create_app(settings=settings, sqlite_check=_sqlite_ok)) as client:
        first = _login_token(client)
        second = _login_token(client)

        logout = client.post(
            "/api/v1/auth/logout", headers={**ORIGIN, **_cookie(first)}
        )
        assert logout.status_code == 204
        assert client.get("/api/v1/auth/session", headers=_cookie(first)).status_code == 401
        assert client.get("/api/v1/auth/session", headers=_cookie(second)).status_code == 200

        changed = client.put(
            "/api/v1/admin/password",
            headers={**ORIGIN, **_cookie(second)},
            json={
                "current_password": "admin",
                "new_password": "阶段八恢复测试密码",
                "new_password_confirmation": "阶段八恢复测试密码",
            },
        )
        assert changed.status_code == 204
        assert client.get("/api/v1/auth/session", headers=_cookie(second)).status_code == 401


def test_health_remains_available_while_scan_is_running(settings, monkeypatch) -> None:
    started = Event()
    release = Event()
    original = ScanCoordinator.scan_once

    def delayed_scan(self):
        started.set()
        if not release.wait(2):
            raise TimeoutError("测试扫描未释放")
        return original(self)

    monkeypatch.setattr(ScanCoordinator, "scan_once", delayed_scan)
    try:
        with TestClient(create_app(settings=settings, sqlite_check=_sqlite_ok)) as client:
            assert started.wait(1)
            assert client.get("/api/v1/health").status_code == 200
            release.set()
    finally:
        release.set()


def test_cold_restore_keeps_credentials_and_sessions(settings, tmp_path: Path) -> None:
    app = create_app(settings=settings, sqlite_check=_sqlite_ok)
    with TestClient(app) as client:
        session_token = _login_token(client)
        key = client.post(
            "/api/v1/admin/api-key",
            headers={**ORIGIN, **_cookie(session_token)},
            json={"current_password": "admin", "confirmed": True},
        ).json()["api_key"]

    backup = tmp_path / "cold-backup"
    shutil.copytree(settings.metadata_dir, backup / "MetaData")
    shutil.copytree(settings.config_dir, backup / "Config")

    shutil.rmtree(settings.metadata_dir)
    shutil.rmtree(settings.config_dir)
    shutil.copytree(backup / "MetaData", settings.metadata_dir)
    shutil.copytree(backup / "Config", settings.config_dir)

    with TestClient(create_app(settings=settings, sqlite_check=_sqlite_ok)) as client:
        assert client.get(
            "/api/v1/auth/session", headers=_cookie(session_token)
        ).status_code == 200
        assert client.get(
            "/api/v1/catalog", headers={"Authorization": f"Bearer {key}"}
        ).status_code == 200
