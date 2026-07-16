"""stage 3 catalog, search, and authentication

Revision ID: 43d1a9b0c7ef
Revises: 9bc218db86e1
"""
from pathlib import PurePosixPath
from typing import Sequence, Union
import re
import unicodedata

from alembic import op
import sqlalchemy as sa


revision: str = "43d1a9b0c7ef"
down_revision: Union[str, Sequence[str], None] = "9bc218db86e1"
branch_labels = None
depends_on = None


def _fold(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _natural_sort_bytes(value: str) -> bytes:
    encoded = bytearray()
    for piece in re.split(r"(\d+)", _fold(value)):
        if not piece:
            continue
        if piece.isdigit():
            number = piece.lstrip("0") or "0"
            encoded.extend(b"N")
            encoded.extend(len(number).to_bytes(4, "big"))
            encoded.extend(number.encode("ascii"))
        else:
            encoded.extend(b"T")
            encoded.extend(piece.encode("utf-8"))
            encoded.append(0)
    encoded.extend(b"\xfe")
    encoded.extend(value.encode("utf-8"))
    encoded.extend(b"\x00\xff")
    return bytes(encoded)


def upgrade() -> None:
    with op.batch_alter_table("files") as batch:
        batch.add_column(sa.Column("parent_path", sa.Text(), nullable=True))
        batch.add_column(sa.Column("rating_updated_at", sa.DateTime(), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, relative_path FROM files")).all()
    for file_id, relative_path in rows:
        parent = PurePosixPath(relative_path).parent.as_posix()
        connection.execute(
            sa.text("UPDATE files SET parent_path=:parent WHERE id=:id"),
            {"parent": "" if parent == "." else parent, "id": file_id},
        )

    with op.batch_alter_table("files") as batch:
        batch.alter_column("parent_path", existing_type=sa.Text(), nullable=False)
        batch.create_index("ix_files_parent_path", ["parent_path"])
        batch.create_index("ix_files_parent_name", ["present", "storage_unavailable", "parent_path", "natural_sort_key", "id"])
        batch.create_index("ix_files_parent_rating", ["present", "storage_unavailable", "parent_path", "rating", "natural_sort_key", "id"])
        batch.create_index("ix_files_parent_size", ["present", "storage_unavailable", "parent_path", "size", "natural_sort_key", "id"])
        batch.create_index("ix_files_parent_modified", ["present", "storage_unavailable", "parent_path", "modified_ns", "natural_sort_key", "id"])

    with op.batch_alter_table("file_tags") as batch:
        batch.create_index("ix_file_tags_tag_file", ["tag_id", "file_id"])

    duplicate_groups = connection.execute(sa.text(
        "SELECT category,value_casefold,MIN(id) AS keep_id FROM tags GROUP BY category,value_casefold HAVING COUNT(*) > 1"
    )).all()
    for category, value_casefold, keep_id in duplicate_groups:
        duplicate_ids = [row[0] for row in connection.execute(sa.text(
            "SELECT id FROM tags WHERE category=:category AND value_casefold=:value AND id<>:keep"
        ), {"category": category, "value": value_casefold, "keep": keep_id})]
        for duplicate_id in duplicate_ids:
            connection.execute(sa.text(
                "INSERT OR IGNORE INTO file_tags(file_id,tag_id) SELECT file_id,:keep FROM file_tags WHERE tag_id=:duplicate"
            ), {"keep": keep_id, "duplicate": duplicate_id})
            connection.execute(sa.text("DELETE FROM tags WHERE id=:id"), {"id": duplicate_id})
    op.create_index("uq_tags_category_value_casefold", "tags", ["category", "value_casefold"], unique=True)

    op.create_table(
        "directories",
        sa.Column("relative_path", sa.Text(), primary_key=True),
        sa.Column("parent_path", sa.Text(), nullable=False),
        sa.Column("name_nfc", sa.Text(), nullable=False),
        sa.Column("name_casefold", sa.Text(), nullable=False),
        sa.Column("natural_sort_key", sa.LargeBinary(), nullable=False),
        sa.Column("present", sa.Boolean(), nullable=False),
        sa.Column("storage_unavailable", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_directories_parent_path", "directories", ["parent_path"])
    op.create_index("ix_directories_parent_name", "directories", ["present", "storage_unavailable", "parent_path", "natural_sort_key", "relative_path"])

    seen: set[str] = set()
    for _file_id, relative_path in rows:
        parent = PurePosixPath(relative_path).parent
        parts = parent.parts if parent.as_posix() != "." else ()
        for index in range(1, len(parts) + 1):
            path = PurePosixPath(*parts[:index]).as_posix()
            if path in seen:
                continue
            seen.add(path)
            parent_path = PurePosixPath(path).parent.as_posix()
            name = PurePosixPath(path).name
            connection.execute(sa.text(
                "INSERT INTO directories(relative_path,parent_path,name_nfc,name_casefold,natural_sort_key,present,storage_unavailable) "
                "VALUES(:path,:parent,:name,:fold,:sort_key,1,0)"
            ), {"path": path, "parent": "" if parent_path == "." else parent_path, "name": unicodedata.normalize("NFC", name), "fold": _fold(name), "sort_key": _natural_sort_bytes(name)})

    op.execute("CREATE VIRTUAL TABLE files_fts USING fts5(file_id UNINDEXED, filename_casefold, tokenize='trigram')")
    op.execute("INSERT INTO files_fts(file_id, filename_casefold) SELECT id, filename_casefold FROM files")
    op.execute("CREATE TRIGGER files_fts_insert AFTER INSERT ON files BEGIN INSERT INTO files_fts(file_id, filename_casefold) VALUES(new.id,new.filename_casefold); END")
    op.execute("CREATE TRIGGER files_fts_delete AFTER DELETE ON files BEGIN DELETE FROM files_fts WHERE file_id=old.id; END")
    op.execute("CREATE TRIGGER files_fts_update AFTER UPDATE OF filename_casefold ON files BEGIN DELETE FROM files_fts WHERE file_id=old.id; INSERT INTO files_fts(file_id,filename_casefold) VALUES(new.id,new.filename_casefold); END")

    with op.batch_alter_table("web_sessions") as batch:
        batch.add_column(sa.Column("absolute_expires_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE web_sessions SET absolute_expires_at=expires_at")
    with op.batch_alter_table("web_sessions") as batch:
        batch.alter_column("absolute_expires_at", existing_type=sa.DateTime(), nullable=False)
        batch.create_index("ix_web_sessions_absolute_expires_at", ["absolute_expires_at"])

    op.create_table(
        "login_failures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_ip", sa.String(128), nullable=False),
        sa.Column("username_casefold", sa.Text(), nullable=False),
        sa.Column("failed_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_login_failures_source_ip", "login_failures", ["source_ip"])
    op.create_index("ix_login_failures_username_casefold", "login_failures", ["username_casefold"])
    op.create_index("ix_login_failures_failed_at", "login_failures", ["failed_at"])


def downgrade() -> None:
    op.drop_table("login_failures")
    with op.batch_alter_table("web_sessions") as batch:
        batch.drop_index("ix_web_sessions_absolute_expires_at")
        batch.drop_column("absolute_expires_at")
    op.execute("DROP TRIGGER files_fts_update")
    op.execute("DROP TRIGGER files_fts_delete")
    op.execute("DROP TRIGGER files_fts_insert")
    op.execute("DROP TABLE files_fts")
    op.drop_table("directories")
    op.drop_index("uq_tags_category_value_casefold", table_name="tags")
    with op.batch_alter_table("file_tags") as batch:
        batch.drop_index("ix_file_tags_tag_file")
    with op.batch_alter_table("files") as batch:
        for index in ("ix_files_parent_modified", "ix_files_parent_size", "ix_files_parent_rating", "ix_files_parent_name", "ix_files_parent_path"):
            batch.drop_index(index)
        batch.drop_column("rating_updated_at")
        batch.drop_column("parent_path")
