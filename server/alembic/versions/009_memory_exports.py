"""Create memory_exports table

Revision ID: 009
Revises: 008
Create Date: 2026-08-05

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memory_exports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("requested_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("status", sa.String(20), nullable=False, server_default="completed"),
        sa.Column("record_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_memory_exports_requested_by", "memory_exports", ["requested_by"])
    op.create_index("ix_memory_exports_created_at", "memory_exports", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_memory_exports_created_at", table_name="memory_exports")
    op.drop_index("ix_memory_exports_requested_by", table_name="memory_exports")
    op.drop_table("memory_exports")
