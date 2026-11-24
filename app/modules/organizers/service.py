from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import service as audit
from app.modules.audit.enums import AuditAction, AuditEntity
from app.modules.organizers import crud
from app.modules.organizers.models import OrganizerProfile
from app.modules.organizers.schemas import (
    OrganizerProfileCreate,
    OrganizerProfileUpdate,
    VerificationStatus,
)
from app.modules.users.models import User

_ALREADY_EXISTS = "Organizer profile already exists"


async def get_or_create_profile(db: AsyncSession, user: User) -> OrganizerProfile:
    """The user's organizer profile, created on first use (e.g. first event)."""
    profile = await crud.get_by_user_id(db, user.id)
    if profile is not None:
        return profile
    try:
        return await crud.create(db, user.id, user.full_name)
    except IntegrityError:
        # A parallel request created it first
        await db.rollback()
        profile = await crud.get_by_user_id(db, user.id)
        if profile is None:
            raise
        return profile


async def create_organizer_profile(
    db: AsyncSession, user: User, data_in: OrganizerProfileCreate
) -> OrganizerProfile:
    if await crud.get_by_user_id(db, user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, _ALREADY_EXISTS)
    try:
        return await crud.create(
            db,
            user.id,
            data_in.display_name or user.full_name,
            data_in.model_dump(exclude={"display_name"}, exclude_none=True),
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, _ALREADY_EXISTS) from None


async def get_organizer_profile(db: AsyncSession, id: UUID) -> OrganizerProfile:
    profile = await crud.get_by_id(db, id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organizer profile not found")
    return profile


async def get_my_profile(db: AsyncSession, user: User) -> OrganizerProfile:
    profile = await crud.get_by_user_id(db, user.id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organizer profile not found")
    return profile


async def update_my_profile(
    db: AsyncSession, user: User, data_in: OrganizerProfileUpdate
) -> OrganizerProfile:
    profile = await get_my_profile(db, user)
    data = data_in.model_dump(exclude_unset=True)
    if data.get("display_name", "") is None:
        del data["display_name"]
    return await crud.update(db, profile, data)


async def set_verification(
    db: AsyncSession,
    id: UUID,
    verification_status: VerificationStatus,
    admin: User,
) -> OrganizerProfile:
    """Platform admins only; the router enforces it."""
    profile = await get_organizer_profile(db, id)
    audit.record(
        db,
        actor=admin,
        action=AuditAction.ORGANIZER_VERIFICATION_CHANGED,
        entity_type=AuditEntity.ORGANIZER_PROFILE,
        entity_id=profile.id,
        description=f"Verification of {profile.display_name}: "
        f"{profile.verification_status} → {verification_status}",
        details={"from": profile.verification_status, "to": verification_status},
    )
    data: dict = {"verification_status": verification_status}
    if verification_status == VerificationStatus.VERIFIED:
        data["verified_at"] = datetime.now(UTC)
    return await crud.update(db, profile, data)
