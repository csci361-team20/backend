from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.users.models import User


# Dummy get_user dependency
async def get_current_user() -> User:
    pass


CurrentUser = Annotated[User, Depends(get_current_user)]

# DB Session dependency
DatabaseSession = Annotated[AsyncSession, Depends(get_db)]
