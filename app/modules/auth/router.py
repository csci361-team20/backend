from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import DatabaseSession
from app.modules.auth import service as auth_service
from app.modules.auth.schemas import Token

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=Token)
async def login(
    db: DatabaseSession,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
):
    access_token = await auth_service.login_for_access_token(
        db, form_data.username, form_data.password
    )
    return Token(access_token=access_token)
