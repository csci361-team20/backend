from uuid import UUID

from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.modules.auth import service as auth_service
from app.modules.users import crud
from app.modules.users.models import User
from app.modules.users.schemas import UserCreate, UserUpdate


def ensure_self_or_admin(actor: User, user_id: UUID) -> None:
    if actor.id != user_id and not actor.is_platform_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You can only access your own account"
        )


async def add_new_user_to_db(
    db: AsyncSession, user_in: UserCreate, background: BackgroundTasks
) -> User:
    if await crud.get_by_email(db, user_in.email):
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="User with this email already exists"
        )
    try:
        user = await crud.create(
            db,
            user_in.email,
            user_in.full_name,
            hash_password(user_in.password),
            user_in.preferred_language,
        )
    except IntegrityError:
        # Two registrations with the same email raced past the check above
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="User with this email already exists"
        ) from None
    auth_service.queue_verification_email(user, background)
    return user


async def get_all_users_from_db(
    db: AsyncSession, skip: int = 0, limit: int = 100
) -> list[User]:
    return await crud.get_all(db, skip, limit)


async def get_user_from_db_by_id(db: AsyncSession, id: UUID) -> User:
    user = await crud.get_by_id(db, id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


async def update_user_in_db(db: AsyncSession, id: UUID, user_in: UserUpdate) -> User:
    user = await get_user_from_db_by_id(db, id)
    data = user_in.model_dump(exclude_unset=True, exclude_none=True)
    return await crud.update(db, user, data)


async def delete_user_from_db(db: AsyncSession, id: UUID) -> None:
    user = await get_user_from_db_by_id(db, id)
    try:
        await crud.delete(db, user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This account owns events, orders, or other records and cannot be deleted",
        ) from None
