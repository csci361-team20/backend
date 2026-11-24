from uuid import UUID

from fastapi import APIRouter

from app.api.deps import CurrentUser, DatabaseSession, OptionalUser
from app.modules.seating import service as seating_service
from app.modules.seating.schemas import (
    SeatingConfigure,
    SeatMapResponse,
    VenueLayoutResponse,
)
from app.modules.tickets import inventory
from app.modules.tickets.schemas import TicketTypeResponse

router = APIRouter(tags=["Seating"])


@router.get("/venue-layouts", response_model=list[VenueLayoutResponse])
async def list_venue_layouts(db: DatabaseSession, _actor: CurrentUser):
    """The predefined layouts an organizer can choose (SRS 4.3.1): sections,
    rows, seat counts, accessible places and price categories."""
    return await seating_service.list_layouts(db)


@router.post("/events/{event_id}/seating", response_model=list[TicketTypeResponse])
async def configure_seating(
    event_id: UUID, data_in: SeatingConfigure, db: DatabaseSession, actor: CurrentUser
):
    """Use assigned seating with a predefined layout. Price each category;
    one ticket type per category is created with one ticket per seat.
    Owner or manager, before any ticket type exists."""
    ticket_types = await seating_service.configure(db, event_id, actor, data_in)
    event = await seating_service.event_service.get_event(db, event_id)
    return await inventory.build_responses(db, event, ticket_types)


@router.get("/events/{event_id}/seat-map", response_model=SeatMapResponse)
async def get_seat_map(event_id: UUID, db: DatabaseSession, actor: OptionalUser):
    """Every seat with its status (available, held, sold, unavailable), price,
    accessible flag and a text label, so status never relies on colour alone.
    Poll it to keep availability current."""
    return await seating_service.seat_map(db, event_id, actor)
