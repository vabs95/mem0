"""Create timeline_events table

Revision ID: 007
Revises: 006
Create Date: 2026-08-02

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "timeline_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=True),
        sa.Column("agent_id", sa.String(255), nullable=True),
        sa.Column("run_id", sa.String(255), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("source_agent", sa.String(32), nullable=False),
        sa.Column("project", sa.String(255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # High-volume append-only timestamp column — go straight to BRIN rather
    # than a btree (see 006_request_logs_brin.py for why request_logs was
    # migrated the same way after the fact).
    op.execute("CREATE INDEX ix_timeline_events_created_at ON timeline_events USING BRIN (created_at)")
    op.create_index("ix_timeline_events_user_id", "timeline_events", ["user_id"])
    op.create_index("ix_timeline_events_agent_id", "timeline_events", ["agent_id"])
    op.create_index("ix_timeline_events_run_id", "timeline_events", ["run_id"])
    op.create_index("ix_timeline_events_project", "timeline_events", ["project"])
    op.create_index("ix_timeline_events_event_type", "timeline_events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_timeline_events_event_type", table_name="timeline_events")
    op.drop_index("ix_timeline_events_project", table_name="timeline_events")
    op.drop_index("ix_timeline_events_run_id", table_name="timeline_events")
    op.drop_index("ix_timeline_events_agent_id", table_name="timeline_events")
    op.drop_index("ix_timeline_events_user_id", table_name="timeline_events")
    op.drop_index("ix_timeline_events_created_at", table_name="timeline_events")
    op.drop_table("timeline_events")
