import uuid
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from app.api.deps import CurrentUser, DatabaseSession
from app.modules.notifications import service as notification_service

router = APIRouter(prefix="/notifications", tags=["Notifications"])


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    message: str
    link: str | None
    event_id: uuid.UUID | None
    is_read: bool
    read_at: datetime | None
    created_at: datetime


class UnreadCount(BaseModel):
    unread: int


@router.get("", response_model=list[NotificationResponse])
async def list_notifications(
    db: DatabaseSession,
    actor: CurrentUser,
    unread_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
):
    """Your notifications, newest first, in your preferred language."""
    return await notification_service.list_for(db, actor, unread_only, limit)


@router.get("/unread-count", response_model=UnreadCount)
async def unread_count(db: DatabaseSession, actor: CurrentUser):
    """For the bell badge; cheap enough to poll."""
    return UnreadCount(unread=await notification_service.unread_count(db, actor))


@router.post("/{notification_id}/read", response_model=NotificationResponse)
async def mark_read(notification_id: UUID, db: DatabaseSession, actor: CurrentUser):
    return await notification_service.mark_read(db, actor, notification_id)


@router.post("/read-all", response_model=UnreadCount)
async def mark_all_read(db: DatabaseSession, actor: CurrentUser):
    """Marks everything read; returns how many changed."""
    return UnreadCount(unread=await notification_service.mark_all_read(db, actor))
