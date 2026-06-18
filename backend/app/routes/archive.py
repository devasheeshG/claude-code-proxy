"""Admin access to the immutable request/response body archive."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.utils import archive, security
from app.utils.postgres import UsageRecordDb, get_db

router = APIRouter(tags=["Request explorer"], prefix="/requests")


class ArchiveRequestDetail(BaseModel):
    event_id: uuid.UUID
    request_body_path: str
    response_body_path: str
    request_available: bool
    response_available: bool


def _store() -> archive.S3ArchiveStore:
    store = archive.get_archive_store()
    if store is None:
        raise HTTPException(status_code=503, detail="Request archive is disabled.")
    return store


async def _body_key(
    store: archive.S3ArchiveStore,
    event_id: uuid.UUID,
    created_at: datetime,
    filename: str,
) -> str | None:
    candidates = [filename]
    if filename.endswith(".json"):
        candidates.append(f"{filename}.gz")
    for candidate in candidates:
        key = await store.find_body_key(str(event_id), created_at, candidate)
        if key is not None:
            return key
    return None


def _created_at(db: Session, event_id: uuid.UUID) -> datetime:
    row = db.query(UsageRecordDb).filter(UsageRecordDb.request_id == f"req_{event_id.hex}").first()
    return row.created_at if row is not None else datetime.now(timezone.utc)


@router.get("/{event_id}", response_model=ArchiveRequestDetail)
async def get_archive_request(
    event_id: uuid.UUID,
    _: str = Depends(security.require_admin),
    db: Session = Depends(get_db),
) -> ArchiveRequestDetail:
    store = _store()
    created_at = _created_at(db, event_id)
    request_key = await _body_key(store, event_id, created_at, "request.json")
    response_key = await _body_key(store, event_id, created_at, "response.json")
    if request_key is None and response_key is None:
        raise HTTPException(status_code=404, detail="Archived request not found.")
    return ArchiveRequestDetail(
        event_id=event_id,
        request_body_path=f"/v1/requests/{event_id}/body?side=request",
        response_body_path=f"/v1/requests/{event_id}/body?side=response",
        request_available=request_key is not None,
        response_available=response_key is not None,
    )


@router.get("/{event_id}/body")
async def get_archive_body(
    event_id: uuid.UUID,
    side: str = Query(..., pattern="^(request|response)$"),
    _: str = Depends(security.require_admin),
    db: Session = Depends(get_db),
) -> Response:
    store = _store()
    key = await _body_key(
        store,
        event_id,
        _created_at(db, event_id),
        "request.json" if side == "request" else "response.json",
    )
    if key is None:
        raise HTTPException(status_code=404, detail=f"Archived {side} body not found.")
    try:
        body = await store.get_decompressed_body(key)
    except archive.ArchiveWriteError as exc:
        raise HTTPException(status_code=502, detail="Unable to read archived request body.") from exc
    return Response(content=body, media_type="application/json")
