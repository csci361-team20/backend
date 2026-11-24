"""Fill an empty database with sample organizers, events and ticket types.

For local development and demos only. Run inside the backend container:

    docker exec biletflow_copy_backend .venv/bin/python -m scripts.seed_demo

It goes through the real API (same validation as the website), then marks the
sample accounts as email-confirmed and opens paid sales on most events, with
the same activation record the checklist leaves. Running it again adds only
what is missing, such as activation records for sample events opened before
the seed wrote them.

Sample accounts all use the password in DEMO_PASSWORD below (local test value):
  - attendee:  dana@demo.biletflow.kz
  - admin:     admin@demo.biletflow.kz
  - organizers: listed in ORGANIZERS
"""

import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.main import app
from app.modules.activation.enums import CURRENT_TERMS_VERSION, ActivationStatus
from app.modules.activation.models import EventActivation
from app.modules.events.models import Event
from app.modules.organizers.models import OrganizerProfile
from app.modules.platform.service import get_settings
from app.modules.users.models import User

API = "/api/v1"
DEMO_PASSWORD = "biletflow-demo-2026"
ALMATY = ZoneInfo("Asia/Almaty")

ORGANIZERS = {
    "steppe": ("Arman Sadykov", "arman@demo.biletflow.kz", "Steppe Sound Agency"),
    "kino": ("Saule Tulegenova", "saule@demo.biletflow.kz", "Kino Club Almaty"),
    "stage": ("Yerlan Abenov", "yerlan@demo.biletflow.kz", "Astana Stage House"),
}

# key, organizer, title, subtitle, category, city, venue, address,
# days from now, local hour, hours long, paid sales on, ticket types
# (name, description, price, quantity[, sale starts in days])
EVENTS = [
    (
        "steppe",
        "Aigerim & the Steppe Sound",
        "The autumn tour comes home.",
        "concert",
        "Almaty",
        "Almaty Arena",
        "Momyshuly St 42",
        6,
        20,
        3,
        True,
        [
            ("Standing", "General admission, dance floor", 9500, 400),
            ("Seated", "Numbered tribune seats", 14000, 200),
            ("Backstage", "Seated, plus meet the band after the show", 32000, 20),
        ],
        "One stage, a full band and a room singing back. Two hours of new songs, "
        "old favourites and the sounds of the steppe. Doors open an hour early.",
    ),
    (
        "kino",
        "The Long Afternoon",
        "A 70mm late-night screening.",
        "cinema",
        "Almaty",
        "Arman Cinema",
        "Dostyk Ave 136",
        3,
        22,
        3,
        True,
        [("Screening", "One seat, any row", 3500, 120)],
        "A late screening for people who still believe a film belongs on a big "
        "screen, followed by a conversation over coffee in the foyer. Original "
        "audio with English subtitles.",
    ),
    (
        "stage",
        "Abai in Three Acts",
        "A new staging of a familiar voice.",
        "theatre",
        "Astana",
        "Astana Opera Chamber Hall",
        "Kunaev St 1",
        12,
        19,
        2,
        True,
        [("Stalls", "Rows 1-12", 8000, 150), ("Balcony", "Rows A-F", 5000, 80)],
        "Three acts trace the life, poetry and restless curiosity of Abai, "
        "performed by the resident ensemble. In Kazakh, with Russian surtitles.",
    ),
    (
        "steppe",
        "Mountain Air Festival",
        "Two days of music above the city.",
        "festival",
        "Almaty",
        "Shymbulak Plateau",
        "Shymbulak resort",
        20,
        14,
        30,
        True,
        [
            ("Weekend pass", "Both days, all stages", 25000, 1500),
            ("Early bird", "Both days, limited", 18000, 30, 0),
        ],
        "Electronic artists, independent food stalls and a dance floor with a "
        "mountain view. Bring a warm layer for the journey home.",
    ),
    (
        "stage",
        "Open Mic Comedy Night",
        "Local headliners, then the open mic.",
        "comedy",
        "Astana",
        "Underground Bar",
        "Turan Ave 24",
        4,
        20,
        2,
        True,
        [("Entry", "Standing room", 4000, 90)],
        "A small room, a good microphone and no drink minimum. Performances in "
        "Russian and Kazakh. Recommended for ages 18 and over.",
    ),
    (
        "steppe",
        "Tigers vs Falcons: Game Five",
        "The series comes down to this.",
        "sport",
        "Shymkent",
        "Shymkent Sports Palace",
        "Tauke Khan Ave 5",
        9,
        19,
        3,
        True,
        [
            ("Upper stand", "Family seating", 3000, 600),
            ("Courtside", "Rows 1-3", 15000, 40),
        ],
        "Join the home crowd for game five. Gates open one hour before tip-off.",
    ),
    (
        "kino",
        "Short Film Night",
        "Six new Kazakh shorts, free entry.",
        "cinema",
        "Shymkent",
        "Cultural Centre Cinema Hall",
        "Kazybek Bi St 12",
        8,
        16,
        2,
        False,
        [("Free entry", "Registration required", 0, 150)],
        "Six short films by new Kazakh directors, followed by a Q&A with the "
        "filmmakers.",
    ),
    (
        "stage",
        "Jazz on the Left Bank",
        "An evening quartet by the river.",
        "concert",
        "Astana",
        "Riverside Jazz Club",
        "Mangilik El Ave 55",
        15,
        21,
        3,
        True,
        [("Table seat", "Includes a welcome drink", 7000, 60)],
        "A quartet playing standards and new Kazakh jazz. Small tables, warm light, "
        "and two sets with an interval.",
    ),
    (
        "steppe",
        "Dombra Night",
        "Traditional music, new arrangements.",
        "concert",
        "Shymkent",
        "Shymkent Philharmonic",
        "Baidibek Bi Ave 1",
        25,
        19,
        2,
        False,
        [("Parterre", "Rows 1-20", 6000, 300)],
        "Young dombra players reimagine traditional kuis with strings and "
        "percussion. Paid ticket sales open soon.",
    ),
    (
        "kino",
        "Silent Film with Live Piano",
        "A classic, scored live.",
        "cinema",
        "Almaty",
        "Kino Club Almaty",
        "Abylai Khan Ave 61",
        30,
        19,
        2,
        True,
        [("Seat", "Free seating", 4500, 70, 7)],
        "A restored silent classic with an improvised piano score. Tickets go on "
        "sale one week from now.",
    ),
    (
        "stage",
        "Family Puppet Theatre",
        "A morning show for ages 4 and up.",
        "theatre",
        "Almaty",
        "State Puppet Theatre",
        "Abai Ave 2",
        5,
        11,
        1,
        True,
        [("Child", "Ages 4-12", 2000, 100), ("Adult", "Accompanying adult", 2500, 100)],
        "A gentle, colourful show about a fox who learns to share. Around 50 "
        "minutes, no interval.",
    ),
    (
        "steppe",
        "Astana Half Marathon",
        "Run the capital at sunrise.",
        "sport",
        "Astana",
        "Expo Boulevard",
        "Mangilik El Ave 53/1",
        40,
        8,
        4,
        True,
        [
            ("10 km", "Timing chip and medal", 6000, 1000),
            ("21 km", "Timing chip, medal and shirt", 9000, 800),
        ],
        "A flat, fast course past the capital's landmarks. Water every 3 km and "
        "a finish-line breakfast.",
    ),
]


def local_start(days: int, hour: int) -> datetime:
    day = datetime.now(ALMATY).date() + timedelta(days=days)
    return datetime(day.year, day.month, day.day, hour, tzinfo=ALMATY)


async def mark_verified(emails: list[str], admin_email: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(User)
            .where(User.email.in_(emails))
            .values(email_verified_at=datetime.now(UTC))
        )
        await db.execute(
            update(User).where(User.email == admin_email).values(is_platform_admin=True)
        )
        await db.commit()


async def register(client: AsyncClient, name: str, email: str) -> None:
    response = await client.post(
        f"{API}/users/",
        json={"full_name": name, "email": email, "password": DEMO_PASSWORD},
    )
    response.raise_for_status()


async def sign_in(client: AsyncClient, email: str) -> dict[str, str]:
    response = await client.post(
        f"{API}/auth/login", data={"username": email, "password": DEMO_PASSWORD}
    )
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def main() -> None:
    async with AsyncSessionLocal() as db:
        first = ORGANIZERS["steppe"][1]
        if (await db.execute(select(User).where(User.email == first))).first():
            print("Sample organizers are already there.")
            await seed_seated_event()
            added = await backfill_activations()
            if added:
                print(f"Added activation records for {added} sample events.")
            return

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://seed") as client:
        others = [
            ("Dana Karimova", "dana@demo.biletflow.kz"),
            ("Aida Nurpeisova", "admin@demo.biletflow.kz"),
        ]
        people = [(name, email) for name, email, _ in ORGANIZERS.values()] + others
        for name, email in people:
            await register(client, name, email)
        await mark_verified([email for _, email in people], "admin@demo.biletflow.kz")

        headers = {}
        for key, (_, email, display_name) in ORGANIZERS.items():
            headers[key] = await sign_in(client, email)
            response = await client.post(
                f"{API}/organizers/",
                json={"display_name": display_name},
                headers=headers[key],
            )
            response.raise_for_status()

        paid_on: list[UUID] = []
        for (
            org,
            title,
            subtitle,
            category,
            city,
            venue,
            address,
            days,
            hour,
            hours,
            paid,
            tickets,
            description,
        ) in EVENTS:
            start = local_start(days, hour)
            response = await client.post(
                f"{API}/events/",
                json={
                    "title": title,
                    "subtitle": subtitle,
                    "description": description,
                    "category": category,
                    "city": city,
                    "venue_name": venue,
                    "venue_address": address,
                    "start_at": start.isoformat(),
                    "end_at": (start + timedelta(hours=hours)).isoformat(),
                    "timezone": "Asia/Almaty",
                    "capacity": sum(t[3] for t in tickets),
                    "refund_policy": "Full refund up to 48 hours before the event.",
                },
                headers=headers[org],
            )
            response.raise_for_status()
            event_id = response.json()["id"]
            for ticket in tickets:
                name, info, price, quantity = ticket[:4]
                body = {
                    "name": name,
                    "description": info,
                    "price_kzt": price,
                    "quantity": quantity,
                    "max_per_order": 8,
                }
                if len(ticket) > 4 and ticket[4]:
                    body["sale_start"] = (
                        datetime.now(UTC) + timedelta(days=ticket[4])
                    ).isoformat()
                (
                    await client.post(
                        f"{API}/events/{event_id}/ticket-types",
                        json=body,
                        headers=headers[org],
                    )
                ).raise_for_status()
            (
                await client.post(
                    f"{API}/events/{event_id}/publish", headers=headers[org]
                )
            ).raise_for_status()
            if paid:
                paid_on.append(UUID(event_id))
            print(f"  {title} ({city}, {start:%d %b %H:%M})")

    await open_paid_sales(paid_on)
    print(f"Added {len(EVENTS)} events; paid sales open on {len(paid_on)}.")
    await seed_seated_event()


async def open_paid_sales(event_ids: list[UUID]) -> None:
    """Open paid sales with a completed activation record (SRS 4.5).

    The record matches what the checklist leaves behind, so the admin's
    activation list shows the sample events. The fee payment is simulated.
    """
    if not event_ids:
        return
    async with AsyncSessionLocal() as db:
        fee = (await get_settings(db)).activation_fee_kzt
        events = (
            (await db.execute(select(Event).where(Event.id.in_(event_ids))))
            .scalars()
            .all()
        )
        now = datetime.now(UTC)
        for event in events:
            # A backfilled event keeps the time its sales were first opened
            event.paid_sales_activated_at = event.paid_sales_activated_at or now
            db.add(
                EventActivation(
                    event_id=event.id,
                    organizer_profile_id=event.organizer_profile_id,
                    status=ActivationStatus.ACTIVE,
                    fee_kzt=fee,
                    fee_paid_at=now,
                    fee_payment_reference=f"SIM-{secrets.token_hex(8).upper()}",
                    terms_version=CURRENT_TERMS_VERSION,
                    terms_accepted_at=now,
                    activated_at=event.paid_sales_activated_at,
                )
            )
        await db.commit()


async def backfill_activations() -> int:
    """Add records for sample events whose paid sales were opened without one.

    Only events of the sample organizers are touched.
    """
    async with AsyncSessionLocal() as db:
        missing = (
            (
                await db.execute(
                    select(Event.id)
                    .join(
                        OrganizerProfile,
                        OrganizerProfile.id == Event.organizer_profile_id,
                    )
                    .join(User, User.id == OrganizerProfile.user_id)
                    .outerjoin(EventActivation, EventActivation.event_id == Event.id)
                    .where(
                        User.email.in_([email for _, email, _ in ORGANIZERS.values()]),
                        Event.paid_sales_activated_at.is_not(None),
                        EventActivation.id.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
    await open_paid_sales(list(missing))
    return len(missing)


SEATED_TITLE = "Winter Gala: State Symphony Orchestra"


async def seed_seated_event() -> None:
    """One event with numbered seats in BiletFlow Hall (added once)."""
    async with AsyncSessionLocal() as db:
        if (await db.execute(select(Event).where(Event.title == SEATED_TITLE))).first():
            return
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://seed") as client:
        headers = await sign_in(client, ORGANIZERS["stage"][1])
        layouts = (await client.get(f"{API}/venue-layouts", headers=headers)).json()
        hall = layouts[0]
        start = local_start(18, 19)
        response = await client.post(
            f"{API}/events/",
            json={
                "title": SEATED_TITLE,
                "subtitle": "Tchaikovsky and Kazakh composers, numbered seats.",
                "description": "The winter programme: the Nutcracker suite, "
                "Brusilovsky's Kyz-Zhibek overture and new works by young Kazakh "
                "composers. Choose your own seats in the stalls or the balcony.",
                "category": "concert",
                "city": hall["city"],
                "venue_name": hall["name"],
                "venue_address": hall["address"],
                "start_at": start.isoformat(),
                "end_at": (start + timedelta(hours=2)).isoformat(),
                "timezone": "Asia/Almaty",
                "capacity": hall["total_seats"],
                "refund_policy": "Full refund up to 48 hours before the concert.",
            },
            headers=headers,
        )
        response.raise_for_status()
        event_id = response.json()["id"]
        prices = {
            "A": ("Front stalls", 12000),
            "B": ("Rear stalls", 8000),
            "C": ("Balcony", 5000),
        }
        (
            await client.post(
                f"{API}/events/{event_id}/seating",
                json={
                    "venue_id": hall["id"],
                    "categories": [
                        {
                            "category": key,
                            "name": name,
                            "price_kzt": amount,
                            "max_per_order": 8,
                        }
                        for key, (name, amount) in prices.items()
                        if key in hall["categories"]
                    ],
                },
                headers=headers,
            )
        ).raise_for_status()
        (
            await client.post(f"{API}/events/{event_id}/publish", headers=headers)
        ).raise_for_status()
    await open_paid_sales([UUID(event_id)])
    print(f"  {SEATED_TITLE} (numbered seats)")


if __name__ == "__main__":
    asyncio.run(main())
