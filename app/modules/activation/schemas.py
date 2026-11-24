import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.activation.enums import ActivationStatus, ChecklistItem


class ChecklistEntry(BaseModel):
    item: ChecklistItem
    label: str
    done: bool
    hint: str | None = None


class ActivationResponse(BaseModel):
    """The organizer's activation checklist for one event (SRS 4.5)."""

    event_id: uuid.UUID
    status: ActivationStatus
    fee_kzt: int
    currency: Literal["KZT"] = "KZT"
    fee_paid_at: datetime | None
    terms_version: str
    terms_accepted_at: datetime | None
    activated_at: datetime | None
    suspended_at: datetime | None
    suspension_reason: str | None
    checklist: list[ChecklistEntry]
    can_activate: bool
    is_simulated: bool = True


class FeePaymentCreate(BaseModel):
    """Simulated fee payment; ``failure`` shows the declined path in a demo."""

    outcome: Literal["success", "failure"] = "success"


class TermsAcceptance(BaseModel):
    terms_version: str = Field(..., max_length=20)


class SuspensionCreate(BaseModel):
    reason: str = Field(..., min_length=5, max_length=500)


class ActivationRecordResponse(BaseModel):
    """Admin view of an activation record (SRS 4.12)."""

    id: uuid.UUID
    event_id: uuid.UUID
    event_title: str
    organizer_profile_id: uuid.UUID
    organizer_name: str
    status: ActivationStatus
    fee_kzt: int
    fee_paid_at: datetime | None
    fee_payment_reference: str | None
    terms_version: str | None
    terms_accepted_at: datetime | None
    activated_at: datetime | None
    suspended_at: datetime | None
    suspension_reason: str | None
    created_at: datetime
