from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.schemas import PlatformSettingsUpdate
from app.modules.audit import service as audit
from app.modules.audit.enums import AuditAction, AuditEntity
from app.modules.platform import service as platform_service
from app.modules.platform.models import PlatformSettings
from app.modules.users.models import User


async def get_settings(db: AsyncSession) -> PlatformSettings:
    return await platform_service.get_settings(db)


async def update_settings(
    db: AsyncSession, admin: User, data_in: PlatformSettingsUpdate
) -> PlatformSettings:
    settings = await platform_service.get_settings(db)
    data = data_in.model_dump(exclude_unset=True, exclude_none=True)
    changed = audit.changes(settings, data)
    if changed:
        audit.record(
            db,
            actor=admin,
            action=AuditAction.SETTINGS_CHANGED,
            entity_type=AuditEntity.PLATFORM_SETTINGS,
            entity_id=None,
            description="Changed platform settings: "
            + ", ".join(field.replace("_", " ") for field in changed),
            details={"changes": changed},
        )
        for field, value in data.items():
            setattr(settings, field, value)
        await db.commit()
        await db.refresh(settings)
    return settings
