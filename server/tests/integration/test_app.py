from fastapi.testclient import TestClient

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
