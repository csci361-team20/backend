"""Phase 5: paid-sales activation (SRS 3.2, 4.5, UC2) and its admin controls."""

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

VALID_IBAN = "KZ86 125K ZT50 0410 0100"
VALID_IIN = "900101300126"
TERMS = "2026-11"


async def _paid_event(client: AsyncClient, owner, price: int = 8000):
    event = await create_event(client, owner)
    ticket_type = await add_ticket_type(client, owner, event["id"], price_kzt=price)
    await client.post(f"{API}/events/{event['id']}/publish", headers=owner.headers)
    return event, ticket_type


async def _verify_and_add_payout(client: AsyncClient, owner) -> None:
    identity = await client.post(
        f"{API}/organizers/me/verification",
        json={"legal_name": "Arman Bekov", "tax_id": VALID_IIN},
        headers=owner.headers,
    )
    assert identity.status_code == 200, identity.text
    payout = await client.put(
        f"{API}/organizers/me/payout-account",
        json={
            "holder_name": "Arman Bekov",
            "bank_name": "Halyk Bank",
            "iban": VALID_IBAN,
        },
        headers=owner.headers,
    )
    assert payout.status_code == 200, payout.text


async def _fully_activate(client: AsyncClient, owner, event_id: str) -> dict:
    await _verify_and_add_payout(client, owner)
    base = f"{API}/events/{event_id}/activation"
    assert (
        await client.post(f"{base}/pay-fee", json={}, headers=owner.headers)
    ).status_code == 200
    assert (
        await client.post(
            f"{base}/accept-terms", json={"terms_version": TERMS}, headers=owner.headers
        )
    ).status_code == 200
    response = await client.post(f"{base}/activate", headers=owner.headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _order(client: AsyncClient, buyer, event_id: str, ticket_type_id: str):
    return await client.post(
        f"{API}/events/{event_id}/orders",
        json={"items": [{"ticket_type_id": ticket_type_id, "quantity": 1}]},
        headers=buyer.headers,
    )


# --- The checklist ------------------------------------------------------------


async def test_checklist_starts_empty_and_lists_the_srs_steps(client: AsyncClient):
    owner = await create_organizer(client)
    event = await create_event(client, owner)

    response = await client.get(
        f"{API}/events/{event['id']}/activation", headers=owner.headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["fee_kzt"] == 2500
    assert body["terms_version"] == TERMS
    assert body["can_activate"] is False
    assert body["is_simulated"] is True
    assert [(c["item"], c["done"]) for c in body["checklist"]] == [
        ("paid_ticket_type", False),
        ("identity_verified", False),
        ("activation_fee_paid", False),
        ("payout_account", False),
        ("terms_accepted", False),
    ]
    assert all(c["hint"] for c in body["checklist"])


async def test_full_activation_opens_paid_checkout(client: AsyncClient, sent_emails):
    owner = await create_organizer(client)
    buyer = await create_account(client)
    event, ticket_type = await _paid_event(client, owner)
    assert (
        await _order(client, buyer, event["id"], ticket_type["id"])
    ).status_code == 400

    sent_emails.clear()
    activation = await _fully_activate(client, owner, event["id"])

    assert activation["status"] == "active"
    assert activation["activated_at"] is not None
    assert all(c["done"] for c in activation["checklist"])
    # Payout-account and paid-sales notices, both to the owner
    assert {m.to for m in sent_emails} == {owner.email}
    assert any("Paid sales are open" in m.subject for m in sent_emails)
    shown = (await client.get(f"{API}/events/{event['id']}")).json()
    assert shown["paid_sales_open"] is True

    order = await _order(client, buyer, event["id"], ticket_type["id"])
    assert order.status_code == 201, order.text
    paid = await client.post(
        f"{API}/orders/{order.json()['id']}/pay", json={}, headers=buyer.headers
    )
    assert paid.json()["status"] == "confirmed"

    timeline = (
        await client.get(
            f"{API}/events/{event['id']}/activity",
            params={"area": "activation"},
            headers=owner.headers,
        )
    ).json()
    assert [e["action"] for e in timeline] == [
        "activation.activated",
        "activation.terms_accepted",
        "activation.fee_paid",
    ]


async def test_activate_refuses_an_unfinished_checklist(client: AsyncClient):
    owner = await create_organizer(client)
    event, _ = await _paid_event(client, owner)

    response = await client.post(
        f"{API}/events/{event['id']}/activation/activate", headers=owner.headers
    )

    assert response.status_code == 409
    assert "Verify your identity" in response.json()["detail"]


async def test_fee_failure_and_terms_version(client: AsyncClient):
    owner = await create_organizer(client)
    event, _ = await _paid_event(client, owner)
    base = f"{API}/events/{event['id']}/activation"

    declined = await client.post(
        f"{base}/pay-fee", json={"outcome": "failure"}, headers=owner.headers
    )
    assert declined.status_code == 402
    paid = await client.post(f"{base}/pay-fee", json={}, headers=owner.headers)
    assert paid.json()["fee_paid_at"] is not None
    twice = await client.post(f"{base}/pay-fee", json={}, headers=owner.headers)
    assert twice.status_code == 409

    stale = await client.post(
        f"{base}/accept-terms", json={"terms_version": "2025-01"}, headers=owner.headers
    )
    assert stale.status_code == 409


async def test_only_the_owner_handles_money_and_terms(client: AsyncClient):
    owner = await create_organizer(client)
    manager = await create_account(client)
    admin = await create_account(client, admin=True)
    event, _ = await _paid_event(client, owner)
    await client.post(
        f"{API}/events/{event['id']}/staff",
        json={"email": manager.email, "role": "manager"},
        headers=owner.headers,
    )
    base = f"{API}/events/{event['id']}/activation"

    # Managers and admins may look at the checklist ...
    assert (await client.get(base, headers=manager.headers)).status_code == 200
    assert (await client.get(base, headers=admin.headers)).status_code == 200
    # ... but cannot pay, accept terms or activate for the organizer
    for account in (manager, admin):
        assert (
            await client.post(f"{base}/pay-fee", json={}, headers=account.headers)
        ).status_code == 403
        assert (
            await client.post(
                f"{base}/accept-terms",
                json={"terms_version": TERMS},
                headers=account.headers,
            )
        ).status_code == 403
        assert (
            await client.post(f"{base}/activate", headers=account.headers)
        ).status_code == 403


# --- Identity and payout account ----------------------------------------------


async def test_identity_and_payout_validation_and_masking(client: AsyncClient):
    owner = await create_organizer(client)

    bad_iin = await client.post(
        f"{API}/organizers/me/verification",
        json={"legal_name": "Arman Bekov", "tax_id": "900101300120"},
        headers=owner.headers,
    )
    assert bad_iin.status_code == 422
    bad_iban = await client.put(
        f"{API}/organizers/me/payout-account",
        json={
            "holder_name": "A B",
            "bank_name": "Halyk",
            "iban": "KZ00125KZT5004100100",
        },
        headers=owner.headers,
    )
    assert bad_iban.status_code == 422

    await _verify_and_add_payout(client, owner)
    me = (await client.get(f"{API}/organizers/me", headers=owner.headers)).json()
    assert me["verification_status"] == "verified"
    assert me["tax_id_masked"].endswith("0126")
    assert VALID_IIN not in str(me)
    payout = (
        await client.get(f"{API}/organizers/me/payout-account", headers=owner.headers)
    ).json()
    assert payout["iban_masked"].startswith("KZ86") and payout["iban_masked"].endswith(
        "0100"
    )
    assert payout["is_verified"] is True

    public = (await client.get(f"{API}/organizers/{me['id']}")).json()
    assert "tax_id_masked" not in public and "legal_name" not in public


async def test_rejected_organizer_needs_admin_after_resubmitting(client: AsyncClient):
    owner = await create_organizer(client)
    admin = await create_account(client, admin=True)
    profile = (await client.get(f"{API}/organizers/me", headers=owner.headers)).json()
    await client.patch(
        f"{API}/organizers/{profile['id']}/verification",
        json={"verification_status": "rejected"},
        headers=admin.headers,
    )

    resubmitted = await client.post(
        f"{API}/organizers/me/verification",
        json={"legal_name": "Arman Bekov", "tax_id": VALID_IIN},
        headers=owner.headers,
    )

    assert resubmitted.json()["verification_status"] == "pending"


# --- Admin controls -----------------------------------------------------------


async def test_admin_suspension_stops_paid_sales_only(client: AsyncClient, sent_emails):
    owner = await create_organizer(client)
    buyer = await create_account(client)
    admin = await create_account(client, admin=True)
    event, paid_type = await _paid_event(client, owner)
    free_type = await add_ticket_type(client, owner, event["id"], name="Free")
    await _fully_activate(client, owner, event["id"])
    pending = (await _order(client, buyer, event["id"], paid_type["id"])).json()
    sent_emails.clear()

    suspend_url = f"{API}/admin/events/{event['id']}/paid-sales/suspend"
    assert (
        await client.post(
            suspend_url, json={"reason": "Fraud check"}, headers=owner.headers
        )
    ).status_code == 403
    suspended = await client.post(
        suspend_url, json={"reason": "Reported as a scam"}, headers=admin.headers
    )
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["status"] == "suspended"
    assert [m.to for m in sent_emails] == [owner.email]
    assert "on hold" in sent_emails[0].body
    sent_emails.clear()

    other = await create_account(client)
    blocked = await _order(client, other, event["id"], paid_type["id"])
    assert blocked.status_code == 409
    assert "suspended" in blocked.json()["detail"]
    late = await client.post(
        f"{API}/orders/{pending['id']}/pay", json={}, headers=buyer.headers
    )
    assert late.status_code == 409
    assert (
        await _order(client, other, event["id"], free_type["id"])
    ).status_code == 201

    sent_emails.clear()
    resumed = await client.post(
        f"{API}/admin/events/{event['id']}/paid-sales/resume", headers=admin.headers
    )
    assert resumed.json()["status"] == "active"
    assert [m.to for m in sent_emails] == [owner.email]
    assert "no longer on hold" in sent_emails[0].body
    assert (
        await _order(client, other, event["id"], paid_type["id"])
    ).status_code == 201


async def test_admin_lists_activation_records(client: AsyncClient):
    owner = await create_organizer(client)
    admin = await create_account(client, admin=True)
    event, _ = await _paid_event(client, owner)
    await _fully_activate(client, owner, event["id"])

    response = await client.get(
        f"{API}/admin/activations", params={"status": "active"}, headers=admin.headers
    )
    assert response.status_code == 200
    record = next(r for r in response.json() if r["event_id"] == event["id"])
    assert record["fee_kzt"] == 2500
    assert record["fee_payment_reference"].startswith("SIM-")
    assert record["organizer_name"] == "Steppe Events"
    assert (
        await client.get(f"{API}/admin/activations", headers=owner.headers)
    ).status_code == 403


async def test_fee_change_keeps_existing_snapshots(client: AsyncClient):
    owner = await create_organizer(client)
    admin = await create_account(client, admin=True)
    first, _ = await _paid_event(client, owner)
    base = f"{API}/events/{first['id']}/activation"
    await client.post(f"{base}/pay-fee", json={}, headers=owner.headers)
    try:
        changed = await client.patch(
            f"{API}/admin/settings",
            json={"activation_fee_kzt": 4000},
            headers=admin.headers,
        )
        assert changed.json()["activation_fee_kzt"] == 4000

        assert (await client.get(base, headers=owner.headers)).json()["fee_kzt"] == 2500
        second, _ = await _paid_event(client, owner)
        fresh = await client.get(
            f"{API}/events/{second['id']}/activation", headers=owner.headers
        )
        assert fresh.json()["fee_kzt"] == 4000
    finally:
        await client.patch(
            f"{API}/admin/settings",
            json={"activation_fee_kzt": 2500},
            headers=admin.headers,
        )


async def test_bookings_switch_pauses_new_orders(client: AsyncClient):
    owner = await create_organizer(client)
    buyer = await create_account(client)
    admin = await create_account(client, admin=True)
    event = await create_event(client, owner, publish=True)
    ticket_type = (await client.get(f"{API}/events/{event['id']}/ticket-types")).json()[
        0
    ]
    try:
        await client.patch(
            f"{API}/admin/settings",
            json={"bookings_enabled": False},
            headers=admin.headers,
        )
        paused = await _order(client, buyer, event["id"], ticket_type["id"])
        assert paused.status_code == 503
    finally:
        await client.patch(
            f"{API}/admin/settings",
            json={"bookings_enabled": True},
            headers=admin.headers,
        )
    assert (
        await _order(client, buyer, event["id"], ticket_type["id"])
    ).status_code == 201


async def test_settings_can_be_saved_back_unchanged(client: AsyncClient):
    """The admin form sends back what it was given; the default must pass too."""
    admin = await create_account(client, admin=True)
    current = (await client.get(f"{API}/admin/settings", headers=admin.headers)).json()
    saved = await client.patch(
        f"{API}/admin/settings",
        json={
            "activation_fee_kzt": current["activation_fee_kzt"],
            "support_email": current["support_email"],
            "bookings_enabled": current["bookings_enabled"],
        },
        headers=admin.headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["support_email"] == current["support_email"]
