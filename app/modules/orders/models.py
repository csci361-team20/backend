import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.security import generate_qr_token
from app.modules.orders.enums import (
    SIMULATED_PROVIDER,
    OrderStatus,
    TicketStatus,
)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OrderStatus.PENDING, index=True
    )
    total_kzt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Before any promo discount; total_kzt = subtotal_kzt - discount_kzt
    subtotal_kzt: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    discount_kzt: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("promotional_campaigns.id"), nullable=True
    )
    promo_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # A pending order holds its places until this moment (SRS 4.3.1, 4.6)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", lazy="selectin"
    )
    attendees: Mapped[list["Attendee"]] = relationship(
        back_populates="order", lazy="selectin"
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="order", lazy="selectin", order_by="Payment.created_at"
    )
    refund: Mapped["Refund | None"] = relationship(lazy="selectin", uselist=False)


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False, index=True
    )
    ticket_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ticket_types.id"), nullable=False, index=True
    )
    # Name at purchase time, so later renames do not rewrite receipts
    ticket_type_name: Mapped[str] = mapped_column(
        String(100), nullable=False, default="", server_default=""
    )
    unit_price_kzt: Mapped[int] = mapped_column(Integer, nullable=False)
    # Assigned seating: labels of the seats on this line (SRS 4.3.1)
    seats: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    order: Mapped["Order"] = relationship(back_populates="items")
    tickets: Mapped[list["Ticket"]] = relationship(
        back_populates="order_item", lazy="selectin"
    )


class Attendee(Base):
    __tablename__ = "attendees"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False, index=True
    )
    # The order line this person's ticket comes from (one attendee per ticket)
    order_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_items.id"), nullable=True, index=True
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Assigned seating: the seat this person's ticket is for
    seat_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("seats.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    order: Mapped["Order"] = relationship(back_populates="attendees")


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_items.id"), nullable=False, index=True
    )
    attendee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("attendees.id"), nullable=False, index=True
    )
    qr_secret: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False, default=generate_qr_token
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TicketStatus.VALID, index=True
    )
    # Current admission state; the full history is in check_in_records
    checked_in_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    checked_in_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Assigned seat, copied at issue so the ticket stays readable on its own
    seat_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("seats.id"), nullable=True
    )
    seat_section: Mapped[str | None] = mapped_column(String(100), nullable=True)
    seat_row: Mapped[str | None] = mapped_column(String(10), nullable=True)
    seat_number: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    order_item: Mapped["OrderItem"] = relationship(back_populates="tickets")
    attendee: Mapped["Attendee"] = relationship(lazy="selectin")


class Payment(Base):
    """A payment attempt. Always simulated in the academic MVP."""

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    amount_kzt: Mapped[int] = mapped_column(Integer, nullable=False)
    # Charged to the organizer, deducted from the payout
    processing_fee_kzt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider: Mapped[str] = mapped_column(
        String(50), nullable=False, default=SIMULATED_PROVIDER
    )
    is_simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    order: Mapped["Order"] = relationship(back_populates="payments")


class Refund(Base):
    """A full refund of a paid order (SRS 4.9). Always simulated in the MVP."""

    __tablename__ = "refunds"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False, unique=True
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id"), nullable=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id"), nullable=False, index=True
    )
    amount_kzt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    initiated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    initiated_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
