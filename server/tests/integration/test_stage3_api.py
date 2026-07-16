import io
import zipfile
from pathlib import Path
from time import monotonic, sleep

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text

from dokura.main import create_app
from dokura.metadata.analysis_service import FileSnapshot
from dokura.metadata.models import AnalysisStatus, CoverStatus, Directory, File, FileTag, Page, Tag
from dokura.metadata.natural_sort import natural_sort_bytes, normalized_casefold
from dokura.sqlite_check import SQLiteCapabilities
from dokura.reset_password import main as reset_password


ORIGIN = {"Origin": "http://testserver"}


def passing_sqlite_check() -> SQLiteCapabilities:
    return SQLiteCapabilities(version="3.51.3", fts5_trigram=True)


def jpeg(size=(900, 600), color="navy") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, "JPEG", quality=92)
    return output.getvalue()


def wait_for_scan(client: TestClient) -> None:
    deadline = monotonic() + 3
    while monotonic() < deadline:
        status = client.get("/api/v1/admin/scan").json().get("status")
        if status in {"completed", "partial", "failed"}:
            return
        sleep(0.01)


def login(client: TestClient, password="admin") -> None:
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": password})
    assert response.status_code == 200


def seed(app, settings, name: str, *, rating: int, tag_value: str, color: str) -> tuple[str, bytes]:
    relative = f"子目录/{name}"
    archive_path = settings.content_dir / relative
    archive_path.parent.mkdir(exist_ok=True)
    page_bytes = jpeg(color=color)
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("001.jpg", page_bytes)
    stat = archive_path.stat()
    content_version = FileSnapshot.read(archive_path).content_version
    file_id = f"00000000-0000-0000-0000-{rating + 1:012d}"
    cover = settings.cover_dir / f"{content_version}.jpg"
    cover.parent.mkdir(parents=True, exist_ok=True)
    cover.write_bytes(jpeg((720, 480), color))
    with app.state.writer.transaction() as session:
        if session.get(Directory, "子目录") is None:
            session.add(Directory(
                relative_path="子目录", parent_path="", name_nfc="子目录",
                name_casefold=normalized_casefold("子目录"), natural_sort_key=natural_sort_bytes("子目录"),
                present=True, storage_unavailable=False,
            ))
        item = File(
            id=file_id, relative_path=relative, parent_path="子目录", original_filename=name,
            filename_nfc=name, filename_casefold=normalized_casefold(name),
            natural_sort_key=natural_sort_bytes(relative), device=stat.st_dev, inode=stat.st_ino,
            size=stat.st_size, modified_ns=stat.st_mtime_ns, content_version=content_version,
            status=AnalysisStatus.READY, cover_status=CoverStatus.COMPLETE,
            cover_path=f"covers/{cover.name}", title=Path(name).stem,
            title_casefold=normalized_casefold(Path(name).stem), parser_version=1,
            parse_confidence=1.0, field_confidence_json="{}", parse_warnings_json="[]",
            unclassified_tags_json="[]", rating=rating, present=True, storage_unavailable=False,
        )
        session.add(item)
        session.flush()
        tag = session.query(Tag).filter_by(category="artist", value=tag_value).one_or_none()
        if tag is None:
            tag = Tag(category="artist", value=tag_value, value_casefold=normalized_casefold(tag_value))
            session.add(tag)
            session.flush()
        session.add(FileTag(file_id=file_id, tag_id=tag.id))
        session.add(Page(file_id=file_id, page_number=1, entry_name="001.jpg", uncompressed_size=len(page_bytes), crc32=0))
    return file_id, page_bytes


def test_auth_permissions_rotation_and_password_lifecycle(settings, caplog) -> None:
    app = create_app(settings=settings, sqlite_check=passing_sqlite_check)
    with TestClient(app) as client:
        assert client.get("/api/v1/catalog").status_code == 401
        login(client)
        assert client.get("/api/v1/admin/scan").status_code == 200
        assert client.post("/api/v1/admin/scan").status_code == 403

        rotated = client.post(
            "/api/v1/admin/api-key", headers=ORIGIN,
            json={"current_password": "admin", "confirmed": True},
        )
        assert rotated.status_code == 200
        key = rotated.json()["api_key"]
        credentials_text = (settings.config_dir / "credentials.json").read_text(encoding="utf-8")
        assert key not in credentials_text
        assert key not in str(app.openapi())
        bearer = {"Authorization": f"Bearer {key}"}
        assert client.get("/api/v1/catalog", headers=bearer).status_code == 200
        assert client.get("/api/v1/admin/scan", headers=bearer).status_code == 401
        new_key = client.post(
            "/api/v1/admin/api-key", headers=ORIGIN,
            json={"current_password": "admin", "confirmed": True},
        ).json()["api_key"]
        assert client.get("/api/v1/catalog", headers=bearer).status_code == 401
        new_bearer = {"Authorization": f"Bearer {new_key}"}
        assert client.get("/api/v1/catalog", headers=new_bearer).status_code == 200
        invalid = client.get("/api/v1/catalog", headers=new_bearer, params={"rating_min": 5, "rating_max": 1})
        assert new_key not in invalid.text
        assert new_key not in str(invalid.request.url)
        assert new_key not in caplog.text

        changed = client.put(
            "/api/v1/admin/password", headers=ORIGIN,
            json={"current_password": "admin", "new_password": "一条足够长的新密码", "new_password_confirmation": "一条足够长的新密码"},
        )
        assert changed.status_code == 204
        assert client.get("/api/v1/auth/session").status_code == 401
        login(client, "一条足够长的新密码")
        assert client.get("/api/v1/catalog", headers=new_bearer).status_code == 200


def test_login_is_limited_by_source_and_does_not_reveal_account(settings) -> None:
    with TestClient(create_app(settings=settings, sqlite_check=passing_sqlite_check)) as client:
        statuses = [
            client.post("/api/v1/auth/login", json={"username": "nobody", "password": "wrong"}).status_code
            for _ in range(5)
        ]
        assert statuses[:4] == [401] * 4
        assert statuses[4] == 429
        response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin"})
        assert response.status_code == 429
        assert response.headers["Retry-After"]


def test_catalog_search_filters_pagination_rating_and_query_plans(settings) -> None:
    app = create_app(settings=settings, sqlite_check=passing_sqlite_check)
    with TestClient(app) as client:
        login(client)
        wait_for_scan(client)
        first_id, _ = seed(app, settings, "Café 2.zip", rating=0, tag_value="作者甲", color="red")
        seed(app, settings, "CAFÉ 10.zip", rating=4, tag_value="作者甲", color="green")
        seed(app, settings, "别册 3.zip", rating=5, tag_value="作者乙", color="blue")

        one = client.get("/api/v1/catalog", params={"path": "子目录", "query": "é"}).json()
        trigram = client.get("/api/v1/catalog", params={"path": "子目录", "query": "CAFE\u0301"}).json()
        assert one["total"] == trigram["total"] == 2
        assert [item["name"] for item in trigram["items"]] == ["Café 2.zip", "CAFÉ 10.zip"]

        candidates = client.get("/api/v1/tags", params={"path": "子目录"}).json()["items"]
        author = next(item for item in candidates if item["value"] == "作者甲")
        filtered = client.get("/api/v1/catalog", params={
            "path": "子目录", "tag_id": author["id"], "rating_min": 0,
            "rating_max": 4, "sort": "rating", "direction": "desc", "per_page": 1,
        }).json()
        assert filtered["total"] == 2
        assert filtered["items"][0]["rating"] == 4
        version = filtered["result_version"]

        first = client.put(f"/api/v1/files/{first_id}/rating", json={"rating": 3}).json()
        second = client.put(f"/api/v1/files/{first_id}/rating", json={"rating": 3}).json()
        assert first == second
        assert client.get(f"/api/v1/files/{first_id}").json()["rating"] == 3
        refreshed = client.get("/api/v1/catalog", params={
            "path": "子目录", "tag_id": author["id"], "rating_min": 0,
            "rating_max": 4, "sort": "rating", "direction": "desc", "per_page": 1,
        }).json()["result_version"]
        assert version != refreshed

        with app.state.database_engine.connect() as connection:
            parent_plan = " ".join(str(row) for row in connection.execute(text(
                "EXPLAIN QUERY PLAN SELECT id FROM files WHERE present=1 AND storage_unavailable=0 AND parent_path='子目录' ORDER BY natural_sort_key,id LIMIT 50"
            )))
            fts_plan = " ".join(str(row) for row in connection.execute(text(
                "EXPLAIN QUERY PLAN SELECT file_id FROM files_fts WHERE files_fts MATCH '\"café\"'"
            )))
        assert "ix_files_parent_name" in parent_plan
        assert "VIRTUAL TABLE INDEX" in fts_plan


def test_image_http_semantics_and_versioned_previews(settings, monkeypatch) -> None:
    app = create_app(settings=settings, sqlite_check=passing_sqlite_check)
    with TestClient(app) as client:
        login(client)
        wait_for_scan(client)
        file_id, original = seed(app, settings, "图片.zip", rating=1, tag_value="作者", color="purple")

        cover = client.get(f"/api/v1/files/{file_id}/cover")
        assert cover.status_code == 200
        assert client.get(f"/api/v1/files/{file_id}/cover", headers={"If-None-Match": cover.headers["etag"]}).status_code == 304
        ranged = client.get(f"/api/v1/files/{file_id}/cover", headers={"Range": "bytes=0-99"})
        assert ranged.status_code == 206
        assert len(ranged.content) == 100

        preview = client.get(f"/api/v1/files/{file_id}/pages/1/preview", params={"size": 256, "purpose": "preview"})
        assert preview.status_code == 200
        assert preview.headers["content-type"] == "image/jpeg"
        with Image.open(io.BytesIO(preview.content)) as image:
            assert max(image.size) == 256
            preview_quantization = image.quantization
        expected_buffer = io.BytesIO()
        Image.new("RGB", (8, 8)).save(expected_buffer, "JPEG", quality=80)
        with Image.open(io.BytesIO(expected_buffer.getvalue())) as expected:
            assert preview_quantization == expected.quantization
        assert client.get(
            f"/api/v1/files/{file_id}/pages/1/preview",
            params={"size": 256, "purpose": "preview"}, headers={"If-None-Match": preview.headers["etag"]},
        ).status_code == 304
        assert client.get(f"/api/v1/files/{file_id}/pages/1/preview", params={"size": 300}).status_code == 422

        response = client.get(f"/api/v1/files/{file_id}/pages/1/original", params={"purpose": "current"})
        assert response.status_code == 200
        assert response.content == original
        assert response.headers["etag"] != preview.headers["etag"]

        async def busy(*_args, **_kwargs):
            raise ImageBusyError

        from dokura.images import ImageBusyError
        with monkeypatch.context() as patch:
            patch.setattr(app.state.images.scheduler, "acquire", busy)
            overloaded = client.get(
                f"/api/v1/files/{file_id}/pages/1/preview", params={"size": 512, "purpose": "preview"}
            )
        assert overloaded.status_code == 503
        assert overloaded.headers["Retry-After"] == "1"

        archive_path = settings.content_dir / "子目录/图片.zip"
        replacement = jpeg(color="orange")
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("001.jpg", replacement)
        snapshot = FileSnapshot.read(archive_path)
        with app.state.writer.transaction() as session:
            item = session.get(File, file_id)
            item.device, item.inode, item.size, item.modified_ns = snapshot.device, snapshot.inode, snapshot.size, snapshot.modified_ns
            item.content_version = snapshot.content_version
        changed = client.get(f"/api/v1/files/{file_id}/pages/1/preview", params={"size": 256, "purpose": "preview"})
        assert changed.status_code == 200
        assert changed.headers["etag"] != preview.headers["etag"]
        assert changed.content != preview.content

        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("001.jpg", b"not an image")
        snapshot = FileSnapshot.read(archive_path)
        with app.state.writer.transaction() as session:
            item = session.get(File, file_id)
            item.device, item.inode, item.size, item.modified_ns = snapshot.device, snapshot.inode, snapshot.size, snapshot.modified_ns
            item.content_version = snapshot.content_version
        unavailable = client.get(f"/api/v1/files/{file_id}/pages/1/preview", params={"size": 768, "purpose": "preview"})
        assert unavailable.status_code == 410
        detail = client.get(f"/api/v1/files/{file_id}").json()
        assert detail["pages"][0]["unavailable"] is True
        assert detail["status"] == "no_valid_content"


def test_docker_password_reset_revokes_sessions_but_keeps_api_key(settings, monkeypatch) -> None:
    app = create_app(settings=settings, sqlite_check=passing_sqlite_check)
    with TestClient(app) as client:
        login(client)
        old_cookie = client.cookies.get("dokura_session")
        rotated = client.post(
            "/api/v1/admin/api-key", headers=ORIGIN,
            json={"current_password": "admin", "confirmed": True},
        ).json()["api_key"]

    monkeypatch.setenv("DOKURA_CONTENT_DIR", str(settings.content_dir))
    monkeypatch.setenv("DOKURA_METADATA_DIR", str(settings.metadata_dir))
    monkeypatch.setenv("DOKURA_CONFIG_DIR", str(settings.config_dir))
    monkeypatch.setattr("sys.argv", ["dokura-reset-password", "--password", "reset-password-123"])
    assert reset_password() == 0

    with TestClient(create_app(settings=settings, sqlite_check=passing_sqlite_check)) as client:
        assert client.get("/api/v1/auth/session", headers={"Cookie": f"dokura_session={old_cookie}"}).status_code == 401
        login(client, "reset-password-123")
        assert client.get("/api/v1/catalog", headers={"Authorization": f"Bearer {rotated}"}).status_code == 200
