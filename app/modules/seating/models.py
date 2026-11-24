"""Venue layouts, seats and seat holds (SRS 4.3.1, UC8).

The MVP ships predefined layouts (no layout editor). A seat is taken for an
event while a hold row exists for it whose order is paid or still holding
places; the unique (event, seat) constraint makes double-selling impossible
even when two checkouts race.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Venue(Base):
    __tablename__ = "venues"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_predefined: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    sections: Mapped[list["VenueSection"]] = relationship(
        lazy="selectin", order_by="VenueSection.position"
    )


class VenueSection(Base):
    __tablename__ = "venue_sections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venues.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    rows: Mapped[list["SeatRow"]] = relationship(
        lazy="selectin", order_by="SeatRow.position"
    )


class SeatRow(Base):
    __tablename__ = "seat_rows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("venue_sections.id"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(10), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    seats: Mapped[list["Seat"]] = relationship(
        lazy="selectin", order_by="Seat.position"
    )


class Seat(Base):
    __tablename__ = "seats"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    row_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("seat_rows.id"), nullable=False, index=True
    )
    number: Mapped[str] = mapped_column(String(10), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # Price category; each event maps a category to one of its ticket types
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    is_accessible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class SeatHold(Base):
    """A seat held or sold for an event, tied to the order that took it."""

    __tablename__ = "seat_holds"
    __table_args__ = (UniqueConstraint("event_id", "seat_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id"), nullable=False, index=True
    )
    seat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("seats.id"), nullable=False
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
