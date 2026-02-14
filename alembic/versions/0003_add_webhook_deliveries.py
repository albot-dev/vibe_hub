"""add github webhook deliveries table

Revision ID: 0003_add_webhook_deliveries
Revises: 0002_add_autopilot_jobs
Create Date: 2026-02-12 09:30:00

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0003_add_webhook_deliveries"
down_revision: Union[str, Sequence[str], None] = "0002_add_autopilot_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_index(
    inspector: sa.Inspector,
    table_name: str,
    columns: tuple[str, ...],
    *,
    unique: bool | None = None,
) -> bool:
    for index in inspector.get_indexes(table_name):
        index_columns = tuple(index.get("column_names") or ())
        if index_columns != columns:
            continue
        if unique is None or bool(index.get("unique")) == unique:
            return True
    return False


def _has_unique_constraint(inspector: sa.Inspector, table_name: str, columns: tuple[str, ...]) -> bool:
    for constraint in inspector.get_unique_constraints(table_name):
        constraint_columns = tuple(constraint.get("column_names") or ())
        if constraint_columns == columns:
            return True
    return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    created_table = False

    if "github_webhook_deliveries" not in table_names:
        op.create_table(
            "github_webhook_deliveries",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("delivery_id", sa.String(length=255), nullable=False),
            sa.Column("event", sa.String(length=120), nullable=False),
            sa.Column("action", sa.String(length=64), nullable=False),
            sa.Column(
                "project_id",
                sa.Integer(),
                sa.ForeignKey("projects.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("issue_number", sa.Integer(), nullable=True),
            sa.Column("job_id", sa.Integer(), nullable=True),
            sa.Column("reason", sa.Text(), nullable=False, server_default=sa.text("''")),
            sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        created_table = True

    has_delivery_unique = _has_index(
        inspector,
        "github_webhook_deliveries",
        ("delivery_id",),
        unique=True,
    ) or _has_unique_constraint(inspector, "github_webhook_deliveries", ("delivery_id",))

    if created_table or not has_delivery_unique:
        op.create_index(
            "ux_github_webhook_deliveries_delivery_id",
            "github_webhook_deliveries",
            ["delivery_id"],
            unique=True,
        )

    if created_table or not _has_index(inspector, "github_webhook_deliveries", ("event",)):
        op.create_index("ix_github_webhook_deliveries_event", "github_webhook_deliveries", ["event"])

    if created_table or not _has_index(inspector, "github_webhook_deliveries", ("action",)):
        op.create_index("ix_github_webhook_deliveries_action", "github_webhook_deliveries", ["action"])

    if created_table or not _has_index(inspector, "github_webhook_deliveries", ("project_id",)):
        op.create_index("ix_github_webhook_deliveries_project_id", "github_webhook_deliveries", ["project_id"])


def downgrade() -> None:
    raise RuntimeError(
        "Forward-only migration policy: downgrade is not supported for revision 0003_add_webhook_deliveries"
    )
