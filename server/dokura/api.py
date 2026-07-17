from __future__ import annotations

import asyncio
from datetime import UTC
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from dokura.catalog import CatalogQuery, file_detail, list_catalog, normalize_catalog_path, tag_candidates
from dokura.images import ImageBusyError, ImageService, PREVIEW_SIZES, image_etag
from dokura.metadata.zip_analyzer import DeterministicPageError, TemporaryReadError
from dokura.metadata.models import File, utc_now
from dokura.security import SESSION_COOKIE, AuthService, Principal, require_read_access, require_same_origin, require_web_access, validate_new_password


class LoginInput(BaseModel):
    username: str
    password: str


class PasswordInput(BaseModel):
    current_password: str
    new_password: str
    new_password_confirmation: str


class ApiKeyInput(BaseModel):
    current_password: str
    confirmed: bool


class RatingInput(BaseModel):
    rating: int = Field(ge=0, le=5)


def _path(value: str) -> str:
    try:
        return normalize_catalog_path(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _client_id(request: Request) -> str:
    return request.headers.get("X-Dokura-Client-ID") or (request.client.host if request.client else "unknown")


def install_stage3_api(app: FastAPI) -> None:
    class _StateProxy:
        def __init__(self, name: str) -> None:
            self.name = name

        def __getattr__(self, name: str):
            return getattr(getattr(app.state, self.name), name)

    auth = _StateProxy("auth")
    images = _StateProxy("images")

    @app.post("/api/v1/auth/login", tags=["鉴权"])
    async def login(payload: LoginInput, request: Request, response: Response) -> dict[str, object]:
        source = request.client.host if request.client else "unknown"
        token, session = await asyncio.to_thread(auth.login, payload.username, payload.password, source)
        response.set_cookie(
            SESSION_COOKIE, token, httponly=True, samesite="strict", path="/",
            max_age=7 * 24 * 60 * 60,
        )
        return {"username": "admin", "default_password": payload.password == "admin", "expires_at": session.expires_at}

    @app.get("/api/v1/auth/session", tags=["鉴权"], dependencies=[Depends(require_web_access)])
    async def session_status(request: Request) -> dict[str, str]:
        return {"username": "admin", "principal": "web"}

    @app.post("/api/v1/auth/logout", status_code=204, tags=["鉴权"])
    async def logout(request: Request, response: Response, principal: Principal = Depends(require_web_access)) -> Response:
        require_same_origin(request)
        if principal.session_id and hasattr(app.state, "management"):
            await asyncio.to_thread(app.state.management.release_snapshot, principal.session_id)
        await asyncio.to_thread(auth.revoke, principal.session_id)
        response.delete_cookie(SESSION_COOKIE, path="/")
        response.status_code = 204
        return response

    @app.put("/api/v1/admin/password", status_code=204, tags=["鉴权"], dependencies=[Depends(require_web_access)])
    async def change_password(payload: PasswordInput, request: Request, response: Response) -> Response:
        require_same_origin(request)
        source = request.client.host if request.client else "unknown"
        await asyncio.to_thread(auth.check_current_password, payload.current_password, source)
        if payload.new_password != payload.new_password_confirmation:
            raise HTTPException(status_code=422, detail="两次输入的新密码不一致")
        validate_new_password(payload.current_password, payload.new_password)
        await asyncio.to_thread(auth.credentials.set_password, payload.new_password)
        await asyncio.to_thread(auth.revoke_all)
        response.delete_cookie(SESSION_COOKIE, path="/")
        response.status_code = 204
        return response

    @app.get("/api/v1/admin/api-key", tags=["鉴权"], dependencies=[Depends(require_web_access)])
    async def api_key_status(request: Request) -> dict[str, str]:
        return {"suffix": auth.credentials.api_key_suffix}

    @app.post("/api/v1/admin/api-key", tags=["鉴权"], dependencies=[Depends(require_web_access)])
    async def rotate_api_key(payload: ApiKeyInput, request: Request) -> dict[str, str]:
        require_same_origin(request)
        if not payload.confirmed:
            raise HTTPException(status_code=422, detail="需要确认所有 Android 客户端均需重新配置")
        source = request.client.host if request.client else "unknown"
        await asyncio.to_thread(auth.check_current_password, payload.current_password, source)
        key, suffix = await asyncio.to_thread(auth.credentials.rotate_api_key)
        return {"api_key": key, "suffix": suffix}

    @app.get("/api/v1/catalog", tags=["目录与文件"], dependencies=[Depends(require_read_access)])
    async def catalog(
        request: Request, path: str = "", page: int = Query(1, ge=1),
        per_page: int = Query(50, ge=1, le=200), query: str = "",
        scope: Literal["current", "recursive"] = "current",
        tag_id: Annotated[list[int] | None, Query()] = None,
        tag_mode: Literal["all", "any"] = "all", rating_min: int = Query(0, ge=0, le=5),
        rating_max: int = Query(5, ge=0, le=5),
        sort: Literal["name", "size", "modified", "rating"] = "name",
        direction: Literal["asc", "desc"] = "asc",
    ) -> dict[str, object]:
        if rating_min > rating_max:
            raise HTTPException(status_code=422, detail="评分下限不能大于上限")
        options = CatalogQuery(_path(path), page, per_page, query, scope, tuple(tag_id or ()), tag_mode, rating_min, rating_max, sort, direction)
        return await asyncio.to_thread(list_catalog, app.state.database_engine, options)

    @app.get("/api/v1/tags", tags=["目录与文件"], dependencies=[Depends(require_read_access)])
    async def tags(request: Request, path: str = "", scope: Literal["current", "recursive"] = "current", query: str = "") -> dict[str, object]:
        items = await asyncio.to_thread(tag_candidates, app.state.database_engine, path=_path(path), scope=scope, keyword=query)
        return {"items": items}

    @app.get("/api/v1/files/{file_id}", tags=["目录与文件"], dependencies=[Depends(require_read_access)])
    async def detail(file_id: str, request: Request) -> dict[str, object]:
        result = await asyncio.to_thread(file_detail, app.state.database_engine, file_id)
        if result is None:
            raise HTTPException(status_code=404, detail="文件不存在")
        cover_record = await asyncio.to_thread(images.cover_record, file_id)
        try:
            result["cover_cache_bytes"] = cover_record[0].stat().st_size if cover_record else 0
        except OSError:
            result["cover_cache_bytes"] = 0
        return result

    @app.put("/api/v1/files/{file_id}/rating", tags=["目录与文件"], dependencies=[Depends(require_read_access)])
    async def set_rating(file_id: str, payload: RatingInput, request: Request) -> dict[str, object]:
        with app.state.writer.transaction() as database:
            item = database.scalar(select(File).where(File.id == file_id, File.present.is_(True)))
            if item is None:
                raise HTTPException(status_code=404, detail="文件不存在")
            if item.rating != payload.rating or item.rating_updated_at is None:
                item.rating = payload.rating
                item.rating_updated_at = utc_now()
            value, changed = item.rating, item.rating_updated_at
        if changed is not None and changed.tzinfo is None:
            changed = changed.replace(tzinfo=UTC)
        return {"id": file_id, "rating": value, "updated_at": changed}

    @app.get("/api/v1/files/{file_id}/cover", tags=["图片"], dependencies=[Depends(require_read_access)])
    async def cover(file_id: str, request: Request):
        record = await asyncio.to_thread(images.cover_record, file_id)
        if record is None:
            raise HTTPException(status_code=404, detail="封面不存在")
        path, version = record
        etag = image_etag(file_id, version, "cover")
        if request.headers.get("If-None-Match") == etag:
            return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "private, max-age=31536000, immutable"})
        return FileResponse(path, media_type="image/jpeg", headers={"ETag": etag, "Cache-Control": "private, max-age=31536000, immutable", "Accept-Ranges": "bytes"})

    @app.get("/api/v1/files/{file_id}/pages/{page_number}/preview", tags=["图片"], dependencies=[Depends(require_read_access)])
    async def preview(file_id: str, page_number: int, request: Request, size: int = Query(...), purpose: Literal["preview"] = "preview"):
        if size not in PREVIEW_SIZES:
            raise HTTPException(status_code=422, detail="预览尺寸只支持 256、512 或 768")
        try:
            record = await asyncio.to_thread(images.page_record, file_id, page_number)
        except TemporaryReadError as exc:
            raise HTTPException(status_code=409, detail="文件内容已经变化，请刷新详情") from exc
        if record is None:
            raise HTTPException(status_code=404, detail="文件或页面不存在")
        if record.unavailable:
            raise HTTPException(status_code=410, detail="页面不可用")
        etag = image_etag(file_id, record.content_version, page_number, size)
        if request.headers.get("If-None-Match") == etag:
            return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "private, max-age=31536000, immutable"})
        try:
            data = await images.preview(record, size, _client_id(request))
        except ImageBusyError as exc:
            raise HTTPException(status_code=503, detail="图片服务繁忙", headers={"Retry-After": "1"}) from exc
        except DeterministicPageError as exc:
            raise HTTPException(status_code=410, detail="页面不可用") from exc
        except TemporaryReadError as exc:
            raise HTTPException(status_code=503, detail="图片暂时无法读取", headers={"Retry-After": "1"}) from exc
        return Response(data, media_type="image/jpeg", headers={"ETag": etag, "Cache-Control": "private, max-age=31536000, immutable"})

    @app.get("/api/v1/files/{file_id}/pages/{page_number}/original", tags=["图片"], dependencies=[Depends(require_read_access)])
    async def original(file_id: str, page_number: int, request: Request, purpose: Literal["current", "prefetch"]):
        try:
            record = await asyncio.to_thread(images.page_record, file_id, page_number)
        except TemporaryReadError as exc:
            raise HTTPException(status_code=409, detail="文件内容已经变化，请刷新详情") from exc
        if record is None:
            raise HTTPException(status_code=404, detail="文件或页面不存在")
        if record.unavailable:
            raise HTTPException(status_code=410, detail="页面不可用")
        etag = image_etag(file_id, record.content_version, page_number, "original")
        if request.headers.get("If-None-Match") == etag:
            return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "private, max-age=31536000, immutable"})
        operation_lock = None
        try:
            if images.operation_locks is not None:
                operation_lock = await asyncio.to_thread(images.operation_locks.acquire, file_id, 5)
            await asyncio.to_thread(images.validate_original_header, record)
        except DeterministicPageError as exc:
            await asyncio.to_thread(images.mark_unavailable, record, exc.code)
            if operation_lock is not None:
                operation_lock.release()
            raise HTTPException(status_code=410, detail="页面不可用") from exc
        except TemporaryReadError as exc:
            if operation_lock is not None:
                operation_lock.release()
            raise HTTPException(status_code=503, detail="图片暂时无法读取", headers={"Retry-After": "1"}) from exc
        except Exception:
            if operation_lock is not None:
                operation_lock.release()
            raise
        media_type = "image/png" if Path(record.entry_name).suffix.casefold() == ".png" else "image/jpeg"
        try:
            await images.scheduler.acquire(purpose, _client_id(request))
        except ImageBusyError as exc:
            if operation_lock is not None:
                operation_lock.release()
            raise HTTPException(status_code=503, detail="图片服务繁忙", headers={"Retry-After": "1"}) from exc
        stream = images.original_stream(record, purpose, _client_id(request), admitted=True, operation_lock=operation_lock)
        return StreamingResponse(stream, media_type=media_type, headers={"ETag": etag, "Cache-Control": "private, max-age=31536000, immutable"})
