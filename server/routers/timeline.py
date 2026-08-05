import uuid
from datetime import datetime
from typing import Any, Optional

from auth import verify_auth
from db import get_db
from fastapi import APIRouter, Depends, Query
from models import TimelineEvent
from pydantic import BaseModel
from sqlalchemy import cast, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

router = APIRouter(prefix="/timeline", tags=["timeline"])


class TimelineEventCreate(BaseModel):
    event_type: str
    source_agent: str
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    project: Optional[str] = None
    summary: Optional[str] = None
    payload: Optional[dict[str, Any]] = None
    category: Optional[str] = None
    memory_ids: Optional[list[str]] = None


class TimelineEventItem(BaseModel):
    id: uuid.UUID
    event_type: str
    source_agent: str
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    project: Optional[str] = None
    summary: Optional[str] = None
    payload: Optional[dict[str, Any]] = None
    category: Optional[str] = None
    memory_ids: list[str] = []
    created_at: datetime

    model_config = {"from_attributes": True}


@router.post("/events", response_model=TimelineEventItem)
def create_event(
    body: TimelineEventCreate,
    _auth=Depends(verify_auth),
    db: Session = Depends(get_db),
):
    data = body.model_dump()
    data["memory_ids"] = data.get("memory_ids") or []
    event = TimelineEvent(**data)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.get("/events", response_model=list[TimelineEventItem])
def list_events(
    _auth=Depends(verify_auth),
    db: Session = Depends(get_db),
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    project: Optional[str] = None,
    event_type: Optional[str] = None,
    category: Optional[str] = None,
    since: Optional[datetime] = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    stmt = select(TimelineEvent)
    if user_id:
        stmt = stmt.where(TimelineEvent.user_id == user_id)
    if agent_id:
        stmt = stmt.where(TimelineEvent.agent_id == agent_id)
    if run_id:
        stmt = stmt.where(TimelineEvent.run_id == run_id)
    if project:
        stmt = stmt.where(TimelineEvent.project == project)
    if event_type:
        stmt = stmt.where(TimelineEvent.event_type == event_type)
    if category:
        stmt = stmt.where(TimelineEvent.category == category)
    if since:
        stmt = stmt.where(TimelineEvent.created_at >= since)
    stmt = stmt.order_by(TimelineEvent.created_at.desc()).limit(limit)
    return db.execute(stmt).scalars().all()


@router.get("/events/for-memory/{memory_id}", response_model=list[TimelineEventItem])
def get_events_for_memory(
    memory_id: str,
    _auth=Depends(verify_auth),
    db: Session = Depends(get_db),
):
    """Backlink: which event(s) produced a given memory (e.g. an add_memory
    tool call). memory_ids is the forward link (event -> memories); this is
    the reverse direction, a query rather than a stored back-reference."""
    stmt = select(TimelineEvent).order_by(TimelineEvent.created_at.desc())
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        # .contains() dispatches through the column's declared type, which
        # is the generic JSON side of the with_variant() in models.py (its
        # .contains() is a plain string LIKE, not a JSONB op) — .op("@>")
        # forces the real Postgres containment operator regardless of type
        # resolution, matching what's actually indexed (GIN, migration 008).
        stmt = stmt.where(TimelineEvent.memory_ids.op("@>")(cast([memory_id], JSONB)))
        return db.execute(stmt).scalars().all()
    # Non-Postgres (e.g. SQLite in tests): JSONB containment isn't
    # available, so filter in Python. Fine at this table's scale — the
    # indexed GIN containment query is what actually runs in production.
    return [e for e in db.execute(stmt).scalars().all() if memory_id in (e.memory_ids or [])]
