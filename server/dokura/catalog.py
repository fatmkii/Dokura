from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import PurePosixPath

from sqlalchemy import and_, asc, column, desc, func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from dokura.metadata.models import Directory, File, FileTag, Page, Scan, Tag
from dokura.metadata.natural_sort import normalized_casefold


SORT_COLUMNS = {
    "name": File.natural_sort_key,
    "size": File.size,
    "modified": File.modified_ns,
    "rating": File.rating,
}


@dataclass(frozen=True, slots=True)
class CatalogQuery:
    path: str = ""
    page: int = 1
    per_page: int = 50
    query: str = ""
    scope: str = "current"
    tag_ids: tuple[int, ...] = ()
    tag_mode: str = "all"
    rating_min: int = 0
    rating_max: int = 5
    sort: str = "name"
    direction: str = "asc"


def normalize_catalog_path(value: str) -> str:
    value = value.replace("\\", "/").strip("/")
    path = PurePosixPath(value)
    if value and (path.is_absolute() or ".." in path.parts):
        raise ValueError("目录路径无效")
    return "" if value == "." else value


def _scope_filter(parent_column, path: str, scope: str):
    if scope == "current":
        return parent_column == path
    escaped = path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    prefix = f"{escaped}/" if escaped else ""
    return or_(parent_column == path, parent_column.like(f"{prefix}%", escape="\\"))


def _file_filters(query: CatalogQuery):
    filters = [File.present.is_(True), File.storage_unavailable.is_(False)]
    filters.append(_scope_filter(File.parent_path, query.path, query.scope))
    if query.rating_min != 0 or query.rating_max != 5:
        filters.append(File.rating.between(query.rating_min, query.rating_max))
    folded = normalized_casefold(query.query.strip())
    params: dict[str, str] = {}
    if folded:
        if len(folded) >= 3:
            candidate = select(column("file_id")).select_from(text("files_fts")).where(text("files_fts MATCH :fts_query"))
            filters.append(File.id.in_(candidate))
            params["fts_query"] = f'"{folded.replace(chr(34), chr(34) * 2)}"'
        else:
            filters.append(File.filename_casefold.contains(folded, autoescape=True))
    if query.tag_ids:
        matched = (
            select(FileTag.file_id)
            .where(FileTag.tag_id.in_(query.tag_ids))
            .group_by(FileTag.file_id)
        )
        if query.tag_mode == "all":
            matched = matched.having(func.count(func.distinct(FileTag.tag_id)) == len(set(query.tag_ids)))
        filters.append(File.id.in_(matched))
    return filters, params


def _file_order(query: CatalogQuery):
    primary = SORT_COLUMNS[query.sort]
    if query.sort == "rating" and query.direction == "desc":
        # Rated files descend first; zero remains last.
        return (asc(File.rating == 0), desc(primary), asc(File.natural_sort_key), asc(File.id))
    ordered = desc(primary) if query.direction == "desc" else asc(primary)
    return (ordered, asc(File.natural_sort_key), asc(File.id))


def _tag_map(session: Session, file_ids: list[str]) -> dict[str, list[dict[str, object]]]:
    result = {file_id: [] for file_id in file_ids}
    if not file_ids:
        return result
    rows = session.execute(
        select(FileTag.file_id, Tag.id, Tag.category, Tag.value)
        .join(Tag, Tag.id == FileTag.tag_id)
        .where(FileTag.file_id.in_(file_ids))
        .order_by(FileTag.file_id, Tag.id)
    )
    for file_id, tag_id, category, value in rows:
        result[file_id].append({"id": tag_id, "category": category, "value": value})
    return result


def _file_item(item: File, tags: list[dict[str, object]], root: str) -> dict[str, object]:
    relative = item.relative_path
    display_path = relative
    if root and relative.startswith(f"{root}/"):
        display_path = relative[len(root) + 1:]
    return {
        "kind": "file", "id": item.id, "name": item.original_filename,
        "relative_path": relative, "display_path": display_path, "size": item.size,
        "modified_ns": item.modified_ns, "rating": item.rating, "status": item.status.value,
        "cover_status": item.cover_status.value, "content_version": item.content_version,
        "tags": tags,
    }


def list_catalog(engine, query: CatalogQuery) -> dict[str, object]:
    filters, params = _file_filters(query)
    has_filter = bool(query.query.strip() or query.tag_ids or query.rating_min != 0 or query.rating_max != 5)
    include_directories = not (query.tag_ids or query.rating_min != 0 or query.rating_max != 5)
    offset = (query.page - 1) * query.per_page
    with Session(engine) as session:
        # Force a SQLite read transaction so counts, page rows, tags, and the
        # result version all describe one database state.
        session.execute(text("BEGIN"))
        directory_filters = [Directory.present.is_(True), Directory.storage_unavailable.is_(False)]
        if query.scope == "current" or not has_filter:
            directory_filters.append(Directory.parent_path == query.path)
        else:
            directory_filters.append(_scope_filter(Directory.parent_path, query.path, "recursive"))
        folded = normalized_casefold(query.query.strip())
        if folded:
            directory_filters.append(Directory.name_casefold.contains(folded, autoescape=True))

        directory_total = 0
        directories: list[Directory] = []
        if include_directories:
            directory_total = session.scalar(select(func.count()).select_from(Directory).where(*directory_filters)) or 0
            if offset < directory_total:
                directories = session.scalars(
                    select(Directory).where(*directory_filters)
                    .order_by(Directory.natural_sort_key, Directory.relative_path)
                    .offset(offset).limit(query.per_page)
                ).all()

        file_total = session.scalar(select(func.count()).select_from(File).where(*filters), params) or 0
        remaining = query.per_page - len(directories)
        file_offset = max(0, offset - directory_total)
        files = session.scalars(
            select(File).where(*filters).order_by(*_file_order(query))
            .offset(file_offset).limit(remaining), params
        ).all() if remaining else []
        tags = _tag_map(session, [item.id for item in files])
        latest_scan = session.scalar(select(Scan.id).order_by(Scan.started_at.desc()).limit(1)) or "none"
        latest_change = session.scalar(select(func.max(File.updated_at))) or "none"
        latest_rating = session.scalar(select(func.max(File.rating_updated_at))) or "none"
        total = directory_total + file_total
        version = hashlib.sha256(
            f"{latest_scan}:{latest_change}:{latest_rating}:{total}".encode()
        ).hexdigest()[:16]
        items = [
            {"kind": "directory", "name": item.name_nfc, "relative_path": item.relative_path}
            for item in directories
        ] + [_file_item(item, tags[item.id], query.path) for item in files]
        return {
            "items": items, "page": query.page, "per_page": query.per_page,
            "total": total, "pages": (total + query.per_page - 1) // query.per_page,
            "result_version": version,
        }


def matching_file_ids(engine, query: CatalogQuery) -> list[str]:
    """Return the stable UUID set used by a cross-page management snapshot."""
    filters, params = _file_filters(query)
    with Session(engine) as session:
        return list(session.scalars(select(File.id).where(*filters).order_by(File.id), params))


def tag_candidates(engine, *, path: str, scope: str, keyword: str = "") -> list[dict[str, object]]:
    folded = normalized_casefold(keyword.strip())
    with Session(engine) as session:
        statement = (
            select(Tag.id, Tag.category, Tag.value, func.count(func.distinct(File.id)).label("uses"))
            .join(FileTag, FileTag.tag_id == Tag.id)
            .join(File, File.id == FileTag.file_id)
            .where(File.present.is_(True), File.storage_unavailable.is_(False), _scope_filter(File.parent_path, path, scope))
        )
        if folded:
            statement = statement.where(Tag.value_casefold.contains(folded, autoescape=True))
        rows = session.execute(statement.group_by(Tag.id).order_by(Tag.category, desc("uses"), Tag.value_casefold)).all()
    limits: dict[str, int] = {}
    maximum = 50 if folded else 20
    result = []
    for tag_id, category, value, uses in rows:
        if limits.get(category, 0) >= maximum:
            continue
        limits[category] = limits.get(category, 0) + 1
        result.append({"id": tag_id, "category": category, "value": value, "count": uses})
    return result


def file_detail(engine, file_id: str) -> dict[str, object] | None:
    with Session(engine) as session:
        item = session.scalar(
            select(File).options(selectinload(File.pages)).where(
                File.id == file_id, File.present.is_(True), File.storage_unavailable.is_(False)
            )
        )
        if item is None:
            return None
        tags = _tag_map(session, [file_id])[file_id]
        unavailable = sum(1 for page in item.pages if page.unavailable)
        return {
            **_file_item(item, tags, ""), "title": item.title, "event": item.event,
            "creator_raw": item.creator_raw, "circle": item.circle, "translated": item.translated,
            "parser_version": item.parser_version, "parse_confidence": item.parse_confidence,
            "parse_warnings": json.loads(item.parse_warnings_json),
            "unclassified_tags": json.loads(item.unclassified_tags_json),
            "last_error": item.last_error, "device": item.device, "inode": item.inode,
            "created_at": item.created_at, "updated_at": item.updated_at,
            "page_count": len(item.pages), "unavailable_page_count": unavailable,
            "pages": [{"number": page.page_number, "unavailable": page.unavailable, "unavailable_reason": page.unavailable_reason} for page in sorted(item.pages, key=lambda page: page.page_number)],
            "rating_updated_at": item.rating_updated_at,
        }
