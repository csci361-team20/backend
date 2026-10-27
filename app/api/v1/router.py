from fastapi import APIRouter

from app.modules.events.router import router as event_router
from app.modules.organizers.router import router as organizer_router
from app.modules.users.router import router as user_router

router = APIRouter(prefix="/api/v1")
router.include_router(user_router)
router.include_router(organizer_router)
router.include_router(event_router)
