from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import service as audit
from app.modules.audit.enums import AuditAction, AuditEntity
from app.modules.events import service as event_service
from app.modules.events.enums import EventLifecycle, EventStatus, SeatingType
from app.modules.events.models import Event
from app.modules.events.permissions import MANAGE_ROLES, ensure_event_role
from app.modules.tickets import crud, inventory
from app.modules.tickets.models import TicketType
from app.modules.tickets.schemas import (
    EventTicketStats,
    TicketTypeCreate,
    TicketTypeResponse,
    TicketTypeUpdate,
)
from app.modules.users.models import User

_REQUIRED_FIELDS = ("name", "price_kzt", "quantity", "max_per_order", "is_hidden")


def _ensure_event_editable(event: Event) -> None:
    if event.status in (EventStatus.CANCELLED, EventStatus.COMPLETED) or (
        event.lifecycle == EventLifecycle.COMPLETED
    ):
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


async def _can_see_hidden(db: AsyncSession, event: Event, actor: User | None) -> bool:
    if actor is None:
        return False
    try:
        await ensure_event_role(db, event, actor, MANAGE_ROLES)
    except HTTPException:
        return False
    return True


async def _get_ticket_type(db: AsyncSession, id: UUID) -> TicketType:
    ticket_type = await crud.get_by_id(db, id)
    if ticket_type is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket type not found")
    return ticket_type


async def _respond(
    db: AsyncSession, event: Event, ticket_type: TicketType
) -> TicketTypeResponse:
    return (await inventory.build_responses(db, event, [ticket_type]))[0]


async def create_ticket_type(
    db: AsyncSession, event_id: UUID, actor: User, data_in: TicketTypeCreate
) -> TicketTypeResponse:
    event = await event_service.get_managed_event(db, event_id, actor)
    _ensure_event_editable(event)
    if event.seating_type == SeatingType.ASSIGNED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ticket types of a seated event come from its layout",
        )
    await _ensure_within_capacity(db, event, data_in.quantity)
    ticket_type_id = uuid4()
    _log(
        db,
        actor,
        AuditAction.TICKET_TYPE_CREATED,
        event.id,
        ticket_type_id,
        f"Added ticket type {data_in.name} "
        f"({data_in.quantity} × {_price(data_in.price_kzt)})",
        {"price_kzt": data_in.price_kzt, "quantity": data_in.quantity},
    )
    ticket_type = await crud.create(
        db, {**data_in.model_dump(), "id": ticket_type_id, "event_id": event_id}
    )
    return await _respond(db, event, ticket_type)


async def get_ticket_type(
    db: AsyncSession, id: UUID, actor: User | None
) -> TicketTypeResponse:
    ticket_type = await _get_ticket_type(db, id)
    event = await event_service.get_visible_event(db, ticket_type.event_id, actor)
    if ticket_type.is_hidden and not await _can_see_hidden(db, event, actor):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket type not found")
    return await _respond(db, event, ticket_type)


async def get_event_ticket_types(
    db: AsyncSession,
    event_id: UUID,
    actor: User | None,
    include_hidden: bool = False,
) -> list[TicketTypeResponse]:
    event = await event_service.get_visible_event(db, event_id, actor)
    if include_hidden and actor is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if include_hidden and not await _can_see_hidden(db, event, actor):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the event's owner and managers can see hidden ticket types",
        )
    ticket_types = await crud.get_by_event(db, event_id, include_hidden)
    return await inventory.build_responses(db, event, ticket_types)


async def get_event_ticket_stats(
    db: AsyncSession, event_id: UUID, actor: User
) -> EventTicketStats:
    event = await event_service.get_managed_event(db, event_id, actor)
    ticket_types = await crud.get_by_event(db, event_id, include_hidden=True)
    return await inventory.build_stats(db, event, ticket_types)


async def update_ticket_type(
    db: AsyncSession, id: UUID, actor: User, data_in: TicketTypeUpdate
) -> TicketTypeResponse:
    ticket_type = await _get_ticket_type(db, id)
    event = await event_service.get_managed_event(db, ticket_type.event_id, actor)
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

    if "quantity" in data and ticket_type.seat_category:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A seated ticket type has one ticket per seat; its quantity is fixed",
        )
    if "quantity" in data:
        await _ensure_within_capacity(db, event, data["quantity"], exclude_id=id)
        counts = (await crud.get_inventory(db, [id]))[id]
        committed = counts.sold + counts.reserved
        if data["quantity"] < committed:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{committed} tickets are already sold or reserved; "
                f"quantity cannot be lower",
            )

    changed = audit.changes(ticket_type, data)
    if changed:
        _log(
            db,
            actor,
            AuditAction.TICKET_TYPE_UPDATED,
            event.id,
            ticket_type.id,
            f"Changed {ticket_type.name}: "
            + ", ".join(_describe_change(f, c) for f, c in changed.items()),
            {"changes": changed},
        )
    ticket_type = await crud.update(db, ticket_type, data)
    return await _respond(db, event, ticket_type)


async def delete_ticket_type(db: AsyncSession, id: UUID, actor: User) -> None:
    ticket_type = await _get_ticket_type(db, id)
    event = await event_service.get_managed_event(db, ticket_type.event_id, actor)
    _ensure_event_editable(event)
    if await crud.has_order_items(db, id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This ticket type has orders; hide it instead of deleting it",
        )
    if ticket_type.seat_category:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A seated ticket type belongs to the layout; hide it instead",
        )
    _log(
        db,
        actor,
        AuditAction.TICKET_TYPE_DELETED,
        event.id,
        ticket_type.id,
        f"Deleted ticket type {ticket_type.name}",
    )
    await crud.delete(db, ticket_type)


def _price(price_kzt: int) -> str:
    return "free" if price_kzt == 0 else f"{price_kzt} KZT"


def _describe_change(field: str, change: dict) -> str:
    if field == "price_kzt":
        return f"price {_price(change['from'])} → {_price(change['to'])}"
    if field == "quantity":
        return f"quantity {change['from']} → {change['to']}"
    return field.replace("_", " ")


def _log(
    db: AsyncSession,
    actor: User,
    action: AuditAction,
    event_id: UUID,
    ticket_type_id: UUID,
    description: str,
    details: dict | None = None,
) -> None:
    audit.record(
        db,
        actor=actor,
        action=action,
        entity_type=AuditEntity.TICKET_TYPE,
        entity_id=ticket_type_id,
        event_id=event_id,
        description=description,
        details=details,
    )
