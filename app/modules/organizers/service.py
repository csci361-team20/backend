from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organizers import crud
from app.modules.organizers.models import OrganizerProfile
from app.modules.organizers.schemas import (
    OrganizerProfileCreate,
    OrganizerProfileUpdate,
)


async def create_organizer_profile(
    db: AsyncSession, user_id: UUID, data_in: OrganizerProfileCreate
) -> OrganizerProfile:
    if await crud.get_by_user_id(db, user_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="Organizer profile already exists"
        )
    return await crud.create(db, user_id, data_in.display_name)


async def get_organizer_profile(db: AsyncSession, id: UUID) -> OrganizerProfile:
    profile = await crud.get_by_id(db, id)
    if profile is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Organizer profile not found"
        )
    return profile


async def update_organizer_profile(
    db: AsyncSession, id: UUID, data_in: OrganizerProfileUpdate
) -> OrganizerProfile:
    profile = await get_organizer_profile(db, id)
    return await crud.update(db, profile, data_in.model_dump(exclude_unset=True))
