from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Query, Response, status

from app.api.deps import CurrentUser, DatabaseSession
from app.modules.orders import refunds as refunds_service
from app.modules.orders import service as order_service
from app.modules.orders import tickets as tickets_service
from app.modules.orders.enums import OrderStatus
from app.modules.orders.schemas import (
    EventAttendeeResponse,
    EventRefundResponse,
    EventSalesSummary,
    OrderCreate,
    OrderResponse,
    PaymentCreate,
    RefundCreate,
    RegistrationCancel,
    TicketDetailResponse,
)

router = APIRouter(tags=["Orders"])


@router.post(
    "/events/{event_id}/orders",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_order(
    event_id: UUID,
    data_in: OrderCreate,
    db: DatabaseSession,
    actor: CurrentUser,
    background: BackgroundTasks,
):
    """Start checkout.

    Free orders come back ``confirmed`` with tickets issued. Paid orders come
    back ``pending``: the places are held until ``expires_at``; pay with
    ``POST /orders/{id}/pay``.
    """
    return await order_service.create_order(
        db=db, event_id=event_id, actor=actor, data_in=data_in, background=background
    )


@router.get("/orders/mine", response_model=list[OrderResponse])
async def get_my_orders(db: DatabaseSession, actor: CurrentUser):
    """Your orders, newest first."""
    return await order_service.get_my_orders(db=db, actor=actor)


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(order_id: UUID, db: DatabaseSession, actor: CurrentUser):
    """The buyer, the event's owner and managers, or a platform admin."""
    return await order_service.get_order(db=db, order_id=order_id, actor=actor)


@router.post("/orders/{order_id}/pay", response_model=OrderResponse)
async def pay_order(
    order_id: UUID,
    data_in: PaymentCreate,
    db: DatabaseSession,
    actor: CurrentUser,
    background: BackgroundTasks,
):
    """Simulated payment; no real money moves and no card details are taken.

    ``outcome=failure`` records a failed attempt and keeps the hold.
    """
    return await order_service.pay_order(
        db=db, order_id=order_id, actor=actor, data_in=data_in, background=background
    )


@router.post("/orders/{order_id}/cancel", response_model=OrderResponse)
async def cancel_order(order_id: UUID, db: DatabaseSession, actor: CurrentUser):
    """Abandon an unpaid checkout and release its places. Paid orders are
    cancelled through refunds."""
    return await order_service.cancel_pending_order(
        db=db, order_id=order_id, actor=actor
    )


@router.get("/events/{event_id}/orders", response_model=list[OrderResponse])
async def get_event_orders(
    event_id: UUID,
    db: DatabaseSession,
    actor: CurrentUser,
    order_status: Annotated[OrderStatus | None, Query(alias="status")] = None,
):
    """Owner or manager of the event."""
    return await order_service.get_event_orders(
        db=db, event_id=event_id, actor=actor, order_status=order_status
    )


@router.get("/events/{event_id}/attendees", response_model=list[EventAttendeeResponse])
async def get_event_attendees(
    event_id: UUID,
    db: DatabaseSession,
    actor: CurrentUser,
    q: str | None = Query(None, max_length=100, description="Name or email"),
):
    """One row per issued ticket. Any member of the event team."""
    return await order_service.get_event_attendees(
        db=db, event_id=event_id, actor=actor, q=q
    )


@router.get("/events/{event_id}/sales", response_model=EventSalesSummary)
async def get_event_sales(event_id: UUID, db: DatabaseSession, actor: CurrentUser):
    """Gross sales, fees, refunds and estimated payout. Demonstration data."""
    return await order_service.get_event_sales(db=db, event_id=event_id, actor=actor)


# --- Tickets ------------------------------------------------------------------

_PDF = {"content": {"application/pdf": {}}, "description": "Print-ready A4 PDF"}


def _pdf_response(content: bytes, filename: str) -> Response:
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/tickets/mine", response_model=list[TicketDetailResponse], tags=["Tickets"]
)
async def get_my_tickets(db: DatabaseSession, actor: CurrentUser):
    """Tickets you bought or that were issued in your name (matched by email)."""
    return await tickets_service.get_my_tickets(db=db, actor=actor)


@router.get(
    "/tickets/{ticket_id}", response_model=TicketDetailResponse, tags=["Tickets"]
)
async def get_ticket(ticket_id: UUID, db: DatabaseSession, actor: CurrentUser):
    """One ticket with its admission QR payload (only while it can be used)."""
    return await tickets_service.get_ticket(db=db, ticket_id=ticket_id, actor=actor)


@router.get(
    "/tickets/{ticket_id}/pdf",
    response_class=Response,
    responses={200: _PDF},
    tags=["Tickets"],
)
async def get_ticket_pdf(ticket_id: UUID, db: DatabaseSession, actor: CurrentUser):
    """Download one ticket as a printable PDF."""
    content = await tickets_service.get_ticket_pdf(
        db=db, ticket_id=ticket_id, actor=actor
    )
    return _pdf_response(content, f"biletflow-ticket-{str(ticket_id)[:8]}.pdf")


@router.get(
    "/orders/{order_id}/tickets.pdf",
    response_class=Response,
    responses={200: _PDF},
    tags=["Tickets"],
)
async def get_order_tickets_pdf(
    order_id: UUID, db: DatabaseSession, actor: CurrentUser
):
    """Every ticket of an order in one PDF, one page each. The buyer only."""
    content = await tickets_service.get_order_pdf(db=db, order_id=order_id, actor=actor)
    return _pdf_response(content, f"biletflow-order-{str(order_id)[:8]}.pdf")


# --- Refunds and cancellations -------------------------------------------------


@router.post(
    "/orders/{order_id}/refund", response_model=OrderResponse, tags=["Refunds"]
)
async def refund_order(
    order_id: UUID,
    data_in: RefundCreate,
    db: DatabaseSession,
    actor: CurrentUser,
    background: BackgroundTasks,
):
    """Fully refund a paid order (simulated). The event owner or a platform
    admin. Its tickets become invalid and the buyer is emailed."""
    await refunds_service.refund_order(db, order_id, actor, data_in.reason, background)
    return await order_service.respond(db, order_id)


@router.post(
    "/orders/{order_id}/cancel-registration",
    response_model=OrderResponse,
    tags=["Refunds"],
)
async def cancel_registration(
    order_id: UUID,
    data_in: RegistrationCancel,
    db: DatabaseSession,
    actor: CurrentUser,
    background: BackgroundTasks,
):
    """Cancel a free registration: the attendee who booked it, or the event's
    owner or a manager. Its tickets become invalid and the places free up."""
    await refunds_service.cancel_registration(
        db, order_id, actor, data_in.reason, background
    )
    return await order_service.respond(db, order_id)


@router.get(
    "/events/{event_id}/refunds",
    response_model=list[EventRefundResponse],
    tags=["Refunds"],
)
async def get_event_refunds(event_id: UUID, db: DatabaseSession, actor: CurrentUser):
    """Refunds for the event, newest first. Owner or manager."""
    return await order_service.get_event_refunds(db=db, event_id=event_id, actor=actor)
