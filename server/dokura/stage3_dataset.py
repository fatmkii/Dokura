from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

from dokura.metadata.database import create_database_engine
from dokura.metadata.migrations import upgrade_database
from dokura.metadata.natural_sort import natural_sort_bytes, normalized_casefold


EMPTY_ZIP = b"PK\x05\x06" + b"\x00" * 18


def generate(path: Path, count: int, content_dir: Path | None = None) -> dict[str, object]:
    """Generate the fixed representative data set used by stages 3 and 9.

    Stage 9 may request a matching filesystem tree. Its tiny valid ZIP files are
    only scan fixtures; representative image throughput is measured separately
    against real Content ZIPs.
    """
    upgrade_database(path)
    engine = create_database_engine(path)
    now = datetime.now(UTC).replace(tzinfo=None).isoformat(" ")
    if content_dir is not None:
        content_dir.mkdir(parents=True, exist_ok=True)
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO tags(id,category,value,value_casefold) VALUES "
                + ",".join(f"({index + 1},'artist','作者{index:02d}','作者{index:02d}')" for index in range(30))
            ))
            connection.exec_driver_sql(
                "INSERT INTO directories(relative_path,parent_path,name_nfc,name_casefold,natural_sort_key,present,storage_unavailable) VALUES(?,?,?,?,?,?,?)",
                [(f"目录{index:03d}", "", f"目录{index:03d}", normalized_casefold(f"目录{index:03d}"), natural_sort_bytes(f"目录{index:03d}"), 1, 0) for index in range(100)],
            )
            sql = (
                "INSERT INTO files(id,relative_path,parent_path,original_filename,filename_nfc,filename_casefold,natural_sort_key,"
                "device,inode,size,modified_ns,content_version,status,cover_status,cover_path,title,title_casefold,event,creator_raw,circle,translated,"
                "parser_version,parse_confidence,field_confidence_json,parse_warnings_json,unclassified_tags_json,last_error,rating,rating_updated_at,"
                "present,storage_unavailable,deleted_at,last_seen_scan_id,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            )
            tag_sql = "INSERT INTO file_tags(file_id,tag_id) VALUES(?,?)"
            for start in range(0, count, 5000):
                rows = []
                tag_rows = []
                for index in range(start, min(start + 5000, count)):
                    file_id = f"{index:08x}-0000-4000-8000-{index:012x}"
                    parent = f"目录{index % 100:03d}"
                    name = f"作品 {index:06d} Café.zip"
                    relative = f"{parent}/{name}"
                    if content_dir is None:
                        device, inode = 1, index + 1
                    else:
                        zip_path = content_dir / relative
                        zip_path.parent.mkdir(exist_ok=True)
                        if not zip_path.exists():
                            zip_path.write_bytes(EMPTY_ZIP)
                        info = zip_path.stat()
                        device, inode = info.st_dev, info.st_ino
                    rows.append((
                        file_id, relative, parent, name, name, normalized_casefold(name), natural_sort_bytes(name),
                        device, inode,
                        (content_dir / relative).stat().st_size if content_dir is not None else 10_000 + index * 31,
                        (content_dir / relative).stat().st_mtime_ns if content_dir is not None else 1_700_000_000_000_000_000 + index,
                        f"version-{index}", "ready", "complete", None, name[:-4], normalized_casefold(name[:-4]),
                        None, None, None, None, 1, 1.0, "{}", "[]", "[]", None, index % 6, now,
                        1, 0, None, None, now, now,
                    ))
                    tag_rows.append((file_id, index % 30 + 1))
                    if index % 7 == 0:
                        tag_rows.append((file_id, (index + 11) % 30 + 1))
                connection.exec_driver_sql(sql, rows)
                connection.exec_driver_sql(tag_sql, tag_rows)

            plans = {
                "parent_name": connection.exec_driver_sql(
                    "EXPLAIN QUERY PLAN SELECT id FROM files WHERE present=1 AND storage_unavailable=0 AND parent_path=? ORDER BY natural_sort_key,id LIMIT 50",
                    ("目录001",),
                ).fetchall(),
                "parent_rating": connection.exec_driver_sql(
                    "EXPLAIN QUERY PLAN SELECT id FROM files WHERE present=1 AND storage_unavailable=0 AND parent_path=? AND rating BETWEEN 3 AND 5 ORDER BY rating,natural_sort_key,id LIMIT 50",
                    ("目录001",),
                ).fetchall(),
                "tag_join": connection.exec_driver_sql(
                    "EXPLAIN QUERY PLAN SELECT file_id FROM file_tags WHERE tag_id=? ORDER BY file_id LIMIT 50", (1,)
                ).fetchall(),
                "fts": connection.exec_driver_sql(
                    "EXPLAIN QUERY PLAN SELECT file_id FROM files_fts WHERE files_fts MATCH ? LIMIT 50", ('"café"',)
                ).fetchall(),
            }
        rendered = {key: " | ".join(str(row) for row in rows) for key, rows in plans.items()}
        required = {
            "parent_name": "ix_files_parent_name",
            "parent_rating": "ix_files_parent_rating",
            "tag_join": "ix_file_tags_tag_file",
            "fts": "VIRTUAL TABLE INDEX",
        }
        missing = {key: value for key, value in required.items() if value not in rendered[key]}
        if missing:
            raise RuntimeError(f"查询计划未使用目标索引: {missing}; plans={rendered}")
        manifest = hashlib.sha256(
            f"dokura-representative-v1:{count}:100:30".encode()
        ).hexdigest()
        return {
            "records": count, "database_bytes": path.stat().st_size,
            "filesystem_fixtures": count if content_dir is not None else 0,
            "dataset_manifest_sha256": manifest, "query_plans": rendered,
        }
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="生成阶段 3 代表性元数据并验证查询计划")
    parser.add_argument("--count", type=int, default=100_000)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--content-dir", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count 必须大于 0")
    temporary = None
    path = args.database
    if path is None:
        temporary = tempfile.TemporaryDirectory(prefix="dokura-stage3-")
        path = Path(temporary.name) / "metadata.sqlite3"
    result = generate(path, args.count, args.content_dir)
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)
    if temporary:
        temporary.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
