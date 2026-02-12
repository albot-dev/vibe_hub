"""add autopilot jobs table

Revision ID: 0002_add_autopilot_jobs
Revises: 0001_initial
Create Date: 2026-02-12 00:30:00

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_add_autopilot_jobs"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS autopilot_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'queued',
            max_items INTEGER NOT NULL DEFAULT 3,
            provider VARCHAR(80),
            requested_by VARCHAR(120) NOT NULL DEFAULT 'system',
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 1,
            worker_id VARCHAR(120),
            started_at DATETIME,
            finished_at DATETIME,
            canceled_at DATETIME,
            processed_items INTEGER NOT NULL DEFAULT 0,
            created_prs INTEGER NOT NULL DEFAULT 0,
            merged_prs INTEGER NOT NULL DEFAULT 0,
            merged_pr_ids_json TEXT NOT NULL DEFAULT '[]',
            error_message TEXT NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_autopilot_jobs_project_id ON autopilot_jobs (project_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_autopilot_jobs_status ON autopilot_jobs (status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS autopilot_jobs")
