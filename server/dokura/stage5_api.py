from __future__ import annotations

import asyncio
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from dokura.catalog import CatalogQuery, normalize_catalog_path
from dokura.management import ManagementError
from dokura.security import Principal, require_same_origin, require_web_access


class SelectionInput(BaseModel):
    path: str = ""
    query: str = ""
    scope: Literal["current", "recursive"] = "current"
    tag_ids: list[int] = Field(default_factory=list)
    tag_mode: Literal["all", "any", "grouped"] = "all"
    rating_min: int = Field(0, ge=0, le=5)
    rating_max: int = Field(5, ge=0, le=5)
    sort: Literal["name", "size", "modified", "rating"] = "name"
    direction: Literal["asc", "desc"] = "asc"


class DeleteConfirmation(BaseModel):
    snapshot_id: str
    file_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)


class RenameInput(BaseModel):
    name: str


class MoveInput(BaseModel):
    target_directory: str


class BatchMoveInput(MoveInput):
    file_ids: list[str]


class DirectoryInput(BaseModel):
    parent: str = ""
    name: str


def install_stage5_api(app: FastAPI) -> None:
    def session_id(principal: Principal) -> str:
        if principal.session_id is None:
            raise HTTPException(status_code=401, detail="需要登录")
        return principal.session_id

    def query_from(payload: SelectionInput) -> CatalogQuery:
        if payload.rating_min > payload.rating_max:
            raise HTTPException(status_code=422, detail="评分下限不能大于上限")
        try:
            path = normalize_catalog_path(payload.path)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return CatalogQuery(
            path=path, query=payload.query, scope=payload.scope,
            tag_ids=tuple(payload.tag_ids), tag_mode=payload.tag_mode,
            rating_min=payload.rating_min, rating_max=payload.rating_max,
            sort=payload.sort, direction=payload.direction,
        )

    async def call(method, *args):
        try:
            return await asyncio.to_thread(method, *args)
        except ManagementError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/admin/selection", tags=["文件管理"])
    async def create_selection(payload: SelectionInput, request: Request, principal: Principal = Depends(require_web_access)):
        require_same_origin(request)
        snapshot = await call(app.state.management.create_snapshot, session_id(principal), query_from(payload))
        return {"id": snapshot.id, "count": len(snapshot.file_ids), "expires_in_seconds": 1800}

    @app.get("/api/v1/admin/selection", tags=["文件管理"])
    async def get_selection(request: Request, principal: Principal = Depends(require_web_access)):
        snapshot = await call(app.state.management.snapshot, session_id(principal))
        return {"active": snapshot is not None, "id": snapshot.id if snapshot else None, "count": len(snapshot.file_ids) if snapshot else 0}

    @app.delete("/api/v1/admin/selection", status_code=204, tags=["文件管理"])
    async def clear_selection(request: Request, principal: Principal = Depends(require_web_access)):
        require_same_origin(request)
        await call(app.state.management.release_snapshot, session_id(principal))
        return Response(status_code=204)

    @app.post("/api/v1/admin/selection/delete-preview", tags=["文件管理"])
    async def delete_preview(request: Request, principal: Principal = Depends(require_web_access)):
        require_same_origin(request)
        return await call(app.state.management.delete_preview, session_id(principal))

    @app.post("/api/v1/admin/selection/delete", tags=["文件管理"])
    async def delete_selection(payload: DeleteConfirmation, request: Request, principal: Principal = Depends(require_web_access)):
        require_same_origin(request)
        return await call(app.state.management.delete_snapshot, session_id(principal), payload.snapshot_id, payload.file_count, payload.total_bytes)

    @app.post("/api/v1/admin/selection/move", tags=["文件管理"])
    async def move_selection(payload: MoveInput, request: Request, principal: Principal = Depends(require_web_access)):
        require_same_origin(request)
        return await call(app.state.management.move_snapshot, session_id(principal), payload.target_directory)

    @app.delete("/api/v1/admin/files/{file_id}", tags=["文件管理"])
    async def delete_file(file_id: str, request: Request, _=Depends(require_web_access)):
        require_same_origin(request)
        return await call(app.state.management.delete_file, file_id)

    @app.put("/api/v1/admin/files/{file_id}/name", tags=["文件管理"])
    async def rename_file(file_id: str, payload: RenameInput, request: Request, _=Depends(require_web_access)):
        require_same_origin(request)
        return await call(app.state.management.rename_file, file_id, payload.name)

    @app.post("/api/v1/admin/files/move", tags=["文件管理"])
    async def move_files(payload: BatchMoveInput, request: Request, _=Depends(require_web_access)):
        require_same_origin(request)
        return await call(app.state.management.move_files, payload.file_ids, payload.target_directory)

    @app.post("/api/v1/admin/directories", tags=["文件管理"])
    async def create_directory(payload: DirectoryInput, request: Request, _=Depends(require_web_access)):
        require_same_origin(request)
        return await call(app.state.management.create_directory, payload.parent, payload.name)

    @app.put("/api/v1/admin/directories/name", tags=["文件管理"])
    async def rename_directory(path: str, payload: RenameInput, request: Request, _=Depends(require_web_access)):
        require_same_origin(request)
        return await call(app.state.management.rename_directory, path, payload.name)

    @app.post("/api/v1/admin/directories/move", tags=["文件管理"])
    async def move_directory(path: str, payload: MoveInput, request: Request, _=Depends(require_web_access)):
        require_same_origin(request)
        return await call(app.state.management.move_directory, path, payload.target_directory)

    @app.delete("/api/v1/admin/directories", status_code=204, tags=["文件管理"])
    async def delete_directory(path: str, request: Request, _=Depends(require_web_access)):
        require_same_origin(request)
        await call(app.state.management.delete_directory, path)
        return Response(status_code=204)

    @app.post("/api/v1/admin/files/{file_id}/reprocess", status_code=202, tags=["扫描与后台任务"])
    async def reprocess(file_id: str, request: Request, _=Depends(require_web_access)):
        require_same_origin(request)
        return await call(app.state.management.reprocess, file_id)

    @app.post("/api/v1/admin/tasks/retry-failed", status_code=202, tags=["扫描与后台任务"])
    async def retry_failed(request: Request, _=Depends(require_web_access)):
        require_same_origin(request)
        return await call(app.state.management.retry_failed)

    @app.get("/api/v1/admin/logs", tags=["后台日志"])
    async def logs(request: Request, level: Annotated[list[str] | None, Query()] = None, _=Depends(require_web_access)):
        return await asyncio.to_thread(app.state.logs.read, set(level or ()), 1000)

    @app.get("/api/v1/admin/logs/archive", tags=["后台日志"])
    async def log_archive(request: Request, _=Depends(require_web_access)):
        data = await asyncio.to_thread(app.state.logs.archive)
        return Response(data, media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="dokura-logs.zip"'})
