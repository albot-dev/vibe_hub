"""add automation policy revisions table with backfill

Revision ID: 0004_add_policy_revisions
Revises: 0003_add_webhook_deliveries
Create Date: 2026-02-13 10:30:00

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_add_policy_revisions"
down_revision: Union[str, Sequence[str], None] = "0003_add_webhook_deliveries"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS automation_policy_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            auto_triage BOOLEAN NOT NULL DEFAULT 1,
            auto_assign BOOLEAN NOT NULL DEFAULT 1,
            auto_review BOOLEAN NOT NULL DEFAULT 1,
            auto_merge BOOLEAN NOT NULL DEFAULT 1,
            min_review_approvals INTEGER NOT NULL DEFAULT 1,
            require_test_pass BOOLEAN NOT NULL DEFAULT 1,
            changed_by VARCHAR(120) NOT NULL DEFAULT 'system',
            change_reason VARCHAR(255) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_automation_policy_revisions_project_id
        ON automation_policy_revisions (project_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_automation_policy_revisions_project_created_at
        ON automation_policy_revisions (project_id, created_at)
        """
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
        "Forward-only migration: downgrade is intentionally unsupported for automation_policy_revisions"
    )
