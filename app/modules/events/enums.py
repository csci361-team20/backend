from datetime import UTC, datetime
from enum import StrEnum


class EventStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class EventVisibility(StrEnum):
    PUBLIC = "public"
    UNLISTED = "unlisted"
    PRIVATE = "private"


class SeatingType(StrEnum):
    GENERAL_ADMISSION = "general_admission"
    ASSIGNED = "assigned"


class StaffRole(StrEnum):
    OWNER = "owner"
    MANAGER = "manager"
    CHECKIN_STAFF = "checkin_staff"
    # Answers attendee support cases for this event (SRS 4.13)
    SUPPORT_STAFF = "support_staff"


class EventLifecycle(StrEnum):
    DRAFT = "draft"
    UPCOMING = "upcoming"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


def compute_lifecycle(
    status: str, start_at: datetime, end_at: datetime, now: datetime | None = None
) -> EventLifecycle:
    now = now or datetime.now(UTC)
    if status == EventStatus.CANCELLED:
        return EventLifecycle.CANCELLED
    if status == EventStatus.COMPLETED or end_at <= now:
        return EventLifecycle.COMPLETED
    if status == EventStatus.DRAFT:
        return EventLifecycle.DRAFT
    if start_at <= now:
        return EventLifecycle.ACTIVE
    return EventLifecycle.UPCOMING
