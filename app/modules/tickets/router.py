from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DatabaseSession, OptionalUser
from app.modules.tickets import service as ticket_service
from app.modules.tickets.schemas import (
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
    event_id: UUID, data_in: TicketTypeCreate, user: CurrentUser, db: DatabaseSession
):
    return await ticket_service.create_ticket_type(
        db=db, user=user, event_id=event_id, data_in=data_in
    )


@router.get("/events/{event_id}/ticket-types", response_model=list[TicketTypeResponse])
async def get_event_ticket_types(
    event_id: UUID,
    user: OptionalUser,
    db: DatabaseSession,
    include_hidden: bool = False,
):
    return await ticket_service.get_event_ticket_types(
        db=db, event_id=event_id, user=user, include_hidden=include_hidden
    )


@router.get("/ticket-types/{id}", response_model=TicketTypeResponse)
async def get_ticket_type(id: UUID, db: DatabaseSession):
    return await ticket_service.get_ticket_type(db=db, id=id)


@router.patch("/ticket-types/{id}", response_model=TicketTypeResponse)
async def update_ticket_type(
    id: UUID, data_in: TicketTypeUpdate, user: CurrentUser, db: DatabaseSession
):
    return await ticket_service.update_ticket_type(
        db=db, user=user, id=id, data_in=data_in
    )
