import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.modules.orders.enums import (
    OrderStatus,
    PaymentStatus,
    RefundStatus,
    TicketStatus,
)

MAX_TICKETS_PER_ORDER = 50
MAX_SEATS = 20


class OrderItemCreate(BaseModel):
    ticket_type_id: uuid.UUID
    quantity: int = Field(..., ge=1, le=MAX_TICKETS_PER_ORDER)


class AttendeeCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    phone: str | None = Field(None, max_length=50)


class OrderCreate(BaseModel):
    """Start checkout. Places are held until payment or ``expires_at``.

    General admission: send ``items``. Assigned seating: send ``seat_ids``
    instead; each seat's ticket type comes from its price category.

    ``attendees`` names each ticket holder in item order (the first item's
    tickets first), or in seat order. Leave it out to put every ticket in
    the buyer's name.
    """

    items: list[OrderItemCreate] = Field(default_factory=list, max_length=20)
    seat_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_SEATS)
    attendees: list[AttendeeCreate] | None = None
    # Validated and priced on the server; see POST /events/{id}/quote
    promo_code: str | None = Field(None, max_length=32)

    @model_validator(mode="after")
    def validate_items(self) -> "OrderCreate":
        if bool(self.items) == bool(self.seat_ids):
            raise ValueError("Send either items or seat_ids")
        if len(self.seat_ids) != len(set(self.seat_ids)):
            raise ValueError("Each seat may appear only once")
        ids = [item.ticket_type_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Each ticket type may appear only once")
        total = sum(item.quantity for item in self.items) + len(self.seat_ids)
        if total > MAX_TICKETS_PER_ORDER:
            raise ValueError(
                f"An order can hold at most {MAX_TICKETS_PER_ORDER} tickets"
            )
        if self.attendees is not None and len(self.attendees) != total:
            raise ValueError(
                f"Give one attendee per ticket ({total}), or leave attendees out"
            )
        return self


class PaymentCreate(BaseModel):
    """Simulated payment (SRS 4.6). No card details are ever sent or stored.

    ``outcome`` lets a demo show both the success and the failure path.
    """

    outcome: Literal["success", "failure"] = "success"
    failure_reason: str | None = Field(None, max_length=255)


class OrderItemResponse(BaseModel):
    id: uuid.UUID
    ticket_type_id: uuid.UUID
    ticket_type_name: str
    unit_price_kzt: int
    quantity: int
    subtotal_kzt: int
    # Assigned seating: the seats on this line
    seats: list[str] | None = None


class TicketResponse(BaseModel):
    id: uuid.UUID
    order_item_id: uuid.UUID
    ticket_type_name: str
    attendee_name: str
    attendee_email: str
    status: TicketStatus
    created_at: datetime
    seat: str | None = None


class PaymentResponse(BaseModel):
    id: uuid.UUID
    status: PaymentStatus
    amount_kzt: int
    processing_fee_kzt: int
    provider: str
    is_simulated: bool
    failure_reason: str | None
    created_at: datetime


class RefundResponse(BaseModel):
    """A full refund. ``is_simulated``: no real money moves in the MVP."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_id: uuid.UUID
    amount_kzt: int
    status: RefundStatus
    reason: str
    initiated_by_name: str | None
    is_simulated: bool
    created_at: datetime


class EventRefundResponse(RefundResponse):
    buyer_name: str


class RefundCreate(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


class RegistrationCancel(BaseModel):
    reason: str | None = Field(None, max_length=500)


class OrderResponse(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    event_title: str
    event_start_at: datetime
    event_timezone: str
    user_id: uuid.UUID
    buyer_name: str
    buyer_email: str
    status: OrderStatus
    subtotal_kzt: int
    discount_kzt: int
    promo_code: str | None
    total_kzt: int
    currency: Literal["KZT"] = "KZT"
    expires_at: datetime | None
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    items: list[OrderItemResponse]
    tickets: list[TicketResponse]
    payments: list[PaymentResponse]
    refund: RefundResponse | None = None
    # One-click calendar options: ics, google, outlook, yahoo
    calendar_links: dict[str, str] = {}


class EventAttendeeResponse(BaseModel):
    """One row of an event's attendee list (one per issued ticket)."""

    ticket_id: uuid.UUID
    order_id: uuid.UUID
    attendee_name: str
    attendee_email: str
    ticket_type_name: str
    status: TicketStatus
    issued_at: datetime
    checked_in_at: datetime | None = None
    seat: str | None = None


class EventSalesSummary(BaseModel):
    """Organizer sales view (SRS 4.6). All figures are demonstration data."""

    event_id: uuid.UUID
    currency: Literal["KZT"] = "KZT"
    is_simulated: bool = True
    confirmed_orders: int
    tickets_sold: int
    gross_sales_kzt: int
    processing_fees_kzt: int
    refunds_kzt: int
    estimated_payout_kzt: int


class TicketEventInfo(BaseModel):
    id: uuid.UUID
    title: str
    start_at: datetime
    end_at: datetime
    timezone: str
    venue_name: str | None
    venue_address: str | None
    city: str | None


class TicketSeat(BaseModel):
    """Filled once assigned seating exists (phase 13)."""

    section: str
    row: str
    number: str


class TicketDetailResponse(BaseModel):
    """A ticket as its holder sees it, with the admission QR payload.

    ``qr_payload`` is the exact text to encode in the QR code. It is only
    given while the ticket can be used; cancelled or refunded tickets have
    none. The digital and printed copies share it and admit once.
    """

    id: uuid.UUID
    order_id: uuid.UUID
    status: TicketStatus
    event: TicketEventInfo
    ticket_type_name: str
    attendee_name: str
    attendee_email: str
    seat: TicketSeat | None = None
    qr_payload: str | None
    issued_at: datetime
