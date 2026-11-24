"""Phase 9: support cases (SRS 4.13, UC9)."""

import pytest
from httpx import AsyncClient

from tests.conftest import (
    API,
    add_ticket_type,
    create_account,
    create_event,
    create_organizer,
)

pytestmark = pytest.mark.anyio
CASES = f"{API}/support/cases"


async def _setup(client: AsyncClient):
    """Owner, support staff, check-in staff, buyer with one free ticket."""
    owner = await create_organizer(client)
    helper = await create_account(client, full_name="Mira Support")
    door = await create_account(client, full_name="Door Keeper")
    buyer = await create_account(client, full_name="Dana Sarsen")
    event = await create_event(client, owner)
    ticket_type = await add_ticket_type(client, owner, event["id"])
    await client.post(f"{API}/events/{event['id']}/publish", headers=owner.headers)
    for account, role in ((helper, "support_staff"), (door, "checkin_staff")):
        added = await client.post(
            f"{API}/events/{event['id']}/staff",
            json={"email": account.email, "role": role},
            headers=owner.headers,
        )
        assert added.status_code == 201, added.text
    order = (
        await client.post(
            f"{API}/events/{event['id']}/orders",
            json={"items": [{"ticket_type_id": ticket_type["id"], "quantity": 1}]},
            headers=buyer.headers,
        )
    ).json()
    return owner, helper, door, buyer, event, order


async def _open(client: AsyncClient, account, **fields) -> dict:
    payload = {
        "category": "ticket_delivery",
        "subject": "Where is my ticket?",
        "message": "I cannot find my ticket.",
    }
    payload.update(fields)
    response = await client.post(CASES, json=payload, headers=account.headers)
    assert response.status_code == 201, response.text
    return response.json()


async def _ids(client: AsyncClient, account, **params) -> list[str]:
    response = await client.get(CASES, params=params, headers=account.headers)
    assert response.status_code == 200, response.text
    return [c["id"] for c in response.json()]


async def test_case_from_ticket_fills_context_and_limits_access(
    client: AsyncClient, sent_emails
):
    owner, helper, door, buyer, event, order = await _setup(client)
    stranger = await create_account(client)
    sent_emails.clear()

    case = await _open(client, buyer, ticket_id=order["tickets"][0]["id"])

    assert case["event_id"] == event["id"]
    assert case["order_id"] == order["id"]
    assert case["status"] == "open" and case["status_label"] == "Open"
    assert case["can_manage"] is False
    assert [m["body"] for m in case["messages"]] == ["I cannot find my ticket."]
    # The event's support team is told; check-in staff are not on it
    assert sorted(m.to for m in sent_emails) == sorted([owner.email, helper.email])

    assert await _ids(client, buyer, scope="requested") == [case["id"]]
    assert case["id"] in await _ids(client, owner, scope="handling")
    assert case["id"] in await _ids(client, helper, scope="handling")
    for outsider in (stranger, door):
        assert case["id"] not in await _ids(client, outsider)
        detail = await client.get(f"{CASES}/{case['id']}", headers=outsider.headers)
        assert detail.status_code == 404


async def test_opening_rules(client: AsyncClient):
    _, _, _, buyer, event, order = await _setup(client)
    other_buyer = await create_account(client)

    wrong_category = await client.post(
        CASES,
        json={
            "category": "activation",
            "subject": "Hi there",
            "message": "x",
            "event_id": event["id"],
        },
        headers=buyer.headers,
    )
    assert wrong_category.status_code == 400
    no_context = await client.post(
        CASES,
        json={"category": "account", "subject": "Hi there", "message": "x"},
        headers=buyer.headers,
    )
    assert no_context.status_code == 400
    # Someone else's ticket cannot be used as context
    theirs = await client.post(
        CASES,
        json={
            "category": "ticket_delivery",
            "subject": "Hi there",
            "message": "x",
            "ticket_id": order["tickets"][0]["id"],
        },
        headers=other_buyer.headers,
    )
    assert theirs.status_code == 404


async def test_conversation_assignment_and_reopening(client: AsyncClient, sent_emails):
    owner, helper, _, buyer, event, order = await _setup(client)
    case = await _open(client, buyer, order_id=order["id"])
    url = f"{CASES}/{case['id']}"

    options = (await client.get(f"{url}/assignees", headers=owner.headers)).json()
    assert {o["full_name"] for o in options} >= {"Mira Support"}
    outsider = await create_account(client)
    bad_assign = await client.patch(
        url, json={"assignee_user_id": str(outsider.id)}, headers=owner.headers
    )
    assert bad_assign.status_code == 400

    sent_emails.clear()
    assigned = await client.patch(
        url, json={"assignee_user_id": str(helper.id)}, headers=owner.headers
    )
    assert assigned.json()["assignee_name"] == "Mira Support"
    assert [m.to for m in sent_emails] == [helper.email]

    sent_emails.clear()
    reply = await client.post(
        f"{url}/messages",
        json={"body": "Check your spam folder."},
        headers=helper.headers,
    )
    assert reply.json()["messages"][-1]["from_staff"] is True
    assert [m.to for m in sent_emails] == [buyer.email]
    first_at = reply.json()["messages"][0]["created_at"]

    sent_emails.clear()
    await client.post(
        f"{url}/messages", json={"body": "Found it!"}, headers=buyer.headers
    )
    # Once assigned, only the assignee hears about replies
    assert [m.to for m in sent_emails] == [helper.email]
    newer = await client.get(
        f"{url}/messages", params={"since": first_at}, headers=buyer.headers
    )
    assert [m["body"] for m in newer.json()] == ["Check your spam folder.", "Found it!"]

    assert (
        await client.patch(url, json={"status": "resolved"}, headers=buyer.headers)
    ).status_code == 403
    sent_emails.clear()
    resolved = await client.patch(
        url, json={"status": "resolved"}, headers=helper.headers
    )
    assert resolved.json()["status"] == "resolved"
    assert [m.to for m in sent_emails] == [buyer.email]

    reopened = await client.post(
        f"{url}/messages", json={"body": "One more question"}, headers=buyer.headers
    )
    assert reopened.json()["status"] == "open"
    actions = [h["action"] for h in reopened.json()["history"]]
    assert actions == [
        "Opened the case",
        "Assigned to Mira Support",
        "Changed status to Resolved",
        "Reopened the case by replying",
    ]
    timeline = (
        await client.get(
            f"{API}/events/{event['id']}/activity",
            params={"area": "support"},
            headers=owner.headers,
        )
    ).json()
    assert [e["action"] for e in timeline] == [
        "support.status_changed",
        "support.assigned",
        "support.opened",
    ]


async def test_escalation_brings_in_platform_admins(client: AsyncClient, sent_emails):
    owner, _, _, buyer, _, order = await _setup(client)
    admin = await create_account(client, admin=True)
    case = await _open(client, buyer, order_id=order["id"], category="refund")
    url = f"{CASES}/{case['id']}"

    assert case["id"] not in await _ids(client, admin, scope="handling")
    assert (
        await client.post(
            f"{url}/escalate", json={"reason": "Fraud?"}, headers=buyer.headers
        )
    ).status_code == 403

    sent_emails.clear()
    escalated = await client.post(
        f"{url}/escalate", json={"reason": "Refund dispute"}, headers=owner.headers
    )
    assert escalated.json()["is_escalated"] is True
    assert admin.email in [m.to for m in sent_emails]
    assert case["id"] in await _ids(client, admin, scope="handling")
    reply = await client.post(
        f"{url}/messages", json={"body": "Platform team here."}, headers=admin.headers
    )
    assert reply.json()["messages"][-1]["from_staff"] is True
    assert (
        await client.post(
            f"{url}/escalate", json={"reason": "again"}, headers=owner.headers
        )
    ).status_code == 409


async def test_organizer_cases_go_to_the_platform_team(client: AsyncClient):
    owner = await create_organizer(client)
    other_organizer = await create_organizer(client)
    admin = await create_account(client, admin=True)
    event = await create_event(client, owner)

    case = await _open(
        client,
        owner,
        audience="organizer",
        category="activation",
        subject="Activation fee question",
        message="Is the fee refundable?",
        event_id=event["id"],
    )

    assert case["id"] in await _ids(client, admin, scope="handling")
    assert case["id"] not in await _ids(client, other_organizer)
    assert (
        await client.patch(
            f"{CASES}/{case['id']}",
            json={"status": "in_progress"},
            headers=owner.headers,
        )
    ).status_code == 403
    progressed = await client.patch(
        f"{CASES}/{case['id']}", json={"status": "in_progress"}, headers=admin.headers
    )
    assert progressed.json()["status_label"] == "In Progress"

    attendee_category = await client.post(
        CASES,
        json={
            "audience": "organizer",
            "category": "refund",
            "subject": "Hi there",
            "message": "x",
        },
        headers=owner.headers,
    )
    assert attendee_category.status_code == 400
    # Organizers can only cite events they manage
    not_theirs = await client.post(
        CASES,
        json={
            "audience": "organizer",
            "category": "technical",
            "subject": "Hi there",
            "message": "x",
            "event_id": event["id"],
        },
        headers=other_organizer.headers,
    )
    assert not_theirs.status_code == 404
