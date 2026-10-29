from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import DatabaseSession
from app.modules.users import service as user_service
from app.modules.users.schemas import UserCreate, UserResponse, UserUpdate

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/", response_model=list[UserResponse])
async def get_all_users(db: DatabaseSession):
    return await user_service.get_all_users_from_db(db=db)


@router.get("/{id}", response_model=UserResponse)
async def get_user_by_id(id: UUID, db: DatabaseSession):
    return await user_service.get_user_from_db_by_id(db=db, id=id)


@router.post("/", response_model=UserResponse)
async def create_user(user_in: UserCreate, db: DatabaseSession):
    return await user_service.add_new_user_to_db(user_in=user_in, db=db)


@router.patch("/{id}", response_model=UserResponse)
async def update_user(id: UUID, user_in: UserUpdate, db: DatabaseSession):
    return await user_service.update_user_in_db(db=db, id=id, user_in=user_in)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(id: UUID, db: DatabaseSession):
    await user_service.delete_user_from_db(db=db, id=id)
