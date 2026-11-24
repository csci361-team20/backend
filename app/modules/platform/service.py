from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform.models import SETTINGS_ROW_ID, PlatformSettings


async def get_settings(db: AsyncSession) -> PlatformSettings:
    """The settings row, created with defaults the first time it is read."""
    settings = await db.get(PlatformSettings, SETTINGS_ROW_ID)
    if settings is None:
        await db.execute(
            insert(PlatformSettings)
            .values(id=SETTINGS_ROW_ID)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await db.commit()
        settings = await db.get(PlatformSettings, SETTINGS_ROW_ID)
    assert settings is not None
    return settings
