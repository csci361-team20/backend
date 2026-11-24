"""Phase 10: in-app notifications and emails in Kazakh, Russian, English."""

import string
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core import i18n
from tests.conftest import (
    API,
    PASSWORD,
    add_ticket_type,
    create_account,
    create_event,
    create_organizer,
    login,
    set_user_fields,
)
from tests.orders_helpers import activate_paid_sales

pytestmark = pytest.mark.anyio


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def test_every_text_exists_in_all_three_languages():
    for key in i18n.keys():
        entry = i18n._CATALOG[key]
        assert set(entry) == {"en", "ru", "kk"}, key
        expected = _placeholders(entry["en"])
        for language in ("ru", "kk"):
            assert _placeholders(entry[language]) == expected, (key, language)


async def _register(client: AsyncClient, language: str | None = None):
    email_address = f"lang-{uuid4().hex}@example.com"
    body = {"email": email_address, "full_name": "Aigerim Nur", "password": PASSWORD}
    if language:
        body["preferred_language"] = language
    return email_address, await client.post(f"{API}/users/", json=body)


async def test_verification_email_follows_the_chosen_language(
    client: AsyncClient, sent_emails
):
    expected = {
        None: "Confirm your BiletFlow email address",
        "ru": "Подтвердите адрес электронной почты в BiletFlow",
        "kk": "BiletFlow-тағы электрондық поштаңызды растаңыз",
    }
    for language, subject in expected.items():
        sent_emails.clear()
        email_address, response = await _register(client, language)
        assert response.status_code == 201, response.text
        assert response.json()["preferred_language"] == (language or "en")
        assert [(m.to, m.subject) for m in sent_emails] == [(email_address, subject)]

    _, unsupported = await _register(client, "fr")
    assert unsupported.status_code == 422


async def test_language_can_be_changed_on_the_profile(client: AsyncClient):
    account = await create_account(client)
    response = await client.patch(
        f"{API}/users/me", json={"preferred_language": "kk"}, headers=account.headers
    )
    assert response.json()["preferred_language"] == "kk"


async def _free_event(client: AsyncClient):
    owner = await create_organizer(client)
    event = await create_event(client, owner)
    ticket_type = await add_ticket_type(client, owner, event["id"])
    await client.post(f"{API}/events/{event['id']}/publish", headers=owner.headers)
    return owner, event, ticket_type


async def _book(client: AsyncClient, buyer, event, ticket_type) -> dict:
    response = await client.post(
        f"{API}/events/{event['id']}/orders",
        json={"items": [{"ticket_type_id": ticket_type["id"], "quantity": 1}]},
        headers=buyer.headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _inbox(client: AsyncClient, account, **params) -> list[dict]:
    response = await client.get(
        f"{API}/notifications", params=params, headers=account.headers
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_order_notification_and_read_state(client: AsyncClient):
    _, event, ticket_type = await _free_event(client)
    buyer = await create_account(client)
    other = await create_account(client)
    order = await _book(client, buyer, event, ticket_type)

    [notice] = await _inbox(client, buyer)
    assert notice["kind"] == "order_confirmed"
    assert notice["link"] == f"/orders/{order['id']}"
    assert notice["event_id"] == event["id"]
    assert event["title"] in notice["message"]
    count = await client.get(f"{API}/notifications/unread-count", headers=buyer.headers)
    assert count.json() == {"unread": 1}

    assert (
        await client.post(
            f"{API}/notifications/{notice['id']}/read", headers=other.headers
        )
    ).status_code == 404
    read = await client.post(
        f"{API}/notifications/{notice['id']}/read", headers=buyer.headers
    )
    assert read.json()["is_read"] is True
    assert await _inbox(client, buyer, unread_only=True) == []

    await _book(client, buyer, event, ticket_type)
    cleared = await client.post(f"{API}/notifications/read-all", headers=buyer.headers)
    assert cleared.json() == {"unread": 1}


async def test_payment_failure_in_russian(client: AsyncClient, sent_emails):
    owner = await create_organizer(client)
    event = await create_event(client, owner, title="Джазовый вечер")
    paid = await add_ticket_type(client, owner, event["id"], price_kzt=4000)
    await client.post(f"{API}/events/{event['id']}/publish", headers=owner.headers)
    await activate_paid_sales(event["id"])
    buyer = await create_account(client)
    await set_user_fields(buyer.id, preferred_language="ru")
    order = (
        await client.post(
            f"{API}/events/{event['id']}/orders",
            json={"items": [{"ticket_type_id": paid["id"], "quantity": 1}]},
            headers=buyer.headers,
        )
    ).json()
    sent_emails.clear()

    await client.post(
        f"{API}/orders/{order['id']}/pay",
        json={"outcome": "failure", "failure_reason": "Карта отклонена"},
        headers=buyer.headers,
    )

    [message] = sent_emails
    assert message.subject == "Оплата не прошла: «Джазовый вечер»"
    assert "Карта отклонена" in message.body
    [notice] = await _inbox(client, buyer)
    assert notice["kind"] == "payment_failed"
    assert notice["message"] == "Оплата не прошла: «Джазовый вечер»"


async def test_event_changes_reach_ticket_holders_in_their_language(
    client: AsyncClient, sent_emails
):
    owner, event, ticket_type = await _free_event(client)
    english = await create_account(client)
    kazakh = await create_account(client)
    await set_user_fields(kazakh.id, preferred_language="kk")
    for buyer in (english, kazakh):
        await _book(client, buyer, event, ticket_type)
    url = f"{API}/events/{event['id']}"

    sent_emails.clear()
    # A title change is not something ticket holders need to hear about
    await client.patch(url, json={"title": "Renamed concert"}, headers=owner.headers)
    assert sent_emails == []

    new_start = (datetime.now(UTC) + timedelta(days=45)).replace(microsecond=0)
    await client.patch(
        url,
        json={
            "start_at": new_start.isoformat(),
            "end_at": (new_start + timedelta(hours=2)).isoformat(),
            "venue_name": "Republic Palace",
        },
        headers=owner.headers,
    )

    by_recipient = {m.to: m for m in sent_emails}
    assert set(by_recipient) == {english.email, kazakh.email}
    assert by_recipient[english.email].subject == "Renamed concert has changed"
    assert "Venue: Republic Palace" in by_recipient[english.email].body
    assert by_recipient[kazakh.email].subject == "«Renamed concert» өзгерді"
    assert "Өтетін орны: Republic Palace" in by_recipient[kazakh.email].body
    kinds = [n["kind"] for n in await _inbox(client, kazakh)]
    assert "event_updated" in kinds


async def test_refund_and_cancellation_notices(client: AsyncClient):
    owner = await create_organizer(client)
    event = await create_event(client, owner)
    paid = await add_ticket_type(client, owner, event["id"], price_kzt=3000)
    free = await add_ticket_type(client, owner, event["id"], name="Free")
    await client.post(f"{API}/events/{event['id']}/publish", headers=owner.headers)
    await activate_paid_sales(event["id"])
    payer = await create_account(client)
    free_holder = await create_account(client)
    order = (
        await client.post(
            f"{API}/events/{event['id']}/orders",
            json={"items": [{"ticket_type_id": paid["id"], "quantity": 1}]},
            headers=payer.headers,
        )
    ).json()
    await client.post(f"{API}/orders/{order['id']}/pay", json={}, headers=payer.headers)
    await _book(client, free_holder, event, free)

    await client.post(f"{API}/events/{event['id']}/cancel", headers=owner.headers)

    payer_kinds = [n["kind"] for n in await _inbox(client, payer)]
    assert payer_kinds[0] == "refund_completed"
    holder_kinds = [n["kind"] for n in await _inbox(client, free_holder)]
    assert holder_kinds[0] == "event_cancelled"


async def test_support_reply_notifies_the_requester_in_app(client: AsyncClient):
    owner, event, ticket_type = await _free_event(client)
    buyer = await create_account(client)
    order = await _book(client, buyer, event, ticket_type)
    case = (
        await client.post(
            f"{API}/support/cases",
            json={
                "category": "ticket_delivery",
                "subject": "Lost ticket",
                "message": "Help",
                "order_id": order["id"],
            },
            headers=buyer.headers,
        )
    ).json()
    owner_inbox = await _inbox(client, owner)
    assert owner_inbox[0]["kind"] == "support_new"

    await client.post(
        f"{API}/support/cases/{case['id']}/messages",
        json={"body": "Here it is."},
        headers=owner.headers,
    )

    latest = (await _inbox(client, buyer))[0]
    assert latest["kind"] == "support_reply"
    assert latest["link"] == f"/support/{case['id']}"


async def test_notifications_need_sign_in(client: AsyncClient):
    assert (await client.get(f"{API}/notifications")).status_code == 401
    account = await create_account(client)
    token = await login(client, account.email, PASSWORD)
    assert (
        await client.get(
            f"{API}/notifications", headers={"Authorization": f"Bearer {token}"}
        )
    ).status_code == 200
