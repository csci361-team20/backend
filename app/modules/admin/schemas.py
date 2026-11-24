import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class PlatformSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    activation_fee_kzt: int
    support_email: str
    bookings_enabled: bool
    updated_at: datetime | None


class PlatformSettingsUpdate(BaseModel):
    activation_fee_kzt: int | None = Field(None, ge=0, le=10_000_000)
    support_email: EmailStr | None = None
    bookings_enabled: bool | None = None


# --- Search and lists ------------------------------------------------------------


class AdminUserRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    is_platform_admin: bool
    is_suspended: bool
    suspension_reason: str | None
    is_email_verified: bool
    created_at: datetime


class AdminEventRow(BaseModel):
    id: uuid.UUID
    title: str
    organizer_name: str
    status: str
    lifecycle: str
    visibility: str
    start_at: datetime
    city: str | None
    is_suspended: bool
    suspension_reason: str | None
    paid_sales_open: bool
    created_at: datetime


class AdminOrderRow(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    event_title: str
    buyer_email: str
    status: str
    total_kzt: int
    discount_kzt: int
    promo_code: str | None
    created_at: datetime


class AdminPaymentRow(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    event_title: str
    buyer_email: str
    status: str
    amount_kzt: int
    processing_fee_kzt: int
    failure_reason: str | None
    is_simulated: bool
    created_at: datetime


class AdminRefundRow(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    event_title: str
    buyer_email: str
    amount_kzt: int
    reason: str
    initiated_by_name: str | None
    created_at: datetime


class AdminOrganizerRow(BaseModel):
    """An organizer for the verification queue; the IIN/BIN is masked."""

    id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    email: str
    verification_status: str
    legal_name: str | None
    tax_id_masked: str | None
    verification_submitted_at: datetime | None
    verified_at: datetime | None
    is_suspended: bool


class SearchResults(BaseModel):
    users: list[AdminUserRow]
    events: list[AdminEventRow]
    orders: list[AdminOrderRow]
    payments: list[AdminPaymentRow]


class SuspensionRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


# --- Reports and disputes ---------------------------------------------------------


class ReportCreate(BaseModel):
    reason: str = Field(..., min_length=10, max_length=1000)


class ReportReview(BaseModel):
    """``action`` marks the report handled; set ``suspend_event`` to also
    suspend the event in the same step."""

    decision: Literal["dismissed", "actioned"]
    note: str | None = Field(None, max_length=1000)
    suspend_event: bool = False


class ReportResponse(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    event_title: str
    reporter_user_id: uuid.UUID
    reason: str
    status: str
    review_note: str | None
    reviewed_at: datetime | None
    created_at: datetime


class DisputeCreate(BaseModel):
    reason: str = Field(..., min_length=3, max_length=1000)


class DisputeResolve(BaseModel):
    status: Literal["won", "lost"]
    note: str | None = Field(None, max_length=1000)


class DisputeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    payment_id: uuid.UUID
    order_id: uuid.UUID
    amount_kzt: int
    reason: str
    status: str
    resolution_note: str | None
    resolved_at: datetime | None
    created_at: datetime


class PromoActivityRow(BaseModel):
    redemption_id: uuid.UUID
    code: str
    campaign_name: str
    event_id: uuid.UUID
    event_title: str
    order_id: uuid.UUID
    order_status: str
    buyer_email: str
    discount_kzt: int
    created_at: datetime


class AuditRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    actor_name: str | None
    event_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    description: str
