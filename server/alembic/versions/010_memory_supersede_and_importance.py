"""Add supersede status and importance columns to memories

Revision ID: 010
Revises: 009
Create Date: 2026-08-05

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Adding importance weighting (1-10) and supersede status lifecycle tracking
    op.add_column("timeline_events", sa.Column("importance", sa.Integer(), nullable=False, server_default="5"))
    op.add_column("timeline_events", sa.Column("status", sa.String(20), nullable=False, server_default="active"))
    op.create_index("ix_timeline_events_status", "timeline_events", ["status"])


def downgrade() -> None:
    op.drop_index("ix_timeline_events_status", table_name="timeline_events")
    op.drop_column("timeline_events", "status")
    op.drop_column("timeline_events", "importance")
