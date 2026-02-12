"""add github webhook deliveries table

Revision ID: 0003_add_webhook_deliveries
Revises: 0002_add_autopilot_jobs
Create Date: 2026-02-12 09:30:00

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_add_webhook_deliveries"
down_revision: Union[str, Sequence[str], None] = "0002_add_autopilot_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS github_webhook_deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            delivery_id VARCHAR(255) NOT NULL,
            event VARCHAR(120) NOT NULL,
            action VARCHAR(64) NOT NULL,
            project_id INTEGER,
            issue_number INTEGER,
            job_id INTEGER,
            reason TEXT NOT NULL DEFAULT '',
            duplicate_count INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_github_webhook_deliveries_delivery_id "
        "ON github_webhook_deliveries (delivery_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_github_webhook_deliveries_event "
        "ON github_webhook_deliveries (event)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_github_webhook_deliveries_action "
        "ON github_webhook_deliveries (action)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_github_webhook_deliveries_project_id "
        "ON github_webhook_deliveries (project_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS github_webhook_deliveries")
