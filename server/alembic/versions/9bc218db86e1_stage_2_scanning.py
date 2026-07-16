"""stage 2 scanning and durable task state

Revision ID: 9bc218db86e1
Revises: a942647ea402
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9bc218db86e1"
down_revision: Union[str, Sequence[str], None] = "a942647ea402"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table(
        "files", naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"}
    ) as batch_op:
        batch_op.drop_constraint("uq_files_relative_path", type_="unique")
        batch_op.add_column(sa.Column("rating", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("present", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("storage_unavailable", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("last_seen_scan_id", sa.String(length=36), nullable=True))
        batch_op.create_index("ix_files_present", ["present"])
        batch_op.create_index("ix_files_storage_unavailable", ["storage_unavailable"])
        batch_op.create_index("ix_files_visible_path", ["present", "relative_path"])
        batch_op.create_index("ix_files_last_seen_scan_id", ["last_seen_scan_id"])

    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(sa.Column("relative_path", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("stable_size", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("stable_modified_ns", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("stable_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("last_error", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("started_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("completed_at", sa.DateTime(), nullable=True))
        batch_op.create_index("ix_tasks_relative_path", ["relative_path"])


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_index("ix_tasks_relative_path")
        for column in ("completed_at", "started_at", "last_error", "stable_count", "stable_modified_ns", "stable_size", "relative_path"):
            batch_op.drop_column(column)

    with op.batch_alter_table(
        "files", naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"}
    ) as batch_op:
        batch_op.drop_index("ix_files_visible_path")
        batch_op.drop_index("ix_files_last_seen_scan_id")
        batch_op.drop_index("ix_files_storage_unavailable")
        batch_op.drop_index("ix_files_present")
        for column in ("last_seen_scan_id", "deleted_at", "storage_unavailable", "present", "rating"):
            batch_op.drop_column(column)
        batch_op.create_unique_constraint("uq_files_relative_path", ["relative_path"])
