from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import CurrentUser, DatabaseSession
from app.modules.auth import service as auth_service
from app.modules.auth.schemas import (
    MessageResponse,
    PasswordChange,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    Token,
    TokenConfirm,
)
from app.modules.users.schemas import UserResponse

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=Token)
async def login(
    db: DatabaseSession,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
):
    """Sign in with a form body: ``username`` (the email) and ``password``.

    Returns a 30-minute access token and a 14-day refresh token.
    """
    return await auth_service.login_for_access_token(
        db, form_data.username, form_data.password
    )


@router.post("/refresh", response_model=Token)
async def refresh(data_in: RefreshRequest, db: DatabaseSession):
    """Swap a refresh token for a new access token and a new refresh token.

    Keeps long sessions alive (e.g. check-in staff during an event). Sign-out
    and password changes make old refresh tokens stop working.
    """
    return await auth_service.refresh_tokens(db, data_in.refresh_token)


@router.post("/logout-session", status_code=status.HTTP_204_NO_CONTENT)
async def logout_session(data_in: RefreshRequest, db: DatabaseSession):
    """Sign out this device only: the given refresh token stops working.

    Other devices stay signed in. Use ``/auth/logout`` to sign out everywhere.
    """
    await auth_service.logout_session(db, data_in.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(db: DatabaseSession, current_user: CurrentUser):
    """Sign out. Every token issued to this account stops working."""
    await auth_service.logout_everywhere(db, current_user)


@router.post(
    "/verify-email/request",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_email_verification(
    current_user: CurrentUser, background: BackgroundTasks
):
    detail = await auth_service.request_email_verification(current_user, background)
    return MessageResponse(detail=detail)


@router.post("/verify-email/confirm", response_model=UserResponse)
async def confirm_email_verification(data_in: TokenConfirm, db: DatabaseSession):
    return await auth_service.confirm_email_verification(db, data_in.token)


@router.post(
    "/password-reset/request",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_password_reset(
    data_in: PasswordResetRequest, db: DatabaseSession, background: BackgroundTasks
):
    await auth_service.request_password_reset(db, data_in.email, background)
    return MessageResponse(
        detail="If an account exists for this email, a reset link has been sent"
    )


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(data_in: PasswordResetConfirm, db: DatabaseSession):
    """Set a new password. Signs the account out everywhere."""
    await auth_service.confirm_password_reset(db, data_in.token, data_in.new_password)


@router.post("/change-password", response_model=Token)
async def change_password(
    data_in: PasswordChange, db: DatabaseSession, current_user: CurrentUser
):
    """Change the password. Other sessions are signed out and a fresh token is
    returned so this client stays signed in."""
    return await auth_service.change_password(
        db, current_user, data_in.current_password, data_in.new_password
    )
