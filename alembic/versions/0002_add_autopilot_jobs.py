"""add autopilot jobs table

Revision ID: 0002_add_autopilot_jobs
Revises: 0001_initial
Create Date: 2026-02-12 00:30:00

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002_add_autopilot_jobs"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_index(inspector: sa.Inspector, table_name: str, columns: tuple[str, ...]) -> bool:
    for index in inspector.get_indexes(table_name):
        index_columns = tuple(index.get("column_names") or ())
        if index_columns == columns:
            return True
    return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    created_table = False

    if "autopilot_jobs" not in table_names:
        op.create_table(
            "autopilot_jobs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "project_id",
                sa.Integer(),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'queued'")),
            sa.Column("max_items", sa.Integer(), nullable=False, server_default=sa.text("3")),
            sa.Column("provider", sa.String(length=80), nullable=True),
            sa.Column("requested_by", sa.String(length=120), nullable=False, server_default=sa.text("'system'")),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("worker_id", sa.String(length=120), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("canceled_at", sa.DateTime(), nullable=True),
            sa.Column("processed_items", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("created_prs", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("merged_prs", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("merged_pr_ids_json", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("error_message", sa.Text(), nullable=False, server_default=sa.text("''")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        created_table = True

    if created_table or not _has_index(inspector, "autopilot_jobs", ("project_id",)):
        op.create_index("ix_autopilot_jobs_project_id", "autopilot_jobs", ["project_id"])

    if created_table or not _has_index(inspector, "autopilot_jobs", ("status",)):
        op.create_index("ix_autopilot_jobs_status", "autopilot_jobs", ["status"])


def downgrade() -> None:
    raise RuntimeError(
        "Forward-only migration policy: downgrade is not supported for revision 0002_add_autopilot_jobs"
    )
