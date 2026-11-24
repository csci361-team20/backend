"""Write and read the audit log.

``record`` only adds the entry to the session: it is saved by the same
commit as the change it describes, so the log never claims something that
was rolled back.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.enums import AuditAction, AuditEntity
from app.modules.audit.models import AuditLog
from app.modules.users.models import User


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


def changes(before: Any, after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``{field: {"from": old, "to": new}}`` for the fields that really change."""
    return {
        field: {"from": _jsonable(getattr(before, field)), "to": _jsonable(new)}
        for field, new in after.items()
        if getattr(before, field) != new
    }


def record(
    db: AsyncSession,
    *,
    actor: User | None,
    action: AuditAction,
    entity_type: AuditEntity,
    entity_id: UUID | None,
    description: str,
    event_id: UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor.id if actor else None,
            actor_name=actor.full_name if actor else None,
            event_id=event_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            description=description[:500],
            details=_jsonable(details or {}),
        )
    )


async def get_event_activity(
    db: AsyncSession,
    event_id: UUID,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    actions: list[AuditAction] | None = None,
    area: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[AuditLog]:
    query = select(AuditLog).where(AuditLog.event_id == event_id)
    if since:
        query = query.where(AuditLog.created_at >= since)
    if until:
        query = query.where(AuditLog.created_at < until)
    if actions:
        query = query.where(AuditLog.action.in_(actions))
    if area:
        query = query.where(AuditLog.action.startswith(f"{area}."))
    result = await db.execute(
        query.order_by(AuditLog.created_at.desc(), AuditLog.id)
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all())
