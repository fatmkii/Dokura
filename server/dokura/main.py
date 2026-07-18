import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from dokura.config import Settings
from dokura.api import install_stage3_api
from dokura.constants import API_VERSION, APP_NAME, APP_VERSION, OPENAPI_VERSION
from dokura.errors import install_error_handlers
from dokura.i18n.zh_cn import OPENAPI_TAGS
from dokura.logging import configure_logging
from dokura.logfiles import LogManager
from dokura.management import FileOperationLocks, ManagementService
from dokura.metadata.database import WriteScheduler, create_database_engine
from dokura.metadata.cache_cleanup import CacheCleanupManager
from dokura.metadata.migrations import upgrade_database
from dokura.metadata.models import Task
from dokura.metadata.scanning import ScanCoordinator
from dokura.metadata.tasks import ForegroundPressure, TaskScheduler
from dokura.metadata.watcher import watch_content
from dokura.images import ImageService
from dokura.security import AuthService, CredentialStore, require_same_origin, require_web_access
from dokura.sqlite_check import SQLiteCapabilities, verify_sqlite_capabilities
from dokura.stage5_api import install_stage5_api


SQLiteCheck = Callable[[], SQLiteCapabilities]


class CleanupExecution(BaseModel):
    confirmation_id: str


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
        logs = LogManager(runtime_settings.config_dir)
        logs.install()
        capabilities = sqlite_check()
        runtime_settings.prepare()
        upgrade_database(runtime_settings.database_path)
        engine = create_database_engine(runtime_settings.database_path)
        app.state.sqlite = capabilities
        app.state.settings = runtime_settings
        app.state.database_engine = engine
        writer = WriteScheduler(engine)
        pressure = ForegroundPressure()
        operation_locks = FileOperationLocks()
        task_scheduler = TaskScheduler(
            engine, writer, runtime_settings.content_dir, runtime_settings.cover_dir, pressure,
            operation_locks=operation_locks,
        )
        scans = ScanCoordinator(engine, writer, runtime_settings.content_dir, task_scheduler, pressure)
        cache_cleanup = CacheCleanupManager(
            engine, writer, runtime_settings.metadata_dir, runtime_settings.content_dir
        )
        app.state.writer = writer
        app.state.foreground_pressure = pressure
        app.state.task_scheduler = task_scheduler
        app.state.scans = scans
        app.state.cache_cleanup = cache_cleanup
        app.state.operation_locks = operation_locks
        app.state.management = ManagementService(
            engine, writer, runtime_settings.content_dir, scans, task_scheduler, operation_locks
        )
        app.state.logs = logs
        credentials = CredentialStore(runtime_settings.config_dir)
        app.state.auth = AuthService(engine, writer, credentials)
        app.state.images = ImageService(
            engine, writer, runtime_settings.content_dir, runtime_settings.cover_dir,
            operation_locks,
        )
        watcher_stop = asyncio.Event()
        workers = [
            asyncio.create_task(task_scheduler.run(), name="dokura-task-scheduler"),
            asyncio.create_task(scans.run(), name="dokura-scan-coordinator"),
            asyncio.create_task(watch_content(runtime_settings.content_dir, scans, watcher_stop), name="dokura-content-watcher"),
        ]
        try:
            yield
        finally:
            await scans.stop()
            await task_scheduler.stop()
            watcher_stop.set()
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            logs.handler.close()
            engine.dispose()

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

    @app.get("/api/v1/admin/scan", tags=[OPENAPI_TAGS["background"]], dependencies=[Depends(require_web_access)])
    async def scan_status(request: Request) -> dict[str, object]:
        return await asyncio.to_thread(app.state.scans.latest_status)

    @app.post("/api/v1/admin/scan", status_code=202, tags=[OPENAPI_TAGS["background"]], dependencies=[Depends(require_web_access)])
    async def request_scan(request: Request) -> dict[str, bool]:
        require_same_origin(request)
        return {"accepted": app.state.scans.request_scan()}

    @app.get("/api/v1/admin/tasks", tags=[OPENAPI_TAGS["background"]], dependencies=[Depends(require_web_access)])
    async def task_status(request: Request, page: int = 1) -> dict[str, object]:
        def read_tasks() -> dict[str, object]:
            with Session(app.state.database_engine) as session:
                active = session.scalars(select(Task).where(Task.status == "analyzing").order_by(Task.started_at)).all()
                queued = session.scalars(select(Task).where(
                    Task.status.in_(("waiting_stable", "retry_wait"))
                ).order_by(Task.priority.desc(), Task.created_at).offset((max(1, page) - 1) * 50).limit(50)).all()
                history = session.scalars(select(Task).where(
                    ~Task.status.in_(("analyzing", "waiting_stable", "retry_wait"))
                ).order_by(Task.updated_at.desc()).limit(100)).all()
                tasks = [*active, *queued, *history]
                waiting = session.scalar(select(func.count()).select_from(Task).where(
                    Task.status.in_(("waiting_stable", "retry_wait"))
                ))
                return {
                    "waiting_count": waiting or 0,
                    "items": [
                        {
                            "id": task.id,
                            "file_id": task.file_id,
                            "relative_path": task.relative_path,
                            "type": task.task_type,
                            "status": task.status,
                            "priority": task.priority,
                            "retry_count": task.retry_count,
                            "max_retries": 3,
                            "next_run_at": task.next_run_at,
                            "last_error": task.last_error,
                            "created_at": task.created_at,
                            "started_at": task.started_at,
                            "updated_at": task.updated_at,
                        }
                        for task in tasks
                    ],
                }
        return await asyncio.to_thread(read_tasks)

    @app.post("/api/v1/admin/cache-cleanup/preview", tags=[OPENAPI_TAGS["cache"]], dependencies=[Depends(require_web_access)])
    async def cleanup_preview(request: Request) -> dict[str, object]:
        require_same_origin(request)
        preview = await asyncio.to_thread(app.state.cache_cleanup.preview)
        return {
            "confirmation_id": preview.confirmation_id,
            "file_count": preview.file_count,
            "cache_file_count": preview.cache_file_count,
            "estimated_bytes": preview.estimated_bytes,
        }

    @app.post("/api/v1/admin/cache-cleanup/execute", tags=[OPENAPI_TAGS["cache"]], dependencies=[Depends(require_web_access)])
    async def cleanup_execute(payload: CleanupExecution, request: Request) -> dict[str, int]:
        require_same_origin(request)
        try:
            return await asyncio.to_thread(app.state.cache_cleanup.execute, payload.confirmation_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    install_stage3_api(app)
    install_stage5_api(app)

    static_dir = web_dist or Path(__file__).resolve().parents[2] / "web" / "dist"
    if static_dir.is_dir():
        assets_dir = static_dir / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/", include_in_schema=False)
        async def web_index() -> FileResponse:
            return FileResponse(static_dir / "index.html")

        @app.get("/{web_path:path}", include_in_schema=False)
        async def web_route(web_path: str) -> FileResponse:
            # Vue Router owns non-API browser routes. API typos must retain the
            # unified JSON 404 instead of receiving the HTML application shell.
            if web_path == "api" or web_path.startswith("api/"):
                raise HTTPException(status_code=404)
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
