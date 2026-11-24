"""One place that tells people things (SRS 4.10).

``notify`` writes an in-app notification and queues an email for each
recipient, both in the recipient's language. It only adds rows to the
session: the caller's commit saves them with the change they describe.
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import email
from app.core.config import settings
from app.core.i18n import t
from app.modules.notifications.models import Notification
from app.modules.users.models import User


def frontend_url(path: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}{path}"


def notify(
    db: AsyncSession,
    background: BackgroundTasks,
    recipients: Iterable[User],
    kind: str,
    *,
    link: str | None = None,
    event_id: UUID | None = None,
    send_email: bool = True,
    in_app: bool = True,
    **params: object,
) -> None:
    """Notify each recipient once; ``kind`` names the ``i18n`` texts used:
    ``<kind>.title`` (in-app message and email subject) and ``<kind>.body``.
    """
    seen: set[UUID] = set()
    for user in recipients:
        if user.id in seen:
            continue
        seen.add(user.id)
        language = user.preferred_language
        title = t(f"{kind}.title", language, **params)
        if in_app:
            db.add(
                Notification(
                    user_id=user.id,
                    kind=kind,
                    message=title[:500],
                    link=link,
                    event_id=event_id,
                )
            )
        if send_email:
            body = t(
                f"{kind}.body",
                language,
                name=user.full_name,
                link=frontend_url(link) if link else "",
                **params,
            )
            background.add_task(email.send_email, user.email, title, body)


async def list_for(
    db: AsyncSession, user: User, unread_only: bool, limit: int
) -> list[Notification]:
    query = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        query = query.where(Notification.is_read.is_(False))
    rows = await db.execute(
        query.order_by(Notification.created_at.desc(), Notification.id).limit(limit)
    )
    return list(rows.scalars().all())


async def unread_count(db: AsyncSession, user: User) -> int:
    return int(
        await db.scalar(
            select(func.count()).where(
                Notification.user_id == user.id, Notification.is_read.is_(False)
            )
        )
        or 0
    )


async def mark_read(
    db: AsyncSession, user: User, notification_id: UUID
) -> Notification:
    notification = await db.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(notification)
    return notification


async def mark_all_read(db: AsyncSession, user: User) -> int:
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        .values(is_read=True, read_at=datetime.now(UTC))
    )
    await db.commit()
    return result.rowcount or 0
