import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.checkin.enums import CheckInAction, CheckInMethod, ScanResult
from app.modules.orders.enums import TicketStatus


class ScanRequest(BaseModel):
    """The exact text read from the QR code."""

    qr_payload: str = Field(..., min_length=1, max_length=500)


class UndoRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


class CheckInTicket(BaseModel):
    id: uuid.UUID
    attendee_name: str
    ticket_type_name: str
    status: TicketStatus
    checked_in_at: datetime | None
    checked_in_by_name: str | None
    seat: str | None = None


class CheckInResult(BaseModel):
    """One clear outcome for the scanner screen (SRS 4.8).

    ``admitted`` is true only when this request let the person in. The
    ticket is left out when the code is not a ticket for this event, so a
    scanner never reveals other events' attendees.
    """

    result: ScanResult
    admitted: bool
    message: str
    ticket: CheckInTicket | None = None


class CheckInStats(BaseModel):
    event_id: uuid.UUID
    registered: int
    checked_in: int
    remaining: int
    checked_in_percent: float


class CheckInRecordResponse(BaseModel):
    id: uuid.UUID
    ticket_id: uuid.UUID
    attendee_name: str
    action: CheckInAction
    method: CheckInMethod
    performed_by_name: str | None
    reason: str | None
    created_at: datetime
