import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    key_prefix: Mapped[str] = mapped_column(String(12))
    key_hash: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(String(255))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class RequestLog(Base):
    __tablename__ = "request_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    method: Mapped[str] = mapped_column(String(16))
    path: Mapped[str] = mapped_column(String(512))
    status_code: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[float] = mapped_column(Float)
    auth_type: Mapped[str] = mapped_column(String(32), default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class RefreshTokenJti(Base):
    __tablename__ = "refresh_token_jtis"

    jti: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class TimelineEvent(Base):
    """Append-only activity log, separate from mem0's extracted-fact memories.

    Reuses mem0's canonical scoping fields (user_id/agent_id/run_id, see
    ENTITY_PARAMS in mem0/memory/main.py) plus `project`, matching the
    self-hosted MCP bridge's naming — not `app_id`, to avoid reintroducing
    the vocabulary mismatch fixed in the MCP bridge's tool schemas.
    """

    __tablename__ = "timeline_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64))
    source_agent: Mapped[str] = mapped_column(String(32))
    project: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # claude-mem-style classification (decision/bug_fix/task_learning/...),
    # pulled from the same metadata.type value add_memory callers already set.
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Forward provenance link: memory ids this event produced (e.g. an
    # add_memory tool call). Going the other way (memory -> source event) is
    # a query against this column (JSONB containment), not a stored
    # back-reference — see routers/timeline.py's for-memory lookup.
    memory_ids: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class MemoryExport(Base):
    """A completed (synchronous, v1) memory export job.

    `status`/`payload` are split out so a future async export path (large
    exports run in a background worker) is a non-breaking addition rather
    than a schema change -- v1 always writes status="completed" immediately.
    """

    __tablename__ = "memory_exports"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    format: Mapped[str] = mapped_column(String(16))
    filters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DreamRun(Base):
    """A Dream memory-consolidation run, executed as a FastAPI BackgroundTask.

    `status` starts at "running" the moment the row is inserted (before the
    background task starts) and is updated to "completed"/"failed" once the
    task finishes -- this is what the dashboard polls to show live progress
    and keep history across refreshes, and what the per-scope unique index
    (see migration 010) uses to block a second concurrent run over the same
    scope.
    """

    __tablename__ = "dream_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_new_uuid)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    project: Mapped[str | None] = mapped_column(String(255), nullable=True)
    similarity_threshold: Mapped[float] = mapped_column(Float, default=0.90)
    status: Mapped[str] = mapped_column(String(20), default="running")
    processed: Mapped[int] = mapped_column(Integer, default=0)
    clusters_merged: Mapped[int] = mapped_column(Integer, default=0)
    new_memories_created: Mapped[int] = mapped_column(Integer, default=0)
    memories_merged: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Settings(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )
