"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-02-12 00:00:00

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

from app.models import Base

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    raise RuntimeError(
        "Forward-only migration policy: downgrade is not supported for revision 0001_initial"
    )
