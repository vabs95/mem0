import uuid
from datetime import datetime
from typing import Any, Optional

from auth import verify_auth
from db import get_db
from fastapi import APIRouter, Depends, Query
from models import TimelineEvent
from pydantic import BaseModel
from sqlalchemy import select
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
    created_at: datetime

    model_config = {"from_attributes": True}


@router.post("/events", response_model=TimelineEventItem)
def create_event(
    body: TimelineEventCreate,
    _auth=Depends(verify_auth),
    db: Session = Depends(get_db),
):
    event = TimelineEvent(**body.model_dump())
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
    if since:
        stmt = stmt.where(TimelineEvent.created_at >= since)
    stmt = stmt.order_by(TimelineEvent.created_at.desc()).limit(limit)
    return db.execute(stmt).scalars().all()
