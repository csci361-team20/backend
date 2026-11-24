from datetime import datetime
from uuid import UUID

from fastapi import APIRouter

from app.api.deps import CurrentUser, DatabaseSession
from app.modules.checkin import service as checkin_service
from app.modules.checkin.schemas import (
    CheckInRecordResponse,
    CheckInResult,
    CheckInStats,
    ScanRequest,
    UndoRequest,
)

router = APIRouter(prefix="/events/{event_id}/check-in", tags=["Check-in"])


@router.post("/verify", response_model=CheckInResult)
async def verify_ticket(
    event_id: UUID, data_in: ScanRequest, db: DatabaseSession, actor: CurrentUser
):
    """Check a scanned code without admitting anyone. Event team only."""
    return await checkin_service.verify(
        db=db, event_id=event_id, actor=actor, payload=data_in.qr_payload
    )


@router.post("/scan", response_model=CheckInResult)
async def scan_ticket(
    event_id: UUID, data_in: ScanRequest, db: DatabaseSession, actor: CurrentUser
):
    """Verify and admit in one step. Event team only.

    Always 200 with one ``result``: valid (``admitted`` true), already_used,
    cancelled, refunded, invalid or wrong_event. Campaign QR codes are
    invalid here: they are never permission to enter.
    """
    return await checkin_service.scan(
        db=db, event_id=event_id, actor=actor, payload=data_in.qr_payload
    )


@router.post("/tickets/{ticket_id}", response_model=CheckInResult)
async def check_in_ticket(
    event_id: UUID, ticket_id: UUID, db: DatabaseSession, actor: CurrentUser
):
    """Admit a ticket found by searching the attendee list."""
    return await checkin_service.check_in_manually(
        db=db, event_id=event_id, ticket_id=ticket_id, actor=actor
    )


@router.post("/tickets/{ticket_id}/undo", response_model=CheckInResult)
async def undo_check_in(
    event_id: UUID,
    ticket_id: UUID,
    data_in: UndoRequest,
    db: DatabaseSession,
    actor: CurrentUser,
):
    """Reverse an accidental check-in, with a reason. Owners and managers any
    time; check-in staff only their own, within 10 minutes."""
    return await checkin_service.undo(
        db=db,
        event_id=event_id,
        ticket_id=ticket_id,
        actor=actor,
        reason=data_in.reason,
    )


@router.get("/stats", response_model=CheckInStats)
async def check_in_stats(event_id: UUID, db: DatabaseSession, actor: CurrentUser):
    """Registered and checked-in counts. Event team only."""
    return await checkin_service.stats(db=db, event_id=event_id, actor=actor)


@router.get("/history", response_model=list[CheckInRecordResponse])
async def check_in_history(
    event_id: UUID,
    db: DatabaseSession,
    actor: CurrentUser,
    since: datetime | None = None,
):
    """Check-ins and reversals, newest first (at most 500). Pass ``since`` to
    fetch only newer records."""
    return await checkin_service.history(
        db=db, event_id=event_id, actor=actor, since=since
    )
