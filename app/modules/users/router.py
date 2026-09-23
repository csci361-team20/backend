from fastapi import APIRouter

from app.api.deps import DatabaseSession
from app.modules.users import service as user_service
from app.modules.users.schemas import UserCreate, UserResponse

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/", response_model=list[UserResponse])
async def get_all_users(db: DatabaseSession):
    return await user_service.get_all_users_from_db(db=db)


@router.post("/", response_model=UserResponse)
async def create_user(user_in: UserCreate, db: DatabaseSession):
    return await user_service.add_new_user_to_db(user_in=user_in, db=db)
