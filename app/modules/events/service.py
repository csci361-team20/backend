from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import t
from app.core.timezones import format_local
from app.modules.audit import service as audit
from app.modules.audit.enums import ActivityArea, AuditAction, AuditEntity
from app.modules.audit.models import AuditLog
from app.modules.events import crud
from app.modules.events.enums import EventLifecycle, EventStatus, StaffRole
from app.modules.events.models import Event
from app.modules.events.permissions import (
    ALL_STAFF_ROLES,
    MANAGE_ROLES,
    ensure_can_view_event,
    ensure_event_role,
)
from app.modules.events.schemas import (
    EventCreate,
    EventPreviewResponse,
    EventResponse,
    EventSort,
    EventUpdate,
    MyEventResponse,
    PublicEventListItem,
    StaffAssignmentCreate,
    StaffAssignmentResponse,
    _check_windows,
)
from app.modules.notifications.service import notify
from app.modules.orders import refunds as refunds_service
from app.modules.organizers import crud as organizer_crud
from app.modules.organizers import service as organizer_service
from app.modules.tickets import crud as tickets_crud
from app.modules.tickets import inventory
from app.modules.tickets.schemas import SaleStatus
from app.modules.users import crud as users_crud
from app.modules.users.models import User

_WINDOW_FIELDS = (
    "start_at",
    "end_at",
    "registration_opens_at",
    "registration_closes_at",
)
# Optional columns an explicit null may clear; required ones ignore nulls
_CLEARABLE_FIELDS = {
    "subtitle",
    "description",
    "cover_image_url",
    "registration_opens_at",
    "registration_closes_at",
    "venue_name",
    "venue_address",
    "city",
    "category",
    "refund_policy",
}
_COPIED_EVENT_FIELDS = (
    "subtitle",
    "description",
    "cover_image_url",
    "visibility",
    "seating_type",
    "start_at",
    "end_at",
    "capacity",
    "registration_opens_at",
    "registration_closes_at",
    "venue_name",
    "venue_address",
    "city",
    "category",
    "timezone",
    "refund_policy",
    "venue_layout_id",
)
_COPIED_TICKET_FIELDS = (
    "name",
    "description",
    "price_kzt",
    "quantity",
    "max_per_order",
    "sale_start",
    "sale_end",
    "is_hidden",
    "seat_category",
)


# Details shown in calendar files (SRS 4.11)
_CALENDAR_FIELDS = (
    "title",
    "subtitle",
    "description",
    "start_at",
    "end_at",
    "venue_name",
    "venue_address",
    "city",
    "timezone",
)

# Changes ticket holders hear about (SRS 4.10 "event updates")
_NOTIFY_ON_CHANGE = (
    "start_at",
    "end_at",
    "venue_name",
    "venue_address",
    "city",
    "timezone",
)


async def _notify_holders_of_update(
    db: AsyncSession, background: BackgroundTasks, event: Event, changes: dict
) -> None:
    holders = await users_crud.get_by_ids(
        db, await crud.get_ticket_holder_ids(db, event.id)
    )
    timezone = changes.get("timezone", event.timezone)
    by_language: dict[str, list[User]] = {}
    for holder in holders:
        by_language.setdefault(holder.preferred_language, []).append(holder)
    for language, group in by_language.items():
        lines = []
        for field, value in changes.items():
            if isinstance(value, datetime):
                value = format_local(value, timezone)
            lines.append("- " + t(f"change.{field}", language, value=value or "—"))
        notify(
            db,
            background,
            group,
            "event_updated",
            link=f"/events/{event.id}",
            event_id=event.id,
            event=event.title,
            changes="\n".join(lines),
        )


async def create_event(db: AsyncSession, actor: User, data_in: EventCreate) -> Event:
    # The first event turns the user into an organizer
    profile = await organizer_service.get_or_create_profile(db, actor)
    event_id = uuid4()
    _log(db, actor, AuditAction.EVENT_CREATED, event_id, f"Created {data_in.title}")
    return await crud.create_with_owner(
        db,
        {**data_in.model_dump(), "id": event_id, "organizer_profile_id": profile.id},
        actor.id,
    )


def _log(
    db: AsyncSession,
    actor: User | None,
    action: AuditAction,
    event_id: UUID,
    description: str,
    details: dict | None = None,
) -> None:
    audit.record(
        db,
        actor=actor,
        action=action,
        entity_type=AuditEntity.EVENT,
        entity_id=event_id,
        event_id=event_id,
        description=description,
        details=details,
    )


async def get_event(db: AsyncSession, id: UUID) -> Event:
    """Load an event with no access check. Callers must authorize."""
    event = await crud.get_by_id(db, id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return event


async def get_visible_event(db: AsyncSession, id: UUID, actor: User | None) -> Event:
    event = await get_event(db, id)
    await ensure_can_view_event(db, event, actor)
    return event


async def get_managed_event(
    db: AsyncSession,
    id: UUID,
    actor: User,
    allowed: tuple[StaffRole, ...] = MANAGE_ROLES,
) -> Event:
    event = await get_event(db, id)
    await ensure_event_role(db, event, actor, allowed)
    return event


async def get_public_events(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
    city: str | None = None,
    category: str | None = None,
    q: str | None = None,
    starts_from: datetime | None = None,
    starts_to: datetime | None = None,
    include_past: bool = False,
    sort: EventSort = EventSort.START_ASC,
) -> list[PublicEventListItem]:
    events = await crud.get_all_public(
        db, skip, limit, city, category, q, starts_from, starts_to, include_past, sort
    )
    return await _list_items(db, events)


async def _list_items(
    db: AsyncSession, events: list[Event]
) -> list[PublicEventListItem]:
    """Add the organizer name, starting price and places left to each event,
    with one query each for ticket types, stock and organizers."""
    if not events:
        return []
    by_event = await crud.get_visible_ticket_types(db, [e.id for e in events])
    stock = await tickets_crud.get_inventory(
        db, [t.id for types in by_event.values() for t in types]
    )
    names = await crud.get_organizer_names(db, {e.organizer_profile_id for e in events})
    now = datetime.now(UTC)
    items = []
    for event in events:
        types = by_event.get(event.id, [])
        statuses = {
            t.id: inventory.compute_sale_status(
                t, event, stock[t.id].available(t.quantity), now
            )
            for t in types
        }
        selling = [t for t in types if statuses[t.id] == SaleStatus.ON_SALE]
        # The most hopeful state across the event's ticket types
        sale_state = next(
            (
                state
                for state in (
                    SaleStatus.ON_SALE,
                    SaleStatus.SCHEDULED,
                    SaleStatus.SOLD_OUT,
                    SaleStatus.ENDED,
                )
                if state in statuses.values()
            ),
            None,
        )
        items.append(
            PublicEventListItem.model_validate(
                {
                    **_event_fields(event),
                    "lifecycle": event.lifecycle,
                    "paid_sales_open": event.paid_sales_open,
                    "organizer_name": names.get(event.organizer_profile_id, ""),
                    "price_from_kzt": min((t.price_kzt for t in types), default=None),
                    "tickets_available": sum(
                        stock[t.id].available(t.quantity) for t in selling
                    ),
                    "sale_state": sale_state,
                }
            )
        )
    return items


async def get_my_events(
    db: AsyncSession,
    actor: User,
    role: StaffRole | None = None,
    lifecycle: EventLifecycle | None = None,
) -> list[MyEventResponse]:
    # Default to the organizer dashboard view; the check-in app asks for its role
    roles = (role,) if role else MANAGE_ROLES
    rows = await crud.get_for_staff_user(db, actor.id, roles)
    return [
        MyEventResponse.model_validate(
            {
                **_event_fields(event),
                "lifecycle": event.lifecycle,
                "paid_sales_open": event.paid_sales_open,
                "my_role": role_value,
            }
        )
        for event, role_value in rows
        if lifecycle is None or event.lifecycle == lifecycle
    ]


def _event_fields(event: Event) -> dict:
    return {
        column.key: getattr(event, column.key) for column in Event.__mapper__.columns
    }


async def update_event(
    db: AsyncSession,
    id: UUID,
    actor: User,
    data_in: EventUpdate,
    background: BackgroundTasks | None = None,
) -> Event:
    event = await get_managed_event(db, id, actor)
    if event.status in (EventStatus.CANCELLED, EventStatus.COMPLETED):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cancelled or completed events cannot be edited",
        )
    data = {
        key: value
        for key, value in data_in.model_dump(exclude_unset=True).items()
        if value is not None or key in _CLEARABLE_FIELDS
    }
    merged = [data.get(key, getattr(event, key)) for key in _WINDOW_FIELDS]
    try:
        _check_windows(*merged)
    except ValueError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from None

    if "capacity" in data:
        allocated = await tickets_crud.get_total_quantity(db, event.id)
        if data["capacity"] < allocated:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Ticket types already hold {allocated} places; "
                "capacity cannot be lower",
            )
    changed = audit.changes(event, data)
    if any(field in _CALENDAR_FIELDS for field in changed):
        data["calendar_sequence"] = event.calendar_sequence + 1
    if changed:
        _log(
            db,
            actor,
            AuditAction.EVENT_UPDATED,
            event.id,
            "Changed " + ", ".join(field.replace("_", " ") for field in changed),
            {"changes": changed},
        )
    notable = {f: data[f] for f in changed if f in _NOTIFY_ON_CHANGE}
    if notable and event.status == EventStatus.PUBLISHED and background is not None:
        await _notify_holders_of_update(db, background, event, notable)
    return await crud.update(db, event, data)


async def publish_event(db: AsyncSession, id: UUID, actor: User) -> Event:
    event = await get_managed_event(db, id, actor)
    if event.status != EventStatus.DRAFT:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Only draft events can be published"
        )
    if event.lifecycle == EventLifecycle.COMPLETED:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "An event that has ended cannot be published"
        )
    if await tickets_crud.count_by_event(db, event.id) == 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Add at least one ticket type before publishing",
        )
    data: dict = {"status": EventStatus.PUBLISHED}
    if event.published_at is None:
        data["published_at"] = datetime.now(UTC)
    _log(db, actor, AuditAction.EVENT_PUBLISHED, event.id, "Published the event")
    return await crud.update(db, event, data)


async def unpublish_event(db: AsyncSession, id: UUID, actor: User) -> Event:
    """Back to draft, hidden from attendees. Only before anyone has ordered."""
    event = await get_managed_event(db, id, actor)
    if event.status != EventStatus.PUBLISHED:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Only published events can be unpublished"
        )
    if await crud.has_live_orders(db, event.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Attendees already have orders for this event; cancel it instead",
        )
    _log(db, actor, AuditAction.EVENT_UNPUBLISHED, event.id, "Unpublished the event")
    return await crud.update(db, event, {"status": EventStatus.DRAFT})


async def duplicate_event(db: AsyncSession, id: UUID, actor: User) -> Event:
    """Copy an event's configuration into a new draft owned by the actor.

    Orders, tickets, payments, check-ins, staff and support cases are not
    copied (SRS 4.16).
    """
    source = await get_managed_event(db, id, actor)
    profile = await organizer_service.get_or_create_profile(db, actor)
    data = {key: getattr(source, key) for key in _COPIED_EVENT_FIELDS}
    data["title"] = (source.title + " (copy)")[:255]
    data["organizer_profile_id"] = profile.id
    data["id"] = uuid4()
    _log(
        db,
        actor,
        AuditAction.EVENT_DUPLICATED,
        data["id"],
        f"Created as a copy of {source.title}",
        {"source_event_id": source.id},
    )
    source_types = await tickets_crud.get_by_event(db, source.id, include_hidden=True)
    ticket_types = [
        {key: getattr(t, key) for key in _COPIED_TICKET_FIELDS} for t in source_types
    ]
    return await crud.create_copy(db, data, actor.id, ticket_types)


async def preview_event(
    db: AsyncSession, id: UUID, actor: User
) -> EventPreviewResponse:
    event = await get_managed_event(db, id, actor, allowed=ALL_STAFF_ROLES)
    profile = await organizer_crud.get_by_id(db, event.organizer_profile_id)
    ticket_types = await tickets_crud.get_by_event(db, event.id, include_hidden=False)
    return EventPreviewResponse(
        event=EventResponse.model_validate(event),
        organizer_name=profile.display_name if profile else "",
        ticket_types=await inventory.build_responses(db, event, ticket_types),
    )


async def cancel_event(
    db: AsyncSession, id: UUID, actor: User, background: BackgroundTasks
) -> Event:
    """Cancel the event: refund paid orders, void free tickets, close open
    checkouts and email the ticket holders. Owner only: it is destructive."""
    event = await get_managed_event(db, id, actor, allowed=(StaffRole.OWNER,))
    if event.status not in (EventStatus.DRAFT, EventStatus.PUBLISHED):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Only draft or published events can be cancelled",
        )
    # Paid orders are refunded in full first (SRS 4.9); free tickets are voided
    refunds = await refunds_service.refund_all_for_event(
        db, event, actor, f"{event.title} was cancelled by the organizer"
    )
    buyer_ids = await crud.cancel_event_orders(db, event.id)
    summary = []
    if refunds:
        summary.append(f"refunded {len(refunds)} paid orders")
    if buyer_ids:
        summary.append(f"voided free tickets of {len(buyer_ids)} buyers")
    _log(
        db,
        actor,
        AuditAction.EVENT_CANCELLED,
        event.id,
        "Cancelled the event" + (f"; {', '.join(summary)}" if summary else ""),
        {
            "refunded_orders": len(refunds),
            "refunded_kzt": sum(r.amount_kzt for r in refunds),
            "notified_buyers": len(buyer_ids),
        },
    )
    for notice in refunds:
        refunds_service.notify_refund(db, background, notice)
    notify(
        db,
        background,
        await users_crud.get_by_ids(db, buyer_ids),
        "event_cancelled",
        link=f"/events/{event.id}",
        event_id=event.id,
        event=event.title,
        when=format_local(event.start_at, event.timezone),
    )
    return await crud.update(
        db,
        event,
        {
            "status": EventStatus.CANCELLED,
            "calendar_sequence": event.calendar_sequence + 1,
        },
    )


# --- Staff ----------------------------------------------------------------


def _staff_response(assignment, user: User) -> StaffAssignmentResponse:
    return StaffAssignmentResponse(
        id=assignment.id,
        event_id=assignment.event_id,
        user_id=assignment.user_id,
        role=assignment.role,
        full_name=user.full_name,
        email=user.email,
    )


def _ensure_can_manage_role(actor_role: StaffRole | None, target: StaffRole) -> None:
    """Owners manage everyone; managers only check-in and support staff.

    ``actor_role`` is None for platform admins, who may manage anyone.
    """
    if target == StaffRole.OWNER:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "The event owner cannot be changed here"
        )
    if actor_role == StaffRole.MANAGER and target not in (
        StaffRole.CHECKIN_STAFF,
        StaffRole.SUPPORT_STAFF,
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Managers can only manage check-in and support staff",
        )


async def get_event_staff(
    db: AsyncSession, event_id: UUID, actor: User
) -> list[StaffAssignmentResponse]:
    await get_managed_event(db, event_id, actor)
    return [_staff_response(a, u) for a, u in await crud.get_staff(db, event_id)]


async def add_event_staff(
    db: AsyncSession, event_id: UUID, actor: User, data_in: StaffAssignmentCreate
) -> StaffAssignmentResponse:
    event = await get_event(db, event_id)
    actor_role = await ensure_event_role(db, event, actor, MANAGE_ROLES)
    target_role = StaffRole(data_in.role)
    _ensure_can_manage_role(actor_role, target_role)

    user = await users_crud.get_by_email(db, data_in.email)
    if user is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No BiletFlow account uses this email. Ask them to register first.",
        )
    if user.is_suspended:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This account is suspended")
    if await crud.get_staff_assignment(db, event_id, user.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This person is already on the event team"
        )
    audit.record(
        db,
        actor=actor,
        action=AuditAction.STAFF_ADDED,
        entity_type=AuditEntity.STAFF_ASSIGNMENT,
        entity_id=user.id,
        event_id=event_id,
        description=f"Added {user.full_name} as {target_role.replace('_', ' ')}",
        details={"user_id": user.id, "role": target_role},
    )
    try:
        assignment = await crud.create_staff_assignment(
            db, event_id, user.id, target_role
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This person is already on the event team"
        ) from None
    return _staff_response(assignment, user)


async def remove_event_staff(
    db: AsyncSession, event_id: UUID, user_id: UUID, actor: User
) -> None:
    event = await get_event(db, event_id)
    actor_role = await ensure_event_role(db, event, actor, MANAGE_ROLES)
    assignment = await crud.get_staff_assignment(db, event_id, user_id)
    if assignment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Staff member not found")
    _ensure_can_manage_role(actor_role, StaffRole(assignment.role))
    member = await users_crud.get_by_id(db, user_id)
    audit.record(
        db,
        actor=actor,
        action=AuditAction.STAFF_REMOVED,
        entity_type=AuditEntity.STAFF_ASSIGNMENT,
        entity_id=user_id,
        event_id=event_id,
        description=f"Removed {member.full_name if member else 'a member'} "
        f"({assignment.role.replace('_', ' ')})",
        details={"user_id": user_id, "role": assignment.role},
    )
    await crud.delete_staff_assignment(db, assignment)


async def get_event_activity(
    db: AsyncSession,
    id: UUID,
    actor: User,
    since: datetime | None = None,
    until: datetime | None = None,
    area: ActivityArea | None = None,
    actions: list[AuditAction] | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[AuditLog]:
    """The event's timeline, newest first (SRS 4.16). Owner, manager or admin."""
    await get_managed_event(db, id, actor)
    return await audit.get_event_activity(
        db,
        id,
        since=since,
        until=until,
        actions=actions,
        area=area.value if area else None,
        limit=limit,
        offset=offset,
    )
