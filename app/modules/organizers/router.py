from uuid import UUID

from fastapi import APIRouter

from app.api.deps import DatabaseSession
from app.modules.organizers import service as organizer_service
from app.modules.organizers.schemas import (
    OrganizerProfileCreate,
    OrganizerProfileResponse,
    OrganizerProfileUpdate,
)

router = APIRouter(prefix="/organizers", tags=["Organizers"])


@router.post("/{user_id}", response_model=OrganizerProfileResponse)
async def create_organizer_profile(
    user_id: UUID, data_in: OrganizerProfileCreate, db: DatabaseSession
):
    return await organizer_service.create_organizer_profile(
        db=db, user_id=user_id, data_in=data_in
    )


@router.get("/{id}", response_model=OrganizerProfileResponse)
async def get_organizer_profile(id: UUID, db: DatabaseSession):
    return await organizer_service.get_organizer_profile(db=db, id=id)


@router.patch("/{id}", response_model=OrganizerProfileResponse)
async def update_organizer_profile(
    id: UUID, data_in: OrganizerProfileUpdate, db: DatabaseSession
):
    return await organizer_service.update_organizer_profile(
        db=db, id=id, data_in=data_in
    )
