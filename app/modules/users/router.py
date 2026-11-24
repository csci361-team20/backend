from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Query, status

from app.api.deps import CurrentUser, DatabaseSession, PlatformAdmin
from app.modules.users import service as user_service
from app.modules.users.schemas import UserCreate, UserResponse, UserUpdate

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/", response_model=list[UserResponse])
async def get_all_users(
    db: DatabaseSession,
    _admin: PlatformAdmin,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
):
    return await user_service.get_all_users_from_db(db=db, skip=skip, limit=limit)


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_in: UserCreate, db: DatabaseSession, background: BackgroundTasks
):
    """Register an account and email a verification link."""
    return await user_service.add_new_user_to_db(
        db=db, user_in=user_in, background=background
    )


@router.get("/me", response_model=UserResponse)
async def get_my_profile(current_user: CurrentUser):
    return current_user


@router.patch("/me", response_model=UserResponse)
async def update_my_profile(
    user_in: UserUpdate, db: DatabaseSession, current_user: CurrentUser
):
    return await user_service.update_user_in_db(
        db=db, id=current_user.id, user_in=user_in
    )


@router.get("/{id}", response_model=UserResponse)
async def get_user_by_id(id: UUID, db: DatabaseSession, current_user: CurrentUser):
    user_service.ensure_self_or_admin(current_user, id)
    return await user_service.get_user_from_db_by_id(db=db, id=id)


@router.patch("/{id}", response_model=UserResponse)
async def update_user(
    id: UUID, user_in: UserUpdate, db: DatabaseSession, current_user: CurrentUser
):
    user_service.ensure_self_or_admin(current_user, id)
    return await user_service.update_user_in_db(db=db, id=id, user_in=user_in)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(id: UUID, db: DatabaseSession, current_user: CurrentUser):
    user_service.ensure_self_or_admin(current_user, id)
    await user_service.delete_user_from_db(db=db, id=id)
