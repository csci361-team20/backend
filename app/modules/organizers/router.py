from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DatabaseSession
from app.modules.organizers import service as organizer_service
from app.modules.organizers.schemas import (
    OrganizerProfileCreate,
    OrganizerProfileResponse,
    OrganizerProfileUpdate,
    OrganizerVerificationUpdate,
)

router = APIRouter(prefix="/organizers", tags=["Organizers"])


@router.post(
    "/", response_model=OrganizerProfileResponse, status_code=status.HTTP_201_CREATED
)
async def create_organizer_profile(
    user: CurrentUser,
    db: DatabaseSession,
    data_in: OrganizerProfileCreate | None = None,
):
    return await organizer_service.create_organizer_profile(
        db=db,
        user=user,
        data_in=data_in if data_in is not None else OrganizerProfileCreate(),
    )


@router.get("/me", response_model=OrganizerProfileResponse)
async def get_my_profile(user: CurrentUser, db: DatabaseSession):
    return await organizer_service.get_my_profile(db=db, user=user)


@router.patch("/me", response_model=OrganizerProfileResponse)
async def update_my_profile(
    data_in: OrganizerProfileUpdate, user: CurrentUser, db: DatabaseSession
):
    return await organizer_service.update_my_profile(db=db, user=user, data_in=data_in)


@router.get("/{id}", response_model=OrganizerProfileResponse)
async def get_organizer_profile(id: UUID, db: DatabaseSession):
    return await organizer_service.get_organizer_profile(db=db, id=id)


@router.patch("/{id}/verification", response_model=OrganizerProfileResponse)
async def set_verification(
    id: UUID,
    data_in: OrganizerVerificationUpdate,
    admin: CurrentUser,
    db: DatabaseSession,
):
    return await organizer_service.set_verification(
        db=db, admin=admin, id=id, verification_status=data_in.verification_status
    )
