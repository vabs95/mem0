"""Add category and memory_ids to timeline_events

Revision ID: 008
Revises: 007
Create Date: 2026-08-05

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("timeline_events", sa.Column("category", sa.String(64), nullable=True))
    op.add_column(
        "timeline_events",
        sa.Column("memory_ids", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.create_index("ix_timeline_events_category", "timeline_events", ["category"])
    # GIN index so the memory->event backlink query (memory_ids @> '["<id>"]')
    # doesn't need a sequential scan as the table grows.
    op.execute(
        "CREATE INDEX ix_timeline_events_memory_ids ON timeline_events USING GIN (memory_ids)"
    )


def downgrade() -> None:
    op.drop_index("ix_timeline_events_memory_ids", table_name="timeline_events")
    op.drop_index("ix_timeline_events_category", table_name="timeline_events")
    op.drop_column("timeline_events", "memory_ids")
    op.drop_column("timeline_events", "category")
