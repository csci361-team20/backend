from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events import service as event_service
from app.modules.events.enums import EventStatus
from app.modules.events.models import Event
from app.modules.tickets import crud
from app.modules.tickets.models import TicketType
from app.modules.tickets.schemas import TicketTypeCreate, TicketTypeUpdate

_REQUIRED_FIELDS = ("name", "price_kzt", "quantity", "max_per_order", "is_hidden")


def _ensure_event_editable(event: Event) -> None:
    if event.status in (EventStatus.CANCELLED, EventStatus.COMPLETED):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cannot change tickets of a cancelled or completed event",
        )


async def _ensure_within_capacity(
    db: AsyncSession, event: Event, quantity: int, exclude_id: UUID | None = None
) -> None:
    allocated = await crud.get_total_quantity(db, event.id, exclude_id)
    if allocated + quantity > event.capacity:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Total ticket quantity would exceed event capacity "
            f"({allocated + quantity} > {event.capacity})",
        )


async def create_ticket_type(
    db: AsyncSession, event_id: UUID, data_in: TicketTypeCreate
) -> TicketType:
    event = await event_service.get_event(db, event_id)
    _ensure_event_editable(event)
    await _ensure_within_capacity(db, event, data_in.quantity)
    return await crud.create(db, {**data_in.model_dump(), "event_id": event_id})


async def get_ticket_type(db: AsyncSession, id: UUID) -> TicketType:
    ticket_type = await crud.get_by_id(db, id)
    if ticket_type is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket type not found")
    return ticket_type


async def get_event_ticket_types(
    db: AsyncSession, event_id: UUID, include_hidden: bool = False
) -> list[TicketType]:
    await event_service.get_event(db, event_id)
    return await crud.get_by_event(db, event_id, include_hidden)


async def update_ticket_type(
    db: AsyncSession, id: UUID, data_in: TicketTypeUpdate
) -> TicketType:
    ticket_type = await get_ticket_type(db, id)
    event = await event_service.get_event(db, ticket_type.event_id)
    _ensure_event_editable(event)

    data = data_in.model_dump(exclude_unset=True)
    for field in _REQUIRED_FIELDS:
        if field in data and data[field] is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{field} cannot be null")

    sale_start = data.get("sale_start", ticket_type.sale_start)
    sale_end = data.get("sale_end", ticket_type.sale_end)
    if sale_start and sale_end and sale_end <= sale_start:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "sale_end must be after sale_start"
        )

    if "quantity" in data:
        # TODO: once orders exist, also reject quantity < tickets already sold
        await _ensure_within_capacity(db, event, data["quantity"], exclude_id=id)

    return await crud.update(db, ticket_type, data)
