from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Query, UploadFile, status

from app.api.deps import CurrentUser, DatabaseSession, OptionalUser, VerifiedUser
from app.modules.audit.enums import ActivityArea, AuditAction
from app.modules.audit.schemas import AuditEntryResponse
from app.modules.events import images as event_images
from app.modules.events import service as event_service
from app.modules.events.enums import EventLifecycle, StaffRole
from app.modules.events.schemas import (
    EventCreate,
    EventImageResponse,
    EventPreviewResponse,
    EventResponse,
    EventSort,
    EventUpdate,
    MyEventResponse,
    PublicEventListItem,
    StaffAssignmentCreate,
    StaffAssignmentResponse,
)

router = APIRouter(prefix="/events", tags=["Events"])


@router.post("/", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(data_in: EventCreate, db: DatabaseSession, actor: VerifiedUser):
    """Create a draft event owned by the signed-in user (verified email
    required). Creates their organizer profile on the first event."""
    return await event_service.create_event(db=db, actor=actor, data_in=data_in)


@router.get("/", response_model=list[PublicEventListItem])
async def get_public_events(
    db: DatabaseSession,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    city: str | None = None,
    category: str | None = None,
    q: str | None = Query(None, max_length=100, description="Title, subtitle, venue"),
    starts_from: datetime | None = None,
    starts_to: datetime | None = None,
    include_past: bool = False,
    sort: EventSort = EventSort.START_ASC,
):
    """Published, public events. Unlisted and private events are not listed,
    and events that have ended are left out unless ``include_past`` is set."""
    return await event_service.get_public_events(
        db=db,
        skip=skip,
        limit=limit,
        city=city,
        category=category,
        q=q,
        starts_from=starts_from,
        starts_to=starts_to,
        include_past=include_past,
        sort=sort,
    )


@router.get("/mine", response_model=list[MyEventResponse])
async def get_my_events(
    db: DatabaseSession,
    actor: CurrentUser,
    role: StaffRole | None = None,
    lifecycle: EventLifecycle | None = None,
):
    """Events the signed-in user owns or manages, newest first.

    Pass ``role=checkin_staff`` for the check-in app's assigned-events list
    (or ``role=owner`` / ``role=manager`` to narrow the default). Filter by
    ``lifecycle`` for the Upcoming / Active / Completed / Cancelled tabs.
    """
    return await event_service.get_my_events(
        db=db, actor=actor, role=role, lifecycle=lifecycle
    )


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(event_id: UUID, db: DatabaseSession, actor: OptionalUser):
    """Public and unlisted events are open to anyone; drafts and private
    events only to the event team and platform admins."""
    return await event_service.get_visible_event(db=db, id=event_id, actor=actor)


@router.patch("/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: UUID,
    data_in: EventUpdate,
    db: DatabaseSession,
    actor: CurrentUser,
    background: BackgroundTasks,
):
    """Owner or manager. Changes to date, time, venue or time zone of a
    published event are sent to ticket holders."""
    return await event_service.update_event(
        db=db, id=event_id, actor=actor, data_in=data_in, background=background
    )


@router.post("/{event_id}/publish", response_model=EventResponse)
async def publish_event(event_id: UUID, db: DatabaseSession, actor: CurrentUser):
    return await event_service.publish_event(db=db, id=event_id, actor=actor)


@router.post("/{event_id}/unpublish", response_model=EventResponse)
async def unpublish_event(event_id: UUID, db: DatabaseSession, actor: CurrentUser):
    """Back to draft. Not allowed once attendees have orders; cancel instead."""
    return await event_service.unpublish_event(db=db, id=event_id, actor=actor)


@router.post(
    "/{event_id}/duplicate",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_event(event_id: UUID, db: DatabaseSession, actor: VerifiedUser):
    """New draft with the same details and ticket types, owned by you.

    Orders, tickets, staff and support cases are not copied.
    """
    return await event_service.duplicate_event(db=db, id=event_id, actor=actor)


@router.get("/{event_id}/preview", response_model=EventPreviewResponse)
async def preview_event(event_id: UUID, db: DatabaseSession, actor: CurrentUser):
    """The event page as attendees will see it, including for drafts.

    Event team only.
    """
    return await event_service.preview_event(db=db, id=event_id, actor=actor)


@router.post("/{event_id}/cancel", response_model=EventResponse)
async def cancel_event(
    event_id: UUID,
    db: DatabaseSession,
    actor: CurrentUser,
    background: BackgroundTasks,
):
    """Owner only. Refunds every paid order in full (simulated), voids free
    tickets, closes open checkouts and emails ticket holders."""
    return await event_service.cancel_event(
        db=db, id=event_id, actor=actor, background=background
    )


@router.get("/{event_id}/staff", response_model=list[StaffAssignmentResponse])
async def get_event_staff(event_id: UUID, db: DatabaseSession, actor: CurrentUser):
    return await event_service.get_event_staff(db=db, event_id=event_id, actor=actor)


@router.post(
    "/{event_id}/staff",
    response_model=StaffAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_event_staff(
    event_id: UUID,
    data_in: StaffAssignmentCreate,
    db: DatabaseSession,
    actor: CurrentUser,
):
    """Add a registered user by email. Owners can add managers and check-in
    staff; managers can add check-in staff."""
    return await event_service.add_event_staff(
        db=db, event_id=event_id, actor=actor, data_in=data_in
    )


@router.delete("/{event_id}/staff/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_event_staff(
    event_id: UUID, user_id: UUID, db: DatabaseSession, actor: CurrentUser
):
    await event_service.remove_event_staff(
        db=db, event_id=event_id, user_id=user_id, actor=actor
    )


@router.get("/{event_id}/activity", response_model=list[AuditEntryResponse])
async def get_event_activity(
    event_id: UUID,
    db: DatabaseSession,
    actor: CurrentUser,
    since: datetime | None = None,
    until: datetime | None = None,
    area: ActivityArea | None = None,
    action: Annotated[list[AuditAction] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """The event's activity timeline, newest first (SRS 4.16).

    Filter by date range, by ``area`` (event, staff, ticket_type, order,
    payment, refund, promo, support, check_in, activation) or by exact
    ``action`` (repeatable). Owner, manager or platform admin. Entries cannot
    be edited or deleted.
    """
    return await event_service.get_event_activity(
        db=db,
        id=event_id,
        actor=actor,
        since=since,
        until=until,
        area=area,
        actions=action,
        limit=limit,
        offset=offset,
    )


@router.get("/{event_id}/images", response_model=list[EventImageResponse])
async def list_event_images(event_id: UUID, db: DatabaseSession, actor: OptionalUser):
    """Images in upload order. Anyone who can see the event."""
    return await event_images.list_images(db=db, event_id=event_id, actor=actor)


@router.post(
    "/{event_id}/images",
    response_model=EventImageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_event_image(
    event_id: UUID, file: UploadFile, db: DatabaseSession, actor: CurrentUser
):
    """Upload a JPEG, PNG or WebP image (max 5 MB, 10 per event).

    The first image becomes the cover unless one is set. Owner or manager.
    """
    return await event_images.add_image(
        db=db, event_id=event_id, actor=actor, upload=file
    )


@router.delete("/{event_id}/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_event_image(
    event_id: UUID, image_id: UUID, db: DatabaseSession, actor: CurrentUser
):
    """Owner or manager. Removing the cover promotes the next image."""
    await event_images.remove_image(
        db=db, event_id=event_id, image_id=image_id, actor=actor
    )
