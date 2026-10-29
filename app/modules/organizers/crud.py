from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organizers.models import OrganizerProfile


async def get_by_id(db: AsyncSession, id: UUID) -> OrganizerProfile | None:
    result = await db.execute(select(OrganizerProfile).where(OrganizerProfile.id == id))
    return result.scalar_one_or_none()


async def get_by_user_id(db: AsyncSession, user_id: UUID) -> OrganizerProfile | None:
    result = await db.execute(
        select(OrganizerProfile).where(OrganizerProfile.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def create(
    db: AsyncSession, user_id: UUID, display_name: str
) -> OrganizerProfile:
    profile = OrganizerProfile(user_id=user_id, display_name=display_name)
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


async def update(
    db: AsyncSession, profile: OrganizerProfile, data: dict
) -> OrganizerProfile:
    for field, value in data.items():
        setattr(profile, field, value)
    await db.commit()
    await db.refresh(profile)
    return profile
