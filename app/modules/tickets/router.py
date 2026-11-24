from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DatabaseSession, OptionalUser
from app.modules.tickets import service as ticket_service
from app.modules.tickets.schemas import (
    EventTicketStats,
    TicketTypeCreate,
    TicketTypeResponse,
    TicketTypeUpdate,
)

router = APIRouter(tags=["Ticket types"])


@router.post(
    "/events/{event_id}/ticket-types",
    response_model=TicketTypeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_ticket_type(
    event_id: UUID, data_in: TicketTypeCreate, db: DatabaseSession, actor: CurrentUser
):
    """Owner or manager of the event."""
    return await ticket_service.create_ticket_type(
        db=db, event_id=event_id, actor=actor, data_in=data_in
    )


@router.get("/events/{event_id}/ticket-types", response_model=list[TicketTypeResponse])
async def get_event_ticket_types(
    event_id: UUID,
    db: DatabaseSession,
    actor: OptionalUser,
    include_hidden: bool = False,
):
    """``include_hidden`` is limited to the event's owner and managers."""
    return await ticket_service.get_event_ticket_types(
        db=db, event_id=event_id, actor=actor, include_hidden=include_hidden
    )


@router.get("/ticket-types/{id}", response_model=TicketTypeResponse)
async def get_ticket_type(id: UUID, db: DatabaseSession, actor: OptionalUser):
    return await ticket_service.get_ticket_type(db=db, id=id, actor=actor)


@router.patch("/ticket-types/{id}", response_model=TicketTypeResponse)
async def update_ticket_type(
    id: UUID, data_in: TicketTypeUpdate, db: DatabaseSession, actor: CurrentUser
):
    """Owner or manager of the event."""
    return await ticket_service.update_ticket_type(
        db=db, id=id, actor=actor, data_in=data_in
    )


@router.get("/events/{event_id}/ticket-stats", response_model=EventTicketStats)
async def get_event_ticket_stats(
    event_id: UUID, db: DatabaseSession, actor: CurrentUser
):
    """Available, reserved, sold, refunded and checked-in counts per ticket type.

    Owner or manager of the event.
    """
    return await ticket_service.get_event_ticket_stats(
        db=db, event_id=event_id, actor=actor
    )


@router.delete("/ticket-types/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ticket_type(id: UUID, db: DatabaseSession, actor: CurrentUser):
    """Only a ticket type with no orders can be deleted; otherwise hide it."""
    await ticket_service.delete_ticket_type(db=db, id=id, actor=actor)
