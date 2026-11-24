"""Event images (SRS 4.2): upload, list, remove.

Files are checked by their first bytes, not the name or the browser's
declared type, so only real JPEG, PNG and WebP images are stored.
"""

import uuid
from uuid import UUID

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.storage import get_storage
from app.modules.audit import service as audit
from app.modules.audit.enums import AuditAction, AuditEntity
from app.modules.events import service as event_service
from app.modules.events.models import EventImage
from app.modules.users.models import User

_SIGNATURES = {
    "image/jpeg": ("jpg", lambda b: b.startswith(b"\xff\xd8\xff")),
    "image/png": ("png", lambda b: b.startswith(b"\x89PNG\r\n\x1a\n")),
    "image/webp": ("webp", lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP"),
}


def _detect(content: bytes) -> tuple[str, str] | None:
    for content_type, (extension, matches) in _SIGNATURES.items():
        if matches(content):
            return content_type, extension
    return None


async def _images(db: AsyncSession, event_id: UUID) -> list[EventImage]:
    result = await db.execute(
        select(EventImage)
        .where(EventImage.event_id == event_id)
        .order_by(EventImage.created_at, EventImage.id)
    )
    return list(result.scalars().all())


async def list_images(
    db: AsyncSession, event_id: UUID, actor: User | None
) -> list[EventImage]:
    await event_service.get_visible_event(db, event_id, actor)
    return await _images(db, event_id)


async def add_image(
    db: AsyncSession, event_id: UUID, actor: User, upload: UploadFile
) -> EventImage:
    event = await event_service.get_managed_event(db, event_id, actor)
    count = await db.scalar(
        select(func.count())
        .select_from(EventImage)
        .where(EventImage.event_id == event_id)
    )
    if (count or 0) >= settings.MAX_IMAGES_PER_EVENT:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"An event can have at most {settings.MAX_IMAGES_PER_EVENT} images",
        )

    content = await upload.read(settings.MAX_IMAGE_BYTES + 1)
    if len(content) > settings.MAX_IMAGE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Images can be at most {settings.MAX_IMAGE_BYTES // (1024 * 1024)} MB",
        )
    detected = _detect(content)
    if detected is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Upload a JPEG, PNG or WebP image",
        )
    content_type, extension = detected

    image_id = uuid.uuid4()
    key = f"events/{event_id}/{image_id}.{extension}"
    url = await get_storage().save(key, content, content_type)
    image = EventImage(
        id=image_id,
        event_id=event_id,
        url=url,
        storage_key=key,
        content_type=content_type,
        size_bytes=len(content),
    )
    db.add(image)
    if event.cover_image_url is None:
        event.cover_image_url = url
    audit.record(
        db,
        actor=actor,
        action=AuditAction.EVENT_IMAGE_ADDED,
        entity_type=AuditEntity.EVENT_IMAGE,
        entity_id=image_id,
        event_id=event_id,
        description="Added an image",
        details={"url": url, "size_bytes": len(content)},
    )
    try:
        await db.commit()
    except Exception:
        await get_storage().delete(key)
        raise
    await db.refresh(image)
    return image


async def remove_image(
    db: AsyncSession, event_id: UUID, image_id: UUID, actor: User
) -> None:
    event = await event_service.get_managed_event(db, event_id, actor)
    image = await db.get(EventImage, image_id)
    if image is None or image.event_id != event_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    if event.cover_image_url == image.url:
        # Promote the next image to cover, if there is one
        rest = [i for i in await _images(db, event_id) if i.id != image.id]
        event.cover_image_url = rest[0].url if rest else None
    audit.record(
        db,
        actor=actor,
        action=AuditAction.EVENT_IMAGE_REMOVED,
        entity_type=AuditEntity.EVENT_IMAGE,
        entity_id=image.id,
        event_id=event_id,
        description="Removed an image",
        details={"url": image.url},
    )
    key = image.storage_key
    await db.delete(image)
    await db.commit()
    await get_storage().delete(key)
