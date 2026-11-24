from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def get_by_id(db: AsyncSession, id: UUID) -> User | None:
    result = await db.execute(select(User).where(User.id == id))
    return result.scalar_one_or_none()


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    # Case-insensitive, so accounts created before normalization still match
    result = await db.execute(
        select(User).where(func.lower(User.email) == normalize_email(email))
    )
    return result.scalar_one_or_none()


async def get_all(db: AsyncSession, skip: int = 0, limit: int = 100) -> list[User]:
    result = await db.execute(
        select(User).order_by(User.created_at).offset(skip).limit(limit)
    )
    return list(result.scalars().all())


async def create(
    db: AsyncSession,
    email: str,
    full_name: str,
    password_hash: str,
    preferred_language: str = "en",
) -> User:
    user = User(
        email=normalize_email(email),
        full_name=full_name,
        password_hash=password_hash,
        preferred_language=preferred_language,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update(db: AsyncSession, user: User, data: dict) -> User:
    for field, value in data.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return user


async def delete(db: AsyncSession, user: User) -> None:
    await db.delete(user)
    await db.commit()


async def get_by_ids(db: AsyncSession, ids: list[UUID]) -> list[User]:
    if not ids:
        return []
    result = await db.execute(select(User).where(User.id.in_(ids)))
    return list(result.scalars().all())
