"""Assigned seating (SRS 4.3.1, UC8)."""

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import service as audit
from app.modules.audit.enums import AuditAction, AuditEntity
from app.modules.events import service as event_service
from app.modules.events.enums import EventStatus, SeatingType
from app.modules.events.models import Event
from app.modules.orders.enums import OrderStatus
from app.modules.orders.models import Order
from app.modules.seating.layouts import ensure_predefined_layouts
from app.modules.seating.models import Seat, SeatHold, SeatRow, Venue, VenueSection
from app.modules.seating.schemas import (
    LayoutRow,
    LayoutSection,
    SeatingConfigure,
    SeatMapResponse,
    SeatRowView,
    SeatSectionView,
    SeatView,
    VenueLayoutResponse,
)
from app.modules.tickets import crud as tickets_crud
from app.modules.tickets.crud import active_hold
from app.modules.tickets.inventory import compute_sale_status
from app.modules.tickets.models import TicketType
from app.modules.tickets.schemas import SaleStatus
from app.modules.users.models import User

LEGEND = {
    "available": "Available",
    "selected": "Selected (by you, before checkout)",
    "held": "Temporarily held by another checkout",
    "sold": "Sold",
    "unavailable": "Not on sale",
    "accessible": "Accessible seat (wheelchair place)",
}


@dataclass(frozen=True)
class SeatInfo:
    id: UUID
    section: str
    row: str
    number: str
    category: str
    is_accessible: bool

    @property
    def label(self) -> str:
        text = f"{self.section}, Row {self.row}, Seat {self.number}"
        return f"{text} (accessible)" if self.is_accessible else text


def seat_text(ticket) -> str | None:
    """'Stalls, Row A, Seat 5' for a ticket with a seat, else None."""
    if not ticket.seat_number:
        return None
    return f"{ticket.seat_section}, Row {ticket.seat_row}, Seat {ticket.seat_number}"


# --- Layouts ------------------------------------------------------------------------


def _layout_response(venue: Venue) -> VenueLayoutResponse:
    categories: Counter[str] = Counter()
    accessible = 0
    sections = []
    for section in venue.sections:
        rows = []
        for row in section.rows:
            rows.append(LayoutRow(label=row.label, seats=len(row.seats)))
            for seat in row.seats:
                categories[seat.category] += 1
                accessible += seat.is_accessible
        sections.append(LayoutSection(name=section.name, rows=rows))
    return VenueLayoutResponse(
        id=venue.id,
        name=venue.name,
        address=venue.address,
        city=venue.city,
        total_seats=sum(categories.values()),
        accessible_seats=accessible,
        categories=dict(sorted(categories.items())),
        sections=sections,
    )


async def list_layouts(db: AsyncSession) -> list[VenueLayoutResponse]:
    await ensure_predefined_layouts(db)
    venues = (await db.execute(select(Venue).order_by(Venue.name))).scalars()
    return [_layout_response(v) for v in venues]


async def _venue(db: AsyncSession, venue_id: UUID) -> Venue:
    await ensure_predefined_layouts(db)
    venue = await db.get(Venue, venue_id)
    if venue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Venue layout not found")
    return venue


def _all_seats(venue: Venue) -> list[SeatInfo]:
    return [
        SeatInfo(
            seat.id,
            section.name,
            row.label,
            seat.number,
            seat.category,
            seat.is_accessible,
        )
        for section in venue.sections
        for row in section.rows
        for seat in row.seats
    ]


# --- Configuring an event -------------------------------------------------------------


async def configure(
    db: AsyncSession, event_id: UUID, actor: User, data_in: SeatingConfigure
) -> list[TicketType]:
    """Switch the event to assigned seating with a predefined layout.

    Only before any ticket type exists, so no sold ticket ever lacks a seat.
    Capacity becomes the layout's seat count.
    """
    event = await event_service.get_managed_event(db, event_id, actor)
    if event.status not in (EventStatus.DRAFT, EventStatus.PUBLISHED):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This event can no longer change"
        )
    if await tickets_crud.count_by_event(db, event.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Set up seating before adding ticket types; this event already has some",
        )
    venue = await _venue(db, data_in.venue_id)
    seats = _all_seats(venue)
    per_category = Counter(seat.category for seat in seats)
    given = {c.category: c for c in data_in.categories}
    if set(given) != set(per_category):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Price every category of this layout: " + ", ".join(sorted(per_category)),
        )
    event.seating_type = SeatingType.ASSIGNED
    event.venue_layout_id = venue.id
    event.capacity = len(seats)
    event.venue_name = event.venue_name or venue.name
    event.venue_address = event.venue_address or venue.address
    event.city = event.city or venue.city
    ticket_types = []
    for category, count in sorted(per_category.items()):
        price = given[category]
        ticket_type = TicketType(
            event_id=event.id,
            name=price.name,
            price_kzt=price.price_kzt,
            quantity=count,
            max_per_order=price.max_per_order,
            seat_category=category,
        )
        db.add(ticket_type)
        ticket_types.append(ticket_type)
    audit.record(
        db,
        actor=actor,
        action=AuditAction.EVENT_UPDATED,
        entity_type=AuditEntity.EVENT,
        entity_id=event.id,
        event_id=event.id,
        description=f"Set up assigned seating with {venue.name} ({len(seats)} seats)",
        details={"venue_id": venue.id, "categories": dict(per_category)},
    )
    await db.commit()
    for ticket_type in ticket_types:
        await db.refresh(ticket_type)
    return ticket_types


# --- Seat state -------------------------------------------------------------------


async def taken_seats(db: AsyncSession, event_id: UUID) -> dict[UUID, str]:
    """{seat_id: "sold" | "held"} for seats with a live order."""
    rows = await db.execute(
        select(SeatHold.seat_id, Order.status)
        .join(Order, Order.id == SeatHold.order_id)
        .where(
            SeatHold.event_id == event_id,
            or_(Order.status == OrderStatus.CONFIRMED, active_hold()),
        )
    )
    return {
        seat_id: "sold" if order_status == OrderStatus.CONFIRMED else "held"
        for seat_id, order_status in rows.all()
    }


async def seat_map(
    db: AsyncSession, event_id: UUID, actor: User | None
) -> SeatMapResponse:
    event = await event_service.get_visible_event(db, event_id, actor)
    if event.seating_type != SeatingType.ASSIGNED or event.venue_layout_id is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "This event has general admission, not seats"
        )
    venue = await _venue(db, event.venue_layout_id)
    ticket_types = await tickets_crud.get_by_event(db, event.id, include_hidden=True)
    inventory = await tickets_crud.get_inventory(db, [t.id for t in ticket_types])
    now = datetime.now(UTC)
    by_category: dict[str, tuple[TicketType, bool]] = {}
    for ticket_type in ticket_types:
        if ticket_type.seat_category:
            available = inventory[ticket_type.id].available(ticket_type.quantity)
            sale = compute_sale_status(ticket_type, event, available, now)
            # Seats are sold out seat by seat, so "sold out" still means on sale
            on_sale = sale in (SaleStatus.ON_SALE, SaleStatus.SOLD_OUT)
            by_category[ticket_type.seat_category] = (ticket_type, on_sale)
    taken = await taken_seats(db, event.id)
    counts: Counter[str] = Counter()
    sections = []
    for section in venue.sections:
        rows = []
        for row in section.rows:
            views = []
            for seat in row.seats:
                info = SeatInfo(
                    seat.id,
                    section.name,
                    row.label,
                    seat.number,
                    seat.category,
                    seat.is_accessible,
                )
                ticket_type, on_sale = by_category.get(seat.category, (None, False))
                seat_status = taken.get(seat.id) or (
                    "available" if on_sale else "unavailable"
                )
                counts[seat_status] += 1
                views.append(
                    SeatView(
                        id=seat.id,
                        number=seat.number,
                        category=seat.category,
                        is_accessible=seat.is_accessible,
                        status=seat_status,  # type: ignore[arg-type]
                        ticket_type_id=ticket_type.id if ticket_type else None,
                        price_kzt=ticket_type.price_kzt if ticket_type else None,
                        label=f"{info.label}: {LEGEND[seat_status].lower()}",
                    )
                )
            rows.append(SeatRowView(label=row.label, seats=views))
        sections.append(SeatSectionView(name=section.name, rows=rows))
    return SeatMapResponse(
        event_id=event.id,
        venue_id=venue.id,
        venue_name=venue.name,
        sections=sections,
        counts=dict(counts),
        legend=LEGEND,
    )


# --- Checkout helpers -------------------------------------------------------------


async def resolve_seats(
    db: AsyncSession, event: Event, seat_ids: list[UUID]
) -> list[SeatInfo]:
    """The requested seats, in request order, if all belong to the event's layout."""
    rows = await db.execute(
        select(Seat, SeatRow.label, VenueSection.name)
        .join(SeatRow, SeatRow.id == Seat.row_id)
        .join(VenueSection, VenueSection.id == SeatRow.section_id)
        .where(Seat.id.in_(seat_ids), VenueSection.venue_id == event.venue_layout_id)
    )
    found = {
        seat.id: SeatInfo(
            seat.id, section, row, seat.number, seat.category, seat.is_accessible
        )
        for seat, row, section in rows.all()
    }
    missing = [sid for sid in seat_ids if sid not in found]
    if missing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Seat not found for this event")
    return [found[sid] for sid in seat_ids]


async def hold_seats(
    db: AsyncSession, event_id: UUID, order_id: UUID, seats: list[SeatInfo]
) -> None:
    """Take the seats for this order, all or nothing.

    Holds left by expired, cancelled or refunded orders are cleared first;
    then the unique (event, seat) constraint refuses any seat another live
    order holds, even if both checkouts arrive at the same moment.
    """
    seat_ids = [seat.id for seat in seats]
    live = select(Order.id).where(
        or_(Order.status == OrderStatus.CONFIRMED, active_hold())
    )
    await db.execute(
        delete(SeatHold).where(
            SeatHold.event_id == event_id,
            SeatHold.seat_id.in_(seat_ids),
            SeatHold.order_id.not_in(live),
        )
    )
    for seat in seats:
        db.add(SeatHold(event_id=event_id, seat_id=seat.id, order_id=order_id))
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "One of the selected seats was just taken; choose another seat",
        ) from None


async def seat_labels(db: AsyncSession, seat_ids: list[UUID]) -> dict[UUID, SeatInfo]:
    if not seat_ids:
        return {}
    rows = await db.execute(
        select(Seat, SeatRow.label, VenueSection.name)
        .join(SeatRow, SeatRow.id == Seat.row_id)
        .join(VenueSection, VenueSection.id == SeatRow.section_id)
        .where(Seat.id.in_(seat_ids))
    )
    return {
        seat.id: SeatInfo(
            seat.id, section, row, seat.number, seat.category, seat.is_accessible
        )
        for seat, row, section in rows.all()
    }
