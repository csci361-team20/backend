from fastapi import APIRouter

from app.modules.activation.router import router as activation_router
from app.modules.admin.router import reports_router
from app.modules.admin.router import router as admin_router
from app.modules.analytics.router import router as analytics_router
from app.modules.auth.router import router as auth_router
from app.modules.calendar.router import router as calendar_router
from app.modules.checkin.router import router as checkin_router
from app.modules.events.router import router as event_router
from app.modules.notifications.router import router as notification_router
from app.modules.orders.router import router as order_router
from app.modules.organizers.router import router as organizer_router
from app.modules.promotions.router import router as promo_router
from app.modules.seating.router import router as seating_router
from app.modules.support.router import router as support_router
from app.modules.tickets.router import router as ticket_router
from app.modules.users.router import router as user_router

router = APIRouter(prefix="/api/v1")
router.include_router(user_router)
router.include_router(organizer_router)
router.include_router(event_router)
router.include_router(ticket_router)
router.include_router(order_router)
router.include_router(activation_router)
router.include_router(admin_router)
router.include_router(reports_router)
router.include_router(checkin_router)
router.include_router(promo_router)
router.include_router(support_router)
router.include_router(notification_router)
router.include_router(analytics_router)
router.include_router(calendar_router)
router.include_router(seating_router)
router.include_router(auth_router)
