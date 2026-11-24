"""Turn ticket types into API responses with live availability.

Kept free of service imports so both the events and tickets services can
use it without importing each other.
"""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.enums import EventLifecycle
from app.modules.events.models import Event
from app.modules.tickets import crud
from app.modules.tickets.crud import Inventory
from app.modules.tickets.models import TicketType
from app.modules.tickets.schemas import (
    EventTicketStats,
    SaleStatus,
    TicketStatsTotals,
    TicketTypeResponse,
    TicketTypeStats,
)


def compute_sale_status(
    ticket_type: TicketType, event: Event, available: int, now: datetime
) -> SaleStatus:
    if ticket_type.is_hidden:
        return SaleStatus.HIDDEN
    if event.lifecycle in (EventLifecycle.COMPLETED, EventLifecycle.CANCELLED):
        return SaleStatus.ENDED
    closes = [t for t in (ticket_type.sale_end, event.registration_closes_at) if t]
    if any(now >= t for t in closes):
        return SaleStatus.ENDED
    opens = [t for t in (ticket_type.sale_start, event.registration_opens_at) if t]
    if any(now < t for t in opens):
        return SaleStatus.SCHEDULED
    if available <= 0:
        return SaleStatus.SOLD_OUT
    return SaleStatus.ON_SALE


def _fields(ticket_type: TicketType) -> dict:
    return {
        column.key: getattr(ticket_type, column.key)
        for column in TicketType.__mapper__.columns
    }


def _build(
    ticket_type: TicketType, event: Event, inventory: Inventory, now: datetime
) -> dict:
    available = inventory.available(ticket_type.quantity)
    return {
        **_fields(ticket_type),
        "available": available,
        "sale_status": compute_sale_status(ticket_type, event, available, now),
    }


async def build_responses(
    db: AsyncSession, event: Event, ticket_types: list[TicketType]
) -> list[TicketTypeResponse]:
    inventory = await crud.get_inventory(db, [t.id for t in ticket_types])
    now = datetime.now(UTC)
    return [
        TicketTypeResponse.model_validate(_build(t, event, inventory[t.id], now))
        for t in ticket_types
    ]


async def build_stats(
    db: AsyncSession, event: Event, ticket_types: list[TicketType]
) -> EventTicketStats:
    inventory = await crud.get_inventory(db, [t.id for t in ticket_types])
    now = datetime.now(UTC)
    rows = []
    for ticket_type in ticket_types:
        counts = inventory[ticket_type.id]
        rows.append(
            TicketTypeStats.model_validate(
                {
                    **_build(ticket_type, event, counts, now),
                    "sold": counts.sold,
                    "reserved": counts.reserved,
                    "refunded": counts.refunded,
                    "checked_in": counts.checked_in,
                }
            )
        )
    totals = TicketStatsTotals(
        quantity=sum(r.quantity for r in rows),
        available=sum(r.available for r in rows),
        sold=sum(r.sold for r in rows),
        reserved=sum(r.reserved for r in rows),
        refunded=sum(r.refunded for r in rows),
        checked_in=sum(r.checked_in for r in rows),
    )
    return EventTicketStats(
        event_id=event.id, capacity=event.capacity, ticket_types=rows, totals=totals
    )
