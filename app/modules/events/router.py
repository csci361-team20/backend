from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DatabaseSession, OptionalUser
from app.modules.events import service as event_service
from app.modules.events.schemas import EventCreate, EventResponse, EventUpdate

router = APIRouter(prefix="/events", tags=["Events"])


@router.post("/", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(data_in: EventCreate, user: CurrentUser, db: DatabaseSession):
    return await event_service.create_event(db=db, user=user, data_in=data_in)


@router.get("/", response_model=list[EventResponse])
async def get_public_events(
    db: DatabaseSession,
    skip: int = 0,
    limit: int = 100,
    city: str | None = None,
    category: str | None = None,
):
    return await event_service.get_public_events(
        db=db, skip=skip, limit=limit, city=city, category=category
    )


@router.get("/mine", response_model=list[EventResponse])
async def get_my_events(user: CurrentUser, db: DatabaseSession):
    return await event_service.get_managed_events(db=db, user=user)


@router.get("/{id}", response_model=EventResponse)
async def get_event(id: UUID, user: OptionalUser, db: DatabaseSession):
    return await event_service.get_event_for_viewer(db=db, id=id, user=user)


@router.patch("/{id}", response_model=EventResponse)
async def update_event(
    id: UUID, data_in: EventUpdate, user: CurrentUser, db: DatabaseSession
):
    return await event_service.update_event(db=db, user=user, id=id, data_in=data_in)


@router.post("/{id}/publish", response_model=EventResponse)
async def publish_event(id: UUID, user: CurrentUser, db: DatabaseSession):
    return await event_service.publish_event(db=db, user=user, id=id)


@router.post("/{id}/cancel", response_model=EventResponse)
async def cancel_event(id: UUID, user: CurrentUser, db: DatabaseSession):
    return await event_service.cancel_event(db=db, user=user, id=id)
