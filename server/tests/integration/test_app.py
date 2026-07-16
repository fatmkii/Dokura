from fastapi.testclient import TestClient
from time import monotonic, sleep

from dokura.main import create_app
from dokura.sqlite_check import SQLiteCapabilities


def passing_sqlite_check() -> SQLiteCapabilities:
    return SQLiteCapabilities(version="3.51.3", fts5_trigram=True)


def test_health_is_available_without_scan(settings) -> None:
    with TestClient(create_app(settings=settings, sqlite_check=passing_sqlite_check)) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Dokura",
        "api_version": "1",
    }


def test_missing_route_uses_unified_error(settings) -> None:
    with TestClient(create_app(settings=settings, sqlite_check=passing_sqlite_check)) as client:
        response = client.get("/api/v1/missing", headers={"X-Request-ID": "test-id"})
    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "请求的资源不存在",
            "request_id": "test-id",
        }
    }


def test_startup_rejects_failed_sqlite_check(settings) -> None:
    def failing_check():
        raise RuntimeError("SQLite 运行时版本不满足要求")

    client = TestClient(create_app(settings=settings, sqlite_check=failing_check))
    try:
        with client:
            raise AssertionError("应用不应启动")
    except RuntimeError as exc:
        assert "SQLite 运行时版本不满足要求" in str(exc)


def test_startup_creates_writable_runtime_directories(settings) -> None:
    with TestClient(create_app(settings=settings, sqlite_check=passing_sqlite_check)):
        pass
    assert settings.metadata_dir.is_dir()
    assert settings.config_dir.is_dir()


def test_content_can_be_temporarily_unavailable_at_startup(settings) -> None:
    settings.content_dir.rmdir()
    with TestClient(create_app(settings=settings, sqlite_check=passing_sqlite_check)) as client:
        assert client.get("/api/v1/health").status_code == 200
        deadline = monotonic() + 2
        while monotonic() < deadline:
            status = client.get("/api/v1/admin/scan").json()
            if status["status"] == "failed":
                break
            sleep(0.01)
        assert status["status"] == "failed"


def test_stage2_management_endpoints_and_listener(settings) -> None:
    with TestClient(create_app(settings=settings, sqlite_check=passing_sqlite_check)) as client:
        deadline = monotonic() + 3
        while monotonic() < deadline:
            if client.get("/api/v1/admin/scan").json()["status"] in ("completed", "partial"):
                break
            sleep(0.01)

        (settings.content_dir / "listener.zip").write_bytes(b"still being written")
        deadline = monotonic() + 4
        waiting = 0
        while monotonic() < deadline:
            payload = client.get("/api/v1/admin/tasks").json()
            waiting = payload["waiting_count"]
            if waiting == 1:
                break
            sleep(0.05)
        assert waiting == 1

        response = client.post("/api/v1/admin/scan")
        assert response.status_code == 202
        preview = client.post("/api/v1/admin/cache-cleanup/preview")
        assert preview.status_code == 200
        confirmation_id = preview.json()["confirmation_id"]
        assert client.post(
            "/api/v1/admin/cache-cleanup/execute",
            json={"confirmation_id": confirmation_id},
        ).status_code == 200
