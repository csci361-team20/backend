from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_payload
from app.modules.users import crud as users_crud
from app.modules.users.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
optional_oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login", auto_error=False
)

DatabaseSession = Annotated[AsyncSession, Depends(get_db)]


def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _resolve_user(token: str, db: AsyncSession) -> User:
    payload = decode_access_payload(token)
    if payload is None:
        raise _credentials_exception()
    try:
        user = await users_crud.get_by_id(db, UUID(payload["sub"]))
    except ValueError:
        raise _credentials_exception() from None
    # A token issued before sign-out / password change carries an old version
    if user is None or payload.get("ver", 0) != user.token_version:
        raise _credentials_exception()
    if user.is_suspended:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is suspended")
    return user


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], db: DatabaseSession
) -> User:
    return await _resolve_user(token, db)


async def get_optional_user(
    token: Annotated[str | None, Depends(optional_oauth2_scheme)],
    db: DatabaseSession,
) -> User | None:
    """The signed-in user, or None for anonymous requests.

    An expired or invalid token is treated as anonymous, so public pages keep
    working for a visitor whose session has lapsed.
    """
    if token is None:
        return None
    try:
        return await _resolve_user(token, db)
    except HTTPException:
        return None


async def get_verified_user(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not user.is_email_verified:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Verify your email address to continue"
        )
    return user


async def get_platform_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not user.is_platform_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Platform administrator access is required"
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
VerifiedUser = Annotated[User, Depends(get_verified_user)]
PlatformAdmin = Annotated[User, Depends(get_platform_admin)]
