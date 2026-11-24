"""Event-scoped authorization.

Roles live in ``StaffAssignment`` rows (OWNER, MANAGER, CHECKIN_STAFF per
event), never on the user. Platform admins may bypass most checks.
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.enums import EventStatus, EventVisibility, StaffRole
from app.modules.events.models import Event, StaffAssignment
from app.modules.organizers.models import OrganizerProfile
from app.modules.users.models import User

MANAGE_ROLES = (StaffRole.OWNER, StaffRole.MANAGER)
ALL_STAFF_ROLES = (StaffRole.OWNER, StaffRole.MANAGER, StaffRole.CHECKIN_STAFF)


async def get_staff_role(
    db: AsyncSession, event_id: UUID, user_id: UUID
) -> StaffRole | None:
    result = await db.execute(
        select(StaffAssignment.role).where(
            StaffAssignment.event_id == event_id, StaffAssignment.user_id == user_id
        )
    )
    role = result.scalar_one_or_none()
    return StaffRole(role) if role else None


def is_publicly_visible(event: Event) -> bool:
    """Anyone with the link can view it (public events are also listed).

    A suspended event never is; see also ``organizer_is_suspended``.
    """
    return (
        event.published_at is not None
        and event.status != EventStatus.DRAFT
        and event.visibility in (EventVisibility.PUBLIC, EventVisibility.UNLISTED)
        and not event.is_suspended
    )


async def organizer_is_suspended(db: AsyncSession, event: Event) -> bool:
    """Events of a suspended organizer leave public view (SRS 4.12)."""
    suspended = await db.scalar(
        select(User.is_suspended)
        .join(OrganizerProfile, OrganizerProfile.user_id == User.id)
        .where(OrganizerProfile.id == event.organizer_profile_id)
    )
    return bool(suspended)


async def can_view_event(db: AsyncSession, event: Event, user: User | None) -> bool:
    if is_publicly_visible(event) and not await organizer_is_suspended(db, event):
        return True
    if user is None:
        return False
    if user.is_platform_admin:
        return True
    return await get_staff_role(db, event.id, user.id) is not None


async def ensure_can_view_event(
    db: AsyncSession, event: Event, user: User | None
) -> None:
    # 404 rather than 403 so private and draft events are not revealed
    if not await can_view_event(db, event, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")


async def ensure_event_role(
    db: AsyncSession,
    event: Event,
    user: User,
    allowed: tuple[StaffRole, ...],
    *,
    allow_platform_admin: bool = True,
) -> StaffRole | None:
    """Return the user's role on the event, or raise if it is not allowed.

    Returns None when access was granted through the platform-admin bypass.
    """
    role = await get_staff_role(db, event.id, user.id)
    if role in allowed:
        return role
    if allow_platform_admin and user.is_platform_admin:
        return None
    if role is None and not await can_view_event(db, event, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    raise HTTPException(
        status.HTTP_403_FORBIDDEN, "You do not have permission for this event"
    )
