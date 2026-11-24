"""Promotional campaigns, their promo codes and redemptions (SRS 4.14)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# Which ticket types a campaign applies to; no rows = every paid ticket type
campaign_ticket_types = Table(
    "campaign_ticket_types",
    Base.metadata,
    Column(
        "campaign_id",
        UUID(as_uuid=True),
        ForeignKey("promotional_campaigns.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "ticket_type_id",
        UUID(as_uuid=True),
        ForeignKey("ticket_types.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class PromotionalCampaign(Base):
    __tablename__ = "promotional_campaigns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # "percent" (1-100) or "fixed" (KZT off the applicable subtotal, once per order)
    discount_type: Mapped[str] = mapped_column(String(10), nullable=False)
    discount_value: Mapped[int] = mapped_column(Integer, nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # None = unlimited
    max_redemptions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Opaque token in the campaign QR link; it carries no price or discount
    link_token: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=func.now()
    )

    promo_code: Mapped["PromoCode"] = relationship(
        back_populates="campaign", lazy="selectin", uselist=False
    )
    # Empty list = applies to every paid ticket type of the event
    ticket_types: Mapped[list["TicketType"]] = relationship(  # noqa: F821
        "TicketType", secondary=campaign_ticket_types, lazy="selectin"
    )


class PromoCode(Base):
    """The code attendees type; one per campaign (SRS 4.14)."""

    __tablename__ = "promo_codes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("promotional_campaigns.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id"), nullable=False
    )
    # Stored upper-case; unique within an event, so organizers can reuse a
    # word like SPRING10 on different events
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    campaign: Mapped["PromotionalCampaign"] = relationship(back_populates="promo_code")

    __table_args__ = (UniqueConstraint("event_id", "code"),)


class PromoRedemption(Base):
    """A code applied to an order.

    Counts toward the campaign limit while its order is confirmed or still
    holding places; an expired, cancelled or refunded order frees it.
    """

    __tablename__ = "promo_redemptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("promotional_campaigns.id"),
        nullable=False,
        index=True,
    )
    promo_code_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("promo_codes.id"), nullable=False
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False, unique=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    discount_kzt: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
