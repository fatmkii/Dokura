from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from dokura.config import Settings
from dokura.constants import API_VERSION, APP_NAME, APP_VERSION, OPENAPI_VERSION
from dokura.errors import install_error_handlers
from dokura.i18n.zh_cn import OPENAPI_TAGS
from dokura.logging import configure_logging
from dokura.sqlite_check import SQLiteCapabilities, verify_sqlite_capabilities


SQLiteCheck = Callable[[], SQLiteCapabilities]


def create_app(
    *,
    settings: Settings | None = None,
    sqlite_check: SQLiteCheck = verify_sqlite_capabilities,
    web_dist: Path | None = None,
) -> FastAPI:
    runtime_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        capabilities = sqlite_check()
        runtime_settings.prepare()
        app.state.sqlite = capabilities
        app.state.settings = runtime_settings
        yield

    app = FastAPI(
        title=APP_NAME,
        version=APP_VERSION,
        openapi_version=OPENAPI_VERSION,
        lifespan=lifespan,
    )
    install_error_handlers(app)

    @app.get("/api/v1/health", tags=[OPENAPI_TAGS["health_identity"]])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": APP_NAME, "api_version": API_VERSION}

    @app.get("/api/v1/identity", tags=[OPENAPI_TAGS["health_identity"]])
    async def identity() -> dict[str, str]:
        return {
            "service": APP_NAME,
            "server_version": APP_VERSION,
            "api_version": API_VERSION,
        }

    static_dir = web_dist or Path(__file__).resolve().parents[2] / "web" / "dist"
    if static_dir.is_dir():
        assets_dir = static_dir / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/", include_in_schema=False)
        async def web_index() -> FileResponse:
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
