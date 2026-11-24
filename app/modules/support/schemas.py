import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.support.enums import CaseAudience, CaseCategory, CaseStatus


class CaseCreate(BaseModel):
    """Open a case. Give the page's context (event, order or ticket); the rest
    of the context is filled in from it."""

    audience: CaseAudience = CaseAudience.ATTENDEE
    category: CaseCategory
    subject: str = Field(..., min_length=3, max_length=200)
    message: str = Field(..., min_length=1, max_length=5000)
    event_id: uuid.UUID | None = None
    order_id: uuid.UUID | None = None
    ticket_id: uuid.UUID | None = None


class MessageCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=5000)


class CaseUpdate(BaseModel):
    """Staff only. Set ``assignee_user_id`` to null to unassign."""

    status: CaseStatus | None = None
    assignee_user_id: uuid.UUID | None = None


class EscalationCreate(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


class MessageResponse(BaseModel):
    id: uuid.UUID
    sender_user_id: uuid.UUID | None
    sender_name: str
    from_staff: bool
    body: str
    created_at: datetime


class HistoryResponse(BaseModel):
    id: uuid.UUID
    actor_name: str | None
    action: str
    created_at: datetime


class CaseSummary(BaseModel):
    id: uuid.UUID
    audience: CaseAudience
    category: CaseCategory
    subject: str
    status: CaseStatus
    status_label: str
    requester_user_id: uuid.UUID
    requester_name: str
    event_id: uuid.UUID | None
    event_title: str | None
    order_id: uuid.UUID | None
    ticket_id: uuid.UUID | None
    assignee_user_id: uuid.UUID | None
    assignee_name: str | None
    is_escalated: bool
    # True when the signed-in user may assign, change status or escalate
    can_manage: bool
    created_at: datetime
    updated_at: datetime
    message_count: int
    last_message_at: datetime | None


class CaseDetail(CaseSummary):
    messages: list[MessageResponse]
    history: list[HistoryResponse]


class AssigneeOption(BaseModel):
    user_id: uuid.UUID
    full_name: str
    role: str
