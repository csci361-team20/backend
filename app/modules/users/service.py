
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.modules.users import crud
from app.modules.users.models import User
from app.modules.users.schemas import UserCreate, UserUpdate


async def add_new_user_to_db(db: AsyncSession, user_in: UserCreate) -> User:
    if await crud.get_by_email(db, user_in.email):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="User with this email already exists"
        )
    return await crud.create(
        db, user_in.email, user_in.full_name, hash_password(user_in.password)
    )


async def get_all_users_from_db(db: AsyncSession) -> list[User]:
    return await crud.get_all(db)


async def get_user_from_db_by_id(db: AsyncSession, id: UUID) -> User:
    user = await crud.get_by_id(db, id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


async def update_user_in_db(db: AsyncSession, id: UUID, user_in: UserUpdate) -> User:
    user = await get_user_from_db_by_id(db, id)
    return await crud.update(db, user, user_in.model_dump(exclude_unset=True))


async def delete_user_in_db(db: AsyncSession, id: UUID) -> None:
    user = await get_user_from_db_by_id(db, id)
    await crud.delete(db, user)
