from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organizers import crud
from app.modules.organizers.models import OrganizerProfile
from app.modules.organizers.schemas import (
    OrganizerProfileCreate,
    OrganizerProfileUpdate,
    VerificationStatus,
)
from app.modules.users.models import User


async def get_or_create_profile(db: AsyncSession, user: User) -> OrganizerProfile:
    profile = await crud.get_by_user_id(db, user.id)
    if profile is None:
        profile = await crud.create(db, user.id, user.full_name)
    return profile


async def create_organizer_profile(
    db: AsyncSession, user: User, data_in: OrganizerProfileCreate
) -> OrganizerProfile:
    if await crud.get_by_user_id(db, user.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Organizer profile already exists"
        )
    return await crud.create(db, user.id, data_in.display_name or user.full_name)


async def get_my_profile(db: AsyncSession, user: User) -> OrganizerProfile:
    profile = await crud.get_by_user_id(db, user.id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organizer profile not found")
    return profile


async def get_organizer_profile(db: AsyncSession, id: UUID) -> OrganizerProfile:
    profile = await crud.get_by_id(db, id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organizer profile not found")
    return profile


async def update_my_profile(
    db: AsyncSession, user: User, data_in: OrganizerProfileUpdate
) -> OrganizerProfile:
    profile = await get_my_profile(db, user)
    data = data_in.model_dump(exclude_unset=True, exclude_none=True)
    return await crud.update(db, profile, data)


async def set_verification(
    db: AsyncSession, admin: User, id: UUID, verification_status: VerificationStatus
) -> OrganizerProfile:
    if not admin.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Platform admins only")
    profile = await get_organizer_profile(db, id)
    return await crud.update(db, profile, {"verification_status": verification_status})
