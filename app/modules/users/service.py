from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User
from app.modules.users.schemas import UserCreate


async def add_new_user_to_db(db: AsyncSession, user_in: UserCreate) -> User:
    query = select(User).where(User.email == user_in.email)
    result = await db.execute(query)
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists",
        )

    user_data = user_in.model_dump()
    raw_password = user_data.pop("password")

    password_hash = raw_password

    user = User(**user_data, password_hash=password_hash)
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return user


async def get_all_users_from_db(db: AsyncSession):
    query = select(User)
    result = await db.execute(query)
    return result.scalars().all()
