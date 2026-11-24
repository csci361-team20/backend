import re

import pytest
from httpx import AsyncClient

from app.core.security import parse_ticket_qr_payload
from tests.conftest import (
    API,
    add_ticket_type,
    create_account,
    create_event,
    create_organizer,
)
from tests.orders_helpers import activate_paid_sales

pytestmark = pytest.mark.anyio


async def _free_order(client: AsyncClient, buyer, *, attendees=None, quantity=1):
    owner = await create_organizer(client)
    event = await create_event(client, owner, title="Jazz at the Steppe")
    ticket_type = await add_ticket_type(client, owner, event["id"], name="Standard")
    await client.post(f"{API}/events/{event['id']}/publish", headers=owner.headers)
    body: dict = {
        "items": [{"ticket_type_id": ticket_type["id"], "quantity": quantity}]
    }
    if attendees:
        body["attendees"] = attendees
    response = await client.post(
        f"{API}/events/{event['id']}/orders", json=body, headers=buyer.headers
    )
    assert response.status_code == 201, response.text
    return owner, event, response.json()


async def test_holder_gets_ticket_with_signed_qr(client: AsyncClient):
    buyer = await create_account(client)
    _, event, order = await _free_order(client, buyer)

    mine = await client.get(f"{API}/tickets/mine", headers=buyer.headers)
    assert mine.status_code == 200
    [ticket] = mine.json()
    assert ticket["id"] == order["tickets"][0]["id"]
    assert ticket["event"]["title"] == "Jazz at the Steppe"
    assert ticket["event"]["timezone"] == "Asia/Almaty"
    assert ticket["status"] == "valid"
    assert ticket["seat"] is None
    payload = ticket["qr_payload"]
    assert payload.startswith("BFT1.")
    assert parse_ticket_qr_payload(payload) is not None
    # The QR never carries the ticket's own id
    assert ticket["id"] not in payload
    tampered = payload[:-1] + ("A" if payload[-1] != "A" else "B")
    assert parse_ticket_qr_payload(tampered) is None

    one = await client.get(f"{API}/tickets/{ticket['id']}", headers=buyer.headers)
    assert one.json()["qr_payload"] == payload


async def test_named_attendee_sees_their_ticket_others_do_not(client: AsyncClient):
    buyer = await create_account(client)
    friend = await create_account(client)
    stranger = await create_account(client)
    owner, _, order = await _free_order(
        client,
        buyer,
        quantity=2,
        attendees=[
            {"name": "Buyer Self", "email": buyer.email},
            {"name": "Friend Guest", "email": friend.email.upper()},
        ],
    )
    friend_ticket = next(
        t for t in order["tickets"] if t["attendee_name"] == "Friend Guest"
    )

    theirs = await client.get(f"{API}/tickets/mine", headers=friend.headers)
    assert [t["id"] for t in theirs.json()] == [friend_ticket["id"]]
    assert (
        len((await client.get(f"{API}/tickets/mine", headers=buyer.headers)).json())
        == 2
    )

    url = f"{API}/tickets/{friend_ticket['id']}"
    assert (await client.get(url, headers=stranger.headers)).status_code == 404
    # Organizers manage attendees through the attendee list, not ticket QRs
    assert (await client.get(url, headers=owner.headers)).status_code == 404


async def test_pdf_downloads(client: AsyncClient):
    buyer = await create_account(client)
    stranger = await create_account(client)
    _, _, order = await _free_order(client, buyer, quantity=2)
    ticket_id = order["tickets"][0]["id"]

    pdf = await client.get(f"{API}/tickets/{ticket_id}/pdf", headers=buyer.headers)
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert "attachment" in pdf.headers["content-disposition"]
    assert pdf.content.startswith(b"%PDF")

    bundle = await client.get(
        f"{API}/orders/{order['id']}/tickets.pdf", headers=buyer.headers
    )
    assert bundle.status_code == 200
    # One page per ticket
    assert len(re.findall(rb"/Type\s*/Page(?!s)", bundle.content)) == 2

    assert (
        await client.get(f"{API}/tickets/{ticket_id}/pdf", headers=stranger.headers)
    ).status_code == 404
    assert (
        await client.get(
            f"{API}/orders/{order['id']}/tickets.pdf", headers=stranger.headers
        )
    ).status_code == 404


async def test_unpaid_order_has_no_tickets_to_print(client: AsyncClient):
    owner = await create_organizer(client)
    buyer = await create_account(client)
    event = await create_event(client, owner)
    paid = await add_ticket_type(client, owner, event["id"], price_kzt=3000)
    await client.post(f"{API}/events/{event['id']}/publish", headers=owner.headers)
    await activate_paid_sales(event["id"])
    order = (
        await client.post(
            f"{API}/events/{event['id']}/orders",
            json={"items": [{"ticket_type_id": paid["id"], "quantity": 1}]},
            headers=buyer.headers,
        )
    ).json()

    response = await client.get(
        f"{API}/orders/{order['id']}/tickets.pdf", headers=buyer.headers
    )
    assert response.status_code == 409


async def test_void_ticket_has_no_qr(client: AsyncClient):
    buyer = await create_account(client)
    owner, event, order = await _free_order(client, buyer)
    await client.post(f"{API}/events/{event['id']}/cancel", headers=owner.headers)

    ticket = (
        await client.get(
            f"{API}/tickets/{order['tickets'][0]['id']}", headers=buyer.headers
        )
    ).json()
    assert ticket["status"] == "cancelled"
    assert ticket["qr_payload"] is None
    pdf = await client.get(
        f"{API}/tickets/{order['tickets'][0]['id']}/pdf", headers=buyer.headers
    )
    assert pdf.status_code == 200


async def test_confirmation_emails_carry_pdf_tickets(client: AsyncClient, sent_emails):
    buyer = await create_account(client)
    friend_email = "friend.guest@example.kz"
    sent_emails.clear()
    await _free_order(
        client,
        buyer,
        quantity=2,
        attendees=[
            {"name": "Buyer Self", "email": buyer.email},
            {"name": "Friend Guest", "email": friend_email},
        ],
    )

    # Ticket emails only; the organizer's sign-up email is also in the outbox
    by_recipient = {m.to: m for m in sent_emails if m.attachments}
    assert set(by_recipient) == {buyer.email, friend_email}
    for message in by_recipient.values():
        [(filename, content, mime_type)] = message.attachments
        assert filename.endswith(".pdf")
        assert mime_type == "application/pdf"
        assert content.startswith(b"%PDF")
    assert "Buyer Self" not in by_recipient[friend_email].body
