import csv
import io
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from auth import require_auth
from db import get_db
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from models import MemoryExport, User
from pydantic import BaseModel
from server_state import get_memory_instance
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/export", tags=["export"])

SCAN_LIMIT = 10_000
ExportFormat = Literal["json", "csv"]

# Mirrors main.py's _RESERVED_PAYLOAD_KEYS / _serialize_memory shape.
# Duplicated rather than imported to avoid a circular import (main.py
# mounts this router) and to keep this new feature from touching main.py
# beyond the one include_router line.
_RESERVED_PAYLOAD_KEYS = {"data", "user_id", "agent_id", "run_id", "hash", "created_at", "updated_at", "expiration_date"}


def _serialize_memory(row: Any) -> dict[str, Any]:
    payload = getattr(row, "payload", None) or {}
    return {
        "id": getattr(row, "id", None),
        "memory": payload.get("data"),
        "user_id": payload.get("user_id"),
        "agent_id": payload.get("agent_id"),
        "run_id": payload.get("run_id"),
        "hash": payload.get("hash"),
        "expiration_date": payload.get("expiration_date"),
        "metadata": {k: v for k, v in payload.items() if k not in _RESERVED_PAYLOAD_KEYS},
        "created_at": payload.get("created_at"),
        "updated_at": payload.get("updated_at"),
    }


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class ExportCreateRequest(BaseModel):
    format: ExportFormat = "json"
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    project: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None


class ExportItem(BaseModel):
    id: uuid.UUID
    format: str
    filters: dict[str, Any]
    status: str
    record_count: int
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


@router.post("/memories", response_model=ExportItem)
def create_export(
    body: ExportCreateRequest,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    results = get_memory_instance().vector_store.list(top_k=SCAN_LIMIT)
    rows = results[0] if results and isinstance(results, list) and isinstance(results[0], list) else results or []
    records = [_serialize_memory(row) for row in rows]

    if body.user_id:
        records = [r for r in records if r.get("user_id") == body.user_id]
    if body.agent_id:
        records = [r for r in records if r.get("agent_id") == body.agent_id]
    if body.run_id:
        records = [r for r in records if r.get("run_id") == body.run_id]
    if body.project:
        records = [r for r in records if r.get("metadata", {}).get("project") == body.project]
    if body.date_from:
        records = [r for r in records if (_parse_timestamp(r.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= body.date_from]
    if body.date_to:
        records = [r for r in records if (_parse_timestamp(r.get("created_at")) or datetime.max.replace(tzinfo=timezone.utc)) <= body.date_to]

    for r in records:
        if r.get("id") is not None:
            r["id"] = str(r["id"])

    filters = {
        k: v
        for k, v in {
            "user_id": body.user_id,
            "agent_id": body.agent_id,
            "run_id": body.run_id,
            "project": body.project,
            "date_from": body.date_from.isoformat() if body.date_from else None,
            "date_to": body.date_to.isoformat() if body.date_to else None,
        }.items()
        if v
    }

    now = datetime.now(timezone.utc)
    export = MemoryExport(
        requested_by=user.id,
        format=body.format,
        filters=filters,
        status="completed",
        record_count=len(records),
        payload=records,
        created_at=now,
        completed_at=now,
    )
    db.add(export)
    db.commit()
    db.refresh(export)
    return export


@router.get("", response_model=list[ExportItem])
def list_exports(
    _user: User = Depends(require_auth),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
):
    stmt = select(MemoryExport).order_by(MemoryExport.created_at.desc()).limit(limit)
    return db.execute(stmt).scalars().all()


def _get_export_or_404(export_id: uuid.UUID, db: Session) -> MemoryExport:
    export = db.get(MemoryExport, export_id)
    if export is None:
        raise HTTPException(status_code=404, detail="Export not found.")
    return export


@router.get("/{export_id}/download")
def download_export(
    export_id: uuid.UUID,
    _user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    export = _get_export_or_404(export_id, db)
    filename_stamp = export.created_at.strftime("%Y%m%d-%H%M%S")

    if export.format == "csv":
        buffer = io.StringIO()
        fieldnames = ["id", "memory", "user_id", "agent_id", "run_id", "hash", "expiration_date", "metadata", "created_at", "updated_at"]
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for record in export.payload:
            row = dict(record)
            row["metadata"] = json.dumps(row.get("metadata") or {})
            writer.writerow(row)
        buffer.seek(0)
        return StreamingResponse(
            iter([buffer.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="memories-{filename_stamp}.csv"'},
        )

    body = json.dumps({"results": export.payload}, default=str)
    return StreamingResponse(
        iter([body]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="memories-{filename_stamp}.json"'},
    )


@router.delete("/{export_id}")
def delete_export(
    export_id: uuid.UUID,
    _user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    export = _get_export_or_404(export_id, db)
    db.delete(export)
    db.commit()
    return {"message": "Export deleted"}
