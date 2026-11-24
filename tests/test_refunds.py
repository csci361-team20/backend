"""Phase 7: refunds and cancellations (SRS 4.9, UC5)."""

import pytest
from httpx import AsyncClient

from tests.conftest import (
    API,
    add_ticket_type,
    create_account,
    create_event,
    create_organizer,
)
from tests.orders_helpers import activate_paid_sales

pytestmark = pytest.mark.anyio


async def _event(client: AsyncClient, *, price: int = 6000, **event_fields):
    owner = await create_organizer(client)
    event = await create_event(client, owner, **event_fields)
    paid = await add_ticket_type(
        client, owner, event["id"], name="Paid", price_kzt=price
    )
    free = await add_ticket_type(client, owner, event["id"], name="Free")
    await client.post(f"{API}/events/{event['id']}/publish", headers=owner.headers)
    await activate_paid_sales(event["id"])
    return owner, event, paid, free


async def _buy(client: AsyncClient, buyer, event: dict, ticket_type: dict, qty=1):
    response = await client.post(
        f"{API}/events/{event['id']}/orders",
        json={"items": [{"ticket_type_id": ticket_type["id"], "quantity": qty}]},
        headers=buyer.headers,
    )
    assert response.status_code == 201, response.text
    order = response.json()
    if order["status"] == "pending":
        paid = await client.post(
            f"{API}/orders/{order['id']}/pay", json={}, headers=buyer.headers
        )
        order = paid.json()
    return order


def _refund(client: AsyncClient, account, order: dict, reason="Attendee is ill"):
    return client.post(
        f"{API}/orders/{order['id']}/refund",
        json={"reason": reason},
        headers=account.headers,
    )


async def test_owner_refunds_a_paid_order(client: AsyncClient, sent_emails):
    owner, event, paid, _ = await _event(client)
    buyer = await create_account(client)
    order = await _buy(client, buyer, event, paid, qty=2)
    sent_emails.clear()

    response = await _refund(client, owner, order)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "refunded"
    assert body["refund"]["amount_kzt"] == 12000
    assert body["refund"]["is_simulated"] is True
    assert body["refund"]["reason"] == "Attendee is ill"
    assert {t["status"] for t in body["tickets"]} == {"refunded"}
    assert [m.to for m in sent_emails] == [buyer.email]
    assert "Refund" in sent_emails[0].subject

    ticket = (
        await client.get(
            f"{API}/tickets/{body['tickets'][0]['id']}", headers=buyer.headers
        )
    ).json()
    assert ticket["qr_payload"] is None

    sales = (
        await client.get(f"{API}/events/{event['id']}/sales", headers=owner.headers)
    ).json()
    assert sales["gross_sales_kzt"] == 12000
    assert sales["refunds_kzt"] == 12000
    assert sales["estimated_payout_kzt"] == 12000 - sales["processing_fees_kzt"] - 12000

    stats = (
        await client.get(
            f"{API}/events/{event['id']}/ticket-stats", headers=owner.headers
        )
    ).json()
    paid_row = next(r for r in stats["ticket_types"] if r["name"] == "Paid")
    assert (paid_row["sold"], paid_row["refunded"], paid_row["available"]) == (0, 2, 10)

    refunds = (
        await client.get(f"{API}/events/{event['id']}/refunds", headers=owner.headers)
    ).json()
    assert [(r["amount_kzt"], r["buyer_name"]) for r in refunds] == [
        (12000, "Test User")
    ]
    timeline = (
        await client.get(
            f"{API}/events/{event['id']}/activity",
            params={"area": "refund"},
            headers=owner.headers,
        )
    ).json()
    assert [e["action"] for e in timeline] == ["refund.completed"]


async def test_who_may_refund(client: AsyncClient):
    owner, event, paid, _ = await _event(client)
    manager = await create_account(client)
    admin = await create_account(client, admin=True)
    stranger = await create_account(client)
    buyer = await create_account(client)
    await client.post(
        f"{API}/events/{event['id']}/staff",
        json={"email": manager.email, "role": "manager"},
        headers=owner.headers,
    )
    order = await _buy(client, buyer, event, paid)

    assert (await _refund(client, manager, order)).status_code == 403
    assert (await _refund(client, buyer, order)).status_code == 403
    assert (await _refund(client, stranger, order)).status_code == 404
    assert (await _refund(client, admin, order)).status_code == 200


async def test_refund_only_confirmed_paid_unused_orders(client: AsyncClient):
    owner, event, paid, free = await _event(client)
    buyer = await create_account(client)
    order = await _buy(client, buyer, event, paid)
    free_order = await _buy(client, buyer, event, free)

    assert (await _refund(client, owner, free_order)).status_code == 409

    # A used ticket blocks the refund until the check-in is undone
    ticket = order["tickets"][0]
    payload = (
        await client.get(f"{API}/tickets/{ticket['id']}", headers=buyer.headers)
    ).json()["qr_payload"]
    await client.post(
        f"{API}/events/{event['id']}/check-in/scan",
        json={"qr_payload": payload},
        headers=owner.headers,
    )
    used = await _refund(client, owner, order)
    assert used.status_code == 409
    await client.post(
        f"{API}/events/{event['id']}/check-in/tickets/{ticket['id']}/undo",
        json={"reason": "Refund requested"},
        headers=owner.headers,
    )
    assert (await _refund(client, owner, order)).status_code == 200
    assert (await _refund(client, owner, order)).status_code == 409


async def test_unpaid_checkout_cannot_be_refunded(client: AsyncClient):
    owner, event, paid, _ = await _event(client)
    buyer = await create_account(client)
    pending = (
        await client.post(
            f"{API}/events/{event['id']}/orders",
            json={"items": [{"ticket_type_id": paid["id"], "quantity": 1}]},
            headers=buyer.headers,
        )
    ).json()
    assert (await _refund(client, owner, pending)).status_code == 409


async def test_cancel_free_registration(client: AsyncClient, sent_emails):
    owner, event, paid, free = await _event(client)
    manager = await create_account(client)
    buyer = await create_account(client)
    other = await create_account(client)
    stranger = await create_account(client)
    await client.post(
        f"{API}/events/{event['id']}/staff",
        json={"email": manager.email, "role": "manager"},
        headers=owner.headers,
    )
    mine = await _buy(client, buyer, event, free, qty=2)
    theirs = await _buy(client, other, event, free)
    paid_order = await _buy(client, buyer, event, paid)

    def cancel(account, order):
        return client.post(
            f"{API}/orders/{order['id']}/cancel-registration",
            json={"reason": "Plans changed"},
            headers=account.headers,
        )

    assert (await cancel(stranger, mine)).status_code == 404
    assert (await cancel(buyer, paid_order)).status_code == 409

    sent_emails.clear()
    self_cancel = await cancel(buyer, mine)
    assert self_cancel.status_code == 200, self_cancel.text
    assert self_cancel.json()["status"] == "cancelled"
    assert {t["status"] for t in self_cancel.json()["tickets"]} == {"cancelled"}
    assert sent_emails == []  # the attendee did it themselves

    by_organizer = await cancel(manager, theirs)
    assert by_organizer.status_code == 200
    assert [m.to for m in sent_emails] == [other.email]
    assert (await cancel(manager, theirs)).status_code == 409

    stats = (
        await client.get(
            f"{API}/events/{event['id']}/ticket-stats", headers=owner.headers
        )
    ).json()
    free_row = next(r for r in stats["ticket_types"] if r["name"] == "Free")
    assert free_row["sold"] == 0 and free_row["available"] == 10


async def test_cancelling_event_refunds_everyone(client: AsyncClient, sent_emails):
    owner, event, paid, free = await _event(client)
    payer = await create_account(client)
    second_payer = await create_account(client)
    free_holder = await create_account(client)
    first = await _buy(client, payer, event, paid)
    second = await _buy(client, second_payer, event, paid)
    await _buy(client, free_holder, event, free)
    # Even a ticket already used is refunded when the event itself is cancelled
    payload = (
        await client.get(
            f"{API}/tickets/{second['tickets'][0]['id']}", headers=second_payer.headers
        )
    ).json()["qr_payload"]
    await client.post(
        f"{API}/events/{event['id']}/check-in/scan",
        json={"qr_payload": payload},
        headers=owner.headers,
    )
    sent_emails.clear()

    response = await client.post(
        f"{API}/events/{event['id']}/cancel", headers=owner.headers
    )

    assert response.status_code == 200, response.text
    for buyer, order in ((payer, first), (second_payer, second)):
        refreshed = (
            await client.get(f"{API}/orders/{order['id']}", headers=buyer.headers)
        ).json()
        assert refreshed["status"] == "refunded"
        assert refreshed["refund"]["amount_kzt"] == 6000
    assert sorted(m.to for m in sent_emails) == sorted(
        [payer.email, second_payer.email, free_holder.email]
    )
    sales = (
        await client.get(f"{API}/events/{event['id']}/sales", headers=owner.headers)
    ).json()
    assert sales["refunds_kzt"] == sales["gross_sales_kzt"] == 12000
    cancelled = (
        await client.get(
            f"{API}/events/{event['id']}/activity",
            params={"area": "event"},
            headers=owner.headers,
        )
    ).json()[0]
    assert cancelled["action"] == "event.cancelled"
    assert cancelled["details"]["refunded_orders"] == 2


async def test_refund_policy_is_shown_and_copied(client: AsyncClient):
    owner = await create_organizer(client)
    policy = "Full refund up to 7 days before the event."
    event = await create_event(client, owner, publish=True, refund_policy=policy)
    assert (await client.get(f"{API}/events/{event['id']}")).json()[
        "refund_policy"
    ] == policy

    copy = (
        await client.post(
            f"{API}/events/{event['id']}/duplicate", headers=owner.headers
        )
    ).json()
    assert copy["refund_policy"] == policy

    cleared = await client.patch(
        f"{API}/events/{event['id']}",
        json={"refund_policy": None},
        headers=owner.headers,
    )
    assert cleared.json()["refund_policy"] is None
