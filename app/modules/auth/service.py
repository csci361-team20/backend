from datetime import UTC, datetime, timedelta
from urllib.parse import quote
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import email
from app.core.config import settings
from app.core.i18n import t
from app.core.rate_limit import auth_emails, login_failures
from app.core.security import (
    EMAIL_VERIFICATION_PURPOSE,
    PASSWORD_RESET_PURPOSE,
    REFRESH_PURPOSE,
    create_access_token,
    create_purpose_token,
    decode_purpose_token,
    dummy_password_check,
    fingerprint,
    hash_password,
    token_digest,
    verify_password,
)
from app.modules.auth.models import RevokedRefreshToken
from app.modules.auth.schemas import Token
from app.modules.users import crud as users_crud
from app.modules.users.models import User

_INVALID_LINK = "This link is invalid or has expired"


def _email_key(address: str) -> str:
    return address.strip().lower()


def _too_many(detail: str, retry_after: int) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        detail,
        headers={"Retry-After": str(retry_after)},
    )


def _frontend_link(path: str, token: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}{path}?token={quote(token)}"


def _issue_access_token(user: User) -> str:
    return create_access_token(subject=str(user.id), token_version=user.token_version)


def issue_tokens(user: User) -> Token:
    """An access token plus a refresh token bound to the user's token version,
    so sign-out and password changes revoke both."""
    refresh = create_purpose_token(
        str(user.id),
        REFRESH_PURPOSE,
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        binding=str(user.token_version),
    )
    return Token(
        access_token=_issue_access_token(user),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        refresh_token=refresh,
    )


async def refresh_tokens(db: AsyncSession, refresh_token: str) -> Token:
    decoded = decode_purpose_token(refresh_token, REFRESH_PURPOSE)
    error = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Session expired; sign in again",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if decoded is None:
        raise error
    subject, binding = decoded
    try:
        user = await users_crud.get_by_id(db, UUID(subject))
    except ValueError:
        user = None
    if user is None or binding != fingerprint(str(user.token_version)):
        raise error
    if await db.get(RevokedRefreshToken, token_digest(refresh_token)) is not None:
        raise error
    if user.is_suspended:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is suspended")
    return issue_tokens(user)


async def _get_user_for_token(
    db: AsyncSession, token: str, purpose: str
) -> tuple[User, str]:
    decoded = decode_purpose_token(token, purpose)
    if decoded is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, _INVALID_LINK)
    subject, binding = decoded
    try:
        user = await users_crud.get_by_id(db, UUID(subject))
    except ValueError:
        user = None
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, _INVALID_LINK)
    return user, binding


async def login_for_access_token(db: AsyncSession, email: str, password: str) -> Token:
    key = _email_key(email)
    wait = login_failures.retry_after(key)
    if wait is not None:
        raise _too_many(
            "Too many failed sign-in attempts; try again in a few minutes", wait
        )
    user = await users_crud.get_by_email(db, email)
    if user is None:
        # Same bcrypt work as a real check, so timing does not reveal accounts
        dummy_password_check(password)
    if user is None or not verify_password(password, user.password_hash):
        login_failures.hit(key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.is_suspended:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is suspended")
    login_failures.clear(key)
    return issue_tokens(user)


async def logout_session(db: AsyncSession, refresh_token: str) -> None:
    """Sign out one device: its refresh token stops working. Its access token
    lapses within ACCESS_TOKEN_EXPIRE_MINUTES (the website deletes it at once).
    Unknown or expired tokens are ignored, so signing out never fails."""
    payload = decode_purpose_token(refresh_token, REFRESH_PURPOSE)
    if payload is None:
        return
    expires = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    await db.execute(
        insert(RevokedRefreshToken)
        .values(token_hash=token_digest(refresh_token), expires_at=expires)
        .on_conflict_do_nothing()
    )
    # Housekeeping: rows past their expiry are no longer needed
    await db.execute(
        delete(RevokedRefreshToken).where(
            RevokedRefreshToken.expires_at < datetime.now(UTC)
        )
    )
    await db.commit()


async def logout_everywhere(db: AsyncSession, user: User) -> None:
    """Invalidate every access token issued to this user so far."""
    await users_crud.update(db, user, {"token_version": user.token_version + 1})


def queue_verification_email(user: User, background: BackgroundTasks) -> None:
    token = create_purpose_token(
        str(user.id),
        EMAIL_VERIFICATION_PURPOSE,
        timedelta(hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS),
        binding=user.email,
    )
    link = _frontend_link("/verify-email", token)
    language = user.preferred_language
    background.add_task(
        email.send_email,
        user.email,
        t("verify_email.title", language),
        t(
            "verify_email.body",
            language,
            name=user.full_name,
            link=link,
            hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS,
        ),
    )


async def request_email_verification(user: User, background: BackgroundTasks) -> str:
    if user.is_email_verified:
        return "Your email address is already verified"
    key = f"verify:{user.id}"
    wait = auth_emails.retry_after(key)
    if wait is not None:
        raise _too_many(
            "A verification email was sent recently; check your inbox or try "
            "again in a few minutes",
            wait,
        )
    auth_emails.hit(key)
    queue_verification_email(user, background)
    return "Verification email sent"


async def confirm_email_verification(db: AsyncSession, token: str) -> User:
    user, binding = await _get_user_for_token(db, token, EMAIL_VERIFICATION_PURPOSE)
    # The link only verifies the address it was sent to
    if binding != fingerprint(user.email):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, _INVALID_LINK)
    if user.is_email_verified:
        return user
    return await users_crud.update(db, user, {"email_verified_at": datetime.now(UTC)})


async def request_password_reset(
    db: AsyncSession, email_address: str, background: BackgroundTasks
) -> None:
    """Email a reset link. Unknown emails get the same response (no enumeration)."""
    # Over the limit the response stays the same; the email is just not sent
    key = f"reset:{_email_key(email_address)}"
    if auth_emails.retry_after(key) is not None:
        return
    auth_emails.hit(key)
    user = await users_crud.get_by_email(db, email_address)
    if user is None or user.is_suspended:
        return
    token = create_purpose_token(
        str(user.id),
        PASSWORD_RESET_PURPOSE,
        timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES),
        binding=user.password_hash,
    )
    link = _frontend_link("/reset-password", token)
    language = user.preferred_language
    background.add_task(
        email.send_email,
        user.email,
        t("password_reset.title", language),
        t(
            "password_reset.body",
            language,
            name=user.full_name,
            link=link,
            minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES,
        ),
    )


async def confirm_password_reset(
    db: AsyncSession, token: str, new_password: str
) -> None:
    user, binding = await _get_user_for_token(db, token, PASSWORD_RESET_PURPOSE)
    # Bound to the old hash, so the link stops working once it has been used
    if binding != fingerprint(user.password_hash) or user.is_suspended:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, _INVALID_LINK)
    data: dict = {
        "password_hash": hash_password(new_password),
        "token_version": user.token_version + 1,
    }
    # Receiving the reset email proves the user controls the address
    if not user.is_email_verified:
        data["email_verified_at"] = datetime.now(UTC)
    await users_crud.update(db, user, data)


async def change_password(
    db: AsyncSession, user: User, current_password: str, new_password: str
) -> Token:
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is wrong")
    user = await users_crud.update(
        db,
        user,
        {
            "password_hash": hash_password(new_password),
            "token_version": user.token_version + 1,
        },
    )
    return issue_tokens(user)
