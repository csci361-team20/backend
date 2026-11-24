"""Phase 6: ticket verification and check-in (SRS 4.8, UC4)."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.modules.checkin.models import CheckInRecord
from app.modules.orders.enums import TicketStatus
from app.modules.orders.models import Ticket
from tests.conftest import (
    API,
    add_ticket_type,
    create_account,
    create_event,
    create_organizer,
)

pytestmark = pytest.mark.anyio


async def _setup(client: AsyncClient, tickets: int = 2):
    """Owner, door staff, buyer with ``tickets`` issued tickets."""
    owner = await create_organizer(client)
    door = await create_account(client, full_name="Door Keeper")
    buyer = await create_account(client)
    event = await create_event(client, owner)
    ticket_type = await add_ticket_type(client, owner, event["id"], name="Standard")
    await client.post(f"{API}/events/{event['id']}/publish", headers=owner.headers)
    await client.post(
        f"{API}/events/{event['id']}/staff",
        json={"email": door.email, "role": "checkin_staff"},
        headers=owner.headers,
    )
    response = await client.post(
        f"{API}/events/{event['id']}/orders",
        json={"items": [{"ticket_type_id": ticket_type["id"], "quantity": tickets}]},
        headers=buyer.headers,
    )
    assert response.status_code == 201, response.text
    mine = (await client.get(f"{API}/tickets/mine", headers=buyer.headers)).json()
    return owner, door, buyer, event, mine


def _url(event: dict, path: str) -> str:
    return f"{API}/events/{event['id']}/check-in/{path}"


async def _scan(client: AsyncClient, account, event: dict, payload: str):
    response = await client.post(
        _url(event, "scan"), json={"qr_payload": payload}, headers=account.headers
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _set_ticket_status(ticket_id: str, ticket_status: TicketStatus) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Ticket)
            .where(Ticket.id == UUID(ticket_id))
            .values(status=ticket_status)
        )
        await session.commit()


async def test_scan_admits_once_then_reports_already_used(client: AsyncClient):
    owner, door, _, event, tickets = await _setup(client)
    payload = tickets[0]["qr_payload"]

    first = await _scan(client, door, event, payload)
    assert first["result"] == "valid"
    assert first["admitted"] is True
    assert first["ticket"]["status"] == "checked_in"
    assert first["ticket"]["checked_in_by_name"] == "Door Keeper"

    again = await _scan(client, door, event, payload)
    assert again["result"] == "already_used"
    assert again["admitted"] is False
    assert "Door Keeper" in again["message"]

    stats = (await client.get(_url(event, "stats"), headers=door.headers)).json()
    assert stats == {
        "event_id": event["id"],
        "registered": 2,
        "checked_in": 1,
        "remaining": 1,
        "checked_in_percent": 50.0,
    }
    history = (await client.get(_url(event, "history"), headers=door.headers)).json()
    assert [(h["action"], h["method"]) for h in history] == [("check_in", "scan")]
    timeline = (
        await client.get(
            f"{API}/events/{event['id']}/activity",
            params={"area": "check_in"},
            headers=owner.headers,
        )
    ).json()
    assert [e["action"] for e in timeline] == ["check_in.admitted"]


async def test_verify_does_not_admit(client: AsyncClient):
    _, door, _, event, tickets = await _setup(client)
    response = await client.post(
        _url(event, "verify"),
        json={"qr_payload": tickets[0]["qr_payload"]},
        headers=door.headers,
    )
    assert response.json()["result"] == "valid"
    assert response.json()["admitted"] is False
    assert (await _scan(client, door, event, tickets[0]["qr_payload"]))["admitted"]


async def test_campaign_links_and_forgeries_never_admit(client: AsyncClient):
    _, door, _, event, tickets = await _setup(client)
    payload = tickets[0]["qr_payload"]

    campaign = await _scan(client, door, event, "https://biletflow.kz/e/abc?c=SPRING")
    assert campaign["result"] == "invalid"
    assert "Promotional" in campaign["message"]
    for bad in ("hello", payload[:-2] + "xx", "BFT1.unknown-secret.zzzz"):
        result = await _scan(client, door, event, bad)
        assert result["result"] == "invalid", bad
        assert result["ticket"] is None


async def test_ticket_for_another_event_is_flagged_without_details(
    client: AsyncClient,
):
    _, door, _, event, _ = await _setup(client)
    _, _, _, _, other_tickets = await _setup(client)

    result = await _scan(client, door, event, other_tickets[0]["qr_payload"])

    assert result["result"] == "wrong_event"
    assert result["ticket"] is None


async def test_cancelled_and_refunded_tickets_are_refused(client: AsyncClient):
    _, door, _, event, tickets = await _setup(client)
    await _set_ticket_status(tickets[0]["id"], TicketStatus.CANCELLED)
    await _set_ticket_status(tickets[1]["id"], TicketStatus.REFUNDED)
    # The QR payload was captured before the change, as on a printed ticket
    cancelled = await _scan(client, door, event, tickets[0]["qr_payload"])
    refunded = await _scan(client, door, event, tickets[1]["qr_payload"])
    assert (cancelled["result"], refunded["result"]) == ("cancelled", "refunded")
    assert not cancelled["admitted"] and not refunded["admitted"]


async def test_only_the_event_team_can_check_in(client: AsyncClient):
    _, _, buyer, event, tickets = await _setup(client)
    outsider = await create_account(client)
    for account in (buyer, outsider):
        response = await client.post(
            _url(event, "scan"),
            json={"qr_payload": tickets[0]["qr_payload"]},
            headers=account.headers,
        )
        # The event is public, so they see it exists but may not check in
        assert response.status_code == 403


async def test_check_in_closed_for_draft_events(client: AsyncClient):
    owner = await create_organizer(client)
    event = await create_event(client, owner)
    response = await client.post(
        _url(event, "scan"), json={"qr_payload": "x"}, headers=owner.headers
    )
    assert response.status_code == 409


async def test_manual_check_in_from_attendee_search(client: AsyncClient):
    _, door, _, event, tickets = await _setup(client, tickets=1)
    found = (
        await client.get(
            f"{API}/events/{event['id']}/attendees",
            params={"q": "test"},
            headers=door.headers,
        )
    ).json()
    assert found[0]["checked_in_at"] is None

    response = await client.post(
        _url(event, f"tickets/{found[0]['ticket_id']}"), headers=door.headers
    )
    assert response.json()["admitted"] is True
    again = await client.post(
        _url(event, f"tickets/{found[0]['ticket_id']}"), headers=door.headers
    )
    assert again.json()["result"] == "already_used"
    found = (
        await client.get(f"{API}/events/{event['id']}/attendees", headers=door.headers)
    ).json()
    assert found[0]["checked_in_at"] is not None
    history = (await client.get(_url(event, "history"), headers=door.headers)).json()
    assert history[0]["method"] == "manual"


async def test_undo_rules(client: AsyncClient):
    owner, door, _, event, tickets = await _setup(client)
    other_door = await create_account(client, full_name="Second Door")
    await client.post(
        f"{API}/events/{event['id']}/staff",
        json={"email": other_door.email, "role": "checkin_staff"},
        headers=owner.headers,
    )
    first, second = tickets
    await _scan(client, door, event, first["qr_payload"])
    await _scan(client, door, event, second["qr_payload"])

    def undo(account, ticket):
        return client.post(
            _url(event, f"tickets/{ticket['id']}/undo"),
            json={"reason": "Scanned the wrong person"},
            headers=account.headers,
        )

    # Another staff member cannot undo Door Keeper's check-in
    assert (await undo(other_door, first)).status_code == 403
    # Door Keeper can undo their own, within the window
    undone = await undo(door, first)
    assert undone.status_code == 200
    assert undone.json()["ticket"]["status"] == "valid"
    assert (await undo(door, first)).status_code == 409
    assert (await _scan(client, door, event, first["qr_payload"]))["admitted"]

    # Outside the window only owners and managers may undo
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(CheckInRecord)
            .where(CheckInRecord.ticket_id == UUID(second["id"]))
            .values(created_at=datetime.now(UTC) - timedelta(minutes=30))
        )
        await session.commit()
    assert (await undo(door, second)).status_code == 403
    assert (await undo(owner, second)).status_code == 200

    history = (await client.get(_url(event, "history"), headers=owner.headers)).json()
    undos = [h for h in history if h["action"] == "undo"]
    assert len(undos) == 2
    assert undos[0]["reason"] == "Scanned the wrong person"


async def test_two_scanners_cannot_admit_the_same_ticket(client: AsyncClient):
    owner, door, _, event, tickets = await _setup(client, tickets=1)
    payload = tickets[0]["qr_payload"]

    results = await asyncio.gather(
        *(_scan(client, account, event, payload) for account in (door, owner, door))
    )

    assert sorted(r["result"] for r in results) == [
        "already_used",
        "already_used",
        "valid",
    ]
    assert sum(r["admitted"] for r in results) == 1
    history = (await client.get(_url(event, "history"), headers=owner.headers)).json()
    assert len(history) == 1
