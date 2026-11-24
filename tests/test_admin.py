"""Phase 11: platform administration (SRS 4.12)."""

import csv
import io
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import (
    API,
    PASSWORD,
    add_ticket_type,
    create_account,
    create_event,
    create_organizer,
)
from tests.orders_helpers import activate_paid_sales

pytestmark = pytest.mark.anyio
ADMIN = f"{API}/admin"


async def _event_with_buyer(client: AsyncClient, **event_fields):
    owner = await create_organizer(client)
    event = await create_event(client, owner, **event_fields)
    ticket_type = await add_ticket_type(client, owner, event["id"])
    await client.post(f"{API}/events/{event['id']}/publish", headers=owner.headers)
    return owner, event, ticket_type


async def _order(client: AsyncClient, buyer, event: dict, ticket_type: dict):
    return await client.post(
        f"{API}/events/{event['id']}/orders",
        json={"items": [{"ticket_type_id": ticket_type["id"], "quantity": 1}]},
        headers=buyer.headers,
    )


async def test_admin_routes_need_a_platform_admin(client: AsyncClient):
    user = await create_account(client)
    for path in (
        "/search?q=ab",
        "/users",
        "/organizers",
        "/events",
        "/orders",
        "/payments",
        "/refunds",
        "/reports",
        "/disputes",
        "/promo-activity",
        "/audit",
        "/exports/users.csv",
    ):
        assert (
            await client.get(f"{ADMIN}{path}", headers=user.headers)
        ).status_code == 403, path


async def test_search_finds_users_events_and_orders(client: AsyncClient):
    admin = await create_account(client, admin=True)
    # Unique per run: test data stays in the database between runs
    token = uuid4().hex[:8]
    owner, event, ticket_type = await _event_with_buyer(
        client, title=f"Zhetysu Folk {token}"
    )
    buyer = await create_account(client)
    order = (await _order(client, buyer, event, ticket_type)).json()

    by_title = await client.get(
        f"{ADMIN}/search", params={"q": f"Folk {token}"}, headers=admin.headers
    )
    assert [e["id"] for e in by_title.json()["events"]] == [event["id"]]
    by_email = await client.get(
        f"{ADMIN}/search", params={"q": buyer.email}, headers=admin.headers
    )
    assert [u["id"] for u in by_email.json()["users"]] == [str(buyer.id)]
    assert order["id"] in [o["id"] for o in by_email.json()["orders"]]
    by_id = await client.get(
        f"{ADMIN}/search", params={"q": order["id"]}, headers=admin.headers
    )
    assert [o["id"] for o in by_id.json()["orders"]] == [order["id"]]


async def test_suspending_a_user_signs_them_out_and_hides_their_events(
    client: AsyncClient,
):
    admin = await create_account(client, admin=True)
    owner, event, ticket_type = await _event_with_buyer(client)
    buyer = await create_account(client)

    assert (
        await client.post(
            f"{ADMIN}/users/{admin.id}/suspend",
            json={"reason": "test"},
            headers=admin.headers,
        )
    ).status_code == 400
    suspended = await client.post(
        f"{ADMIN}/users/{owner.id}/suspend",
        json={"reason": "Fraud reports"},
        headers=admin.headers,
    )
    assert suspended.json()["is_suspended"] is True
    assert (
        await client.get(f"{API}/users/me", headers=owner.headers)
    ).status_code == 401
    login = await client.post(
        f"{API}/auth/login", data={"username": owner.email, "password": PASSWORD}
    )
    assert login.status_code == 403
    assert (await client.get(f"{API}/events/{event['id']}")).status_code == 404
    listed = await client.get(
        f"{API}/events/", params={"q": event["title"], "limit": 200}
    )
    assert event["id"] not in [e["id"] for e in listed.json()]
    assert (await _order(client, buyer, event, ticket_type)).status_code == 404

    await client.post(f"{ADMIN}/users/{owner.id}/restore", headers=admin.headers)
    assert (await client.get(f"{API}/events/{event['id']}")).status_code == 200


async def test_suspending_an_event_stops_sales_and_tells_the_organizer(
    client: AsyncClient,
):
    admin = await create_account(client, admin=True)
    owner, event, ticket_type = await _event_with_buyer(client)
    buyer = await create_account(client)
    url = f"{ADMIN}/events/{event['id']}"

    row = await client.post(
        f"{url}/suspend", json={"reason": "Misleading venue"}, headers=admin.headers
    )
    assert row.status_code == 200, row.text
    assert row.json()["is_suspended"] is True
    assert (await client.get(f"{API}/events/{event['id']}")).status_code == 404
    assert (await _order(client, buyer, event, ticket_type)).status_code == 404
    # The organizer still sees it, cannot sell, and is told why
    shown = await client.get(f"{API}/events/{event['id']}", headers=owner.headers)
    assert shown.json()["is_suspended"] is True
    assert (await _order(client, owner, event, ticket_type)).status_code == 409
    inbox = (await client.get(f"{API}/notifications", headers=owner.headers)).json()
    assert inbox[0]["kind"] == "event_suspended"
    assert (
        await client.post(
            f"{url}/suspend", json={"reason": "again"}, headers=admin.headers
        )
    ).status_code == 409

    await client.post(f"{url}/restore", headers=admin.headers)
    assert (await _order(client, buyer, event, ticket_type)).status_code == 201


async def test_event_reports_and_review(client: AsyncClient):
    admin = await create_account(client, admin=True)
    _, event, _ = await _event_with_buyer(client)
    reporter = await create_account(client)
    reason = {"reason": "The venue in the description does not exist."}

    report = await client.post(
        f"{API}/events/{event['id']}/reports", json=reason, headers=reporter.headers
    )
    assert report.status_code == 201, report.text
    assert (
        await client.post(
            f"{API}/events/{event['id']}/reports", json=reason, headers=reporter.headers
        )
    ).status_code == 409

    pending = await client.get(
        f"{ADMIN}/reports", params={"status": "pending"}, headers=admin.headers
    )
    assert report.json()["id"] in [r["id"] for r in pending.json()]
    review_url = f"{ADMIN}/reports/{report.json()['id']}/review"
    assert (
        await client.post(
            review_url,
            json={"decision": "dismissed", "suspend_event": True},
            headers=admin.headers,
        )
    ).status_code == 400
    reviewed = await client.post(
        review_url,
        json={
            "decision": "actioned",
            "note": "Confirmed fake venue",
            "suspend_event": True,
        },
        headers=admin.headers,
    )
    assert reviewed.json()["status"] == "actioned"
    assert (await client.get(f"{API}/events/{event['id']}")).status_code == 404
    assert (
        await client.post(
            review_url, json={"decision": "dismissed"}, headers=admin.headers
        )
    ).status_code == 409


async def test_payment_monitors_and_disputes(client: AsyncClient):
    admin = await create_account(client, admin=True)
    owner = await create_organizer(client)
    event = await create_event(client, owner)
    paid = await add_ticket_type(client, owner, event["id"], price_kzt=7000)
    await client.post(f"{API}/events/{event['id']}/publish", headers=owner.headers)
    await activate_paid_sales(event["id"])
    buyer = await create_account(client)
    order = (await _order(client, buyer, event, paid)).json()
    pay = f"{API}/orders/{order['id']}/pay"
    failed = (
        await client.post(pay, json={"outcome": "failure"}, headers=buyer.headers)
    ).json()
    paid_order = (await client.post(pay, json={}, headers=buyer.headers)).json()
    failed_id = failed["payments"][0]["id"]
    ok_id = paid_order["payments"][-1]["id"]

    failures = await client.get(
        f"{ADMIN}/payments",
        params={"status": "failed", "q": buyer.email},
        headers=admin.headers,
    )
    assert [p["id"] for p in failures.json()] == [failed_id]

    assert (
        await client.post(
            f"{ADMIN}/payments/{failed_id}/disputes",
            json={"reason": "Chargeback"},
            headers=admin.headers,
        )
    ).status_code == 400
    dispute = await client.post(
        f"{ADMIN}/payments/{ok_id}/disputes",
        json={"reason": "Cardholder disputes the charge"},
        headers=admin.headers,
    )
    assert dispute.status_code == 201
    assert dispute.json()["amount_kzt"] == 7000
    resolved = await client.patch(
        f"{ADMIN}/disputes/{dispute.json()['id']}",
        json={"status": "won", "note": "Ticket was used"},
        headers=admin.headers,
    )
    assert resolved.json()["status"] == "won"
    assert (
        await client.patch(
            f"{ADMIN}/disputes/{dispute.json()['id']}",
            json={"status": "lost"},
            headers=admin.headers,
        )
    ).status_code == 409

    await client.post(
        f"{API}/orders/{order['id']}/refund",
        json={"reason": "Event moved"},
        headers=owner.headers,
    )
    refunds = await client.get(f"{ADMIN}/refunds", headers=admin.headers)
    assert order["id"] in [r["order_id"] for r in refunds.json()]


async def test_promo_activity_and_platform_audit(client: AsyncClient):
    admin = await create_account(client, admin=True)
    owner = await create_organizer(client)
    event = await create_event(client, owner)
    paid = await add_ticket_type(client, owner, event["id"], price_kzt=5000)
    await client.post(f"{API}/events/{event['id']}/publish", headers=owner.headers)
    await activate_paid_sales(event["id"])
    campaign = (
        await client.post(
            f"{API}/events/{event['id']}/campaigns",
            json={"name": "Launch", "discount_type": "percent", "discount_value": 10},
            headers=owner.headers,
        )
    ).json()
    buyer = await create_account(client)
    await client.post(
        f"{API}/events/{event['id']}/orders",
        json={
            "items": [{"ticket_type_id": paid["id"], "quantity": 1}],
            "promo_code": campaign["code"],
        },
        headers=buyer.headers,
    )

    activity = await client.get(f"{ADMIN}/promo-activity", headers=admin.headers)
    mine = [r for r in activity.json() if r["code"] == campaign["code"]]
    assert mine and mine[0]["discount_kzt"] == 500

    target = await create_account(client)
    await client.post(
        f"{ADMIN}/users/{target.id}/suspend",
        json={"reason": "Spam"},
        headers=admin.headers,
    )
    audit = await client.get(
        f"{ADMIN}/audit", params={"action": "platform."}, headers=admin.headers
    )
    assert audit.json()[0]["action"] == "platform.user_suspended"
    assert target.email in audit.json()[0]["description"]


async def test_csv_exports_escape_formulas(client: AsyncClient):
    admin = await create_account(client, admin=True)
    owner = await create_organizer(client)
    await create_event(client, owner, title="=HYPERLINK(evil)")

    for kind in (
        "users",
        "events",
        "orders",
        "payments",
        "refunds",
        "activations",
        "disputes",
        "promotions",
        "support",
    ):
        response = await client.get(
            f"{ADMIN}/exports/{kind}.csv", headers=admin.headers
        )
        assert response.status_code == 200, kind
        assert response.headers["content-type"].startswith("text/csv")
        assert f"biletflow-{kind}.csv" in response.headers["content-disposition"]

    events_csv = (
        await client.get(f"{ADMIN}/exports/events.csv", headers=admin.headers)
    ).text
    titles = [row["title"] for row in csv.DictReader(io.StringIO(events_csv))]
    assert "'=HYPERLINK(evil)" in titles
    assert "=HYPERLINK(evil)" not in titles
    assert (
        await client.get(f"{ADMIN}/exports/secrets.csv", headers=admin.headers)
    ).status_code == 404


async def test_organizer_verification_queue(client: AsyncClient):
    admin = await create_account(client, admin=True)
    owner = await create_organizer(client)
    token = uuid4().hex[:8]
    await client.post(
        f"{API}/organizers/me/verification",
        json={"legal_name": f"Steppe Events {token} LLP", "tax_id": "900101300126"},
        headers=owner.headers,
    )
    found = await client.get(
        f"{ADMIN}/organizers", params={"q": token}, headers=admin.headers
    )
    assert found.status_code == 200, found.text
    [row] = found.json()
    assert row["email"] == owner.email
    # The identity number is only ever shown masked
    assert row["tax_id_masked"].endswith("0126")
    assert "900101300126" not in found.text

    # The admin can overrule the simulated check; the queue filters by status
    decided = await client.patch(
        f"{API}/organizers/{row['id']}/verification",
        json={"verification_status": "rejected"},
        headers=admin.headers,
    )
    assert decided.status_code == 200
    rejected = await client.get(
        f"{ADMIN}/organizers",
        params={"q": token, "verification_status": "rejected"},
        headers=admin.headers,
    )
    assert [r["id"] for r in rejected.json()] == [row["id"]]
    verified = await client.get(
        f"{ADMIN}/organizers",
        params={"q": token, "verification_status": "verified"},
        headers=admin.headers,
    )
    assert verified.json() == []
