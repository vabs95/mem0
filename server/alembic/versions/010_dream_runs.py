"""Create dream_runs table

Revision ID: 010
Revises: 009
Create Date: 2026-08-06

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dream_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("requested_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", sa.String(255), nullable=True),
        sa.Column("agent_id", sa.String(255), nullable=True),
        sa.Column("run_id", sa.String(255), nullable=True),
        sa.Column("project", sa.String(255), nullable=True),
        sa.Column("similarity_threshold", sa.Float(), nullable=False, server_default="0.9"),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clusters_merged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_memories_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("memories_merged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_dream_runs_requested_by", "dream_runs", ["requested_by"])
    op.create_index("ix_dream_runs_created_at", "dream_runs", ["created_at"])
    # Per-scope concurrency lock: only one "running" row allowed per exact
    # (user_id, agent_id, run_id, project) tuple. Plain multi-column UNIQUE
    # indexes treat NULL as distinct from NULL, so two concurrent runs that
    # are both e.g. user_id=alice with agent_id/run_id/project all NULL
    # (the common case -- most Dream runs only set user_id) would NOT
    # collide and the lock would silently do nothing for exactly the
    # scope shape that matters most. COALESCE each column to '' first so
    # NULLs compare equal to each other within this index.
    op.execute(
        """
        CREATE UNIQUE INDEX dream_runs_active_scope_idx ON dream_runs (
            COALESCE(user_id, ''), COALESCE(agent_id, ''), COALESCE(run_id, ''), COALESCE(project, '')
        ) WHERE status = 'running'
        """
    )


def downgrade() -> None:
    op.drop_index("dream_runs_active_scope_idx", table_name="dream_runs")
    op.drop_index("ix_dream_runs_created_at", table_name="dream_runs")
    op.drop_index("ix_dream_runs_requested_by", table_name="dream_runs")
    op.drop_table("dream_runs")
