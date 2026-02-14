"""add automation policy revisions table with backfill

Revision ID: 0004_add_policy_revisions
Revises: 0003_add_webhook_deliveries
Create Date: 2026-02-13 10:30:00

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0004_add_policy_revisions"
down_revision: Union[str, Sequence[str], None] = "0003_add_webhook_deliveries"
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

    if "automation_policy_revisions" not in table_names:
        op.create_table(
            "automation_policy_revisions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "project_id",
                sa.Integer(),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("auto_triage", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("auto_assign", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("auto_review", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("auto_merge", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("min_review_approvals", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("require_test_pass", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("changed_by", sa.String(length=120), nullable=False, server_default=sa.text("'system'")),
            sa.Column("change_reason", sa.String(length=255), nullable=False, server_default=sa.text("''")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        created_table = True

    if created_table or not _has_index(inspector, "automation_policy_revisions", ("project_id",)):
        op.create_index("ix_automation_policy_revisions_project_id", "automation_policy_revisions", ["project_id"])

    if created_table or not _has_index(inspector, "automation_policy_revisions", ("project_id", "created_at")):
        op.create_index(
            "ix_automation_policy_revisions_project_created_at",
            "automation_policy_revisions",
            ["project_id", "created_at"],
        )

    op.execute(
        """
        INSERT INTO automation_policy_revisions (
            project_id,
            auto_triage,
            auto_assign,
            auto_review,
            auto_merge,
            min_review_approvals,
            require_test_pass,
            changed_by,
            change_reason,
            created_at
        )
        SELECT
            project_id,
            auto_triage,
            auto_assign,
            auto_review,
            auto_merge,
            min_review_approvals,
            require_test_pass,
            'system:migration',
            'initial_snapshot_backfill',
            CURRENT_TIMESTAMP
        FROM automation_policies p
        WHERE NOT EXISTS (
            SELECT 1
            FROM automation_policy_revisions r
            WHERE r.project_id = p.project_id
        )
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Forward-only migration policy: downgrade is not supported for revision 0004_add_policy_revisions"
    )
