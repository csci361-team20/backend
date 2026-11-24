import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.storage import LocalStorage
from app.modules.events import images
from tests.conftest import API, create_account, create_event, create_organizer

pytestmark = pytest.mark.anyio

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


@pytest.fixture
def media_dir(tmp_path, monkeypatch):
    """Store uploads in a temporary folder instead of ./media."""
    storage = LocalStorage(tmp_path, "http://test")
    monkeypatch.setattr(images, "get_storage", lambda: storage)
    return tmp_path


async def _upload(
    client: AsyncClient, account, event_id: str, content: bytes, name: str
):
    return await client.post(
        f"{API}/events/{event_id}/images",
        files={"file": (name, content, "application/octet-stream")},
        headers=account.headers,
    )


async def test_upload_sets_cover_and_lists_images(client: AsyncClient, media_dir):
    owner = await create_organizer(client)
    event = await create_event(client, owner, publish=True)

    first = await _upload(client, owner, event["id"], PNG, "poster.png")
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["content_type"] == "image/png"
    assert body["url"].startswith("http://test/api/v1/media/events/")
    assert (media_dir / body["url"].split("/media/", 1)[1]).read_bytes() == PNG

    second = await _upload(client, owner, event["id"], JPEG, "stage.jpg")
    assert second.json()["content_type"] == "image/jpeg"

    listed = await client.get(f"{API}/events/{event['id']}/images")
    assert [i["id"] for i in listed.json()] == [body["id"], second.json()["id"]]
    shown = (await client.get(f"{API}/events/{event['id']}")).json()
    assert shown["cover_image_url"] == body["url"]


async def test_only_real_images_within_limits(
    client: AsyncClient, media_dir, monkeypatch
):
    owner = await create_organizer(client)
    event = await create_event(client, owner)

    # The name says PNG; the bytes say otherwise
    fake = await _upload(
        client, owner, event["id"], b"<script>alert(1)</script>", "x.png"
    )
    assert fake.status_code == 415

    monkeypatch.setattr(settings, "MAX_IMAGE_BYTES", 32)
    too_big = await _upload(client, owner, event["id"], PNG, "big.png")
    assert too_big.status_code == 413


async def test_image_permissions(client: AsyncClient, media_dir):
    owner = await create_organizer(client)
    outsider = await create_account(client)
    event = await create_event(client, owner)

    assert (
        await _upload(client, outsider, event["id"], PNG, "p.png")
    ).status_code == 404
    image = (await _upload(client, owner, event["id"], PNG, "p.png")).json()
    # Draft event: its images are as hidden as the event itself
    assert (await client.get(f"{API}/events/{event['id']}/images")).status_code == 404
    remove = await client.delete(
        f"{API}/events/{event['id']}/images/{image['id']}", headers=outsider.headers
    )
    assert remove.status_code == 404


async def test_removing_cover_promotes_next_image(client: AsyncClient, media_dir):
    owner = await create_organizer(client)
    event = await create_event(client, owner)
    first = (await _upload(client, owner, event["id"], PNG, "a.png")).json()
    second = (await _upload(client, owner, event["id"], JPEG, "b.jpg")).json()

    response = await client.delete(
        f"{API}/events/{event['id']}/images/{first['id']}", headers=owner.headers
    )
    assert response.status_code == 204
    assert not (media_dir / first["url"].split("/media/", 1)[1]).exists()
    shown = (
        await client.get(f"{API}/events/{event['id']}", headers=owner.headers)
    ).json()
    assert shown["cover_image_url"] == second["url"]

    activity = (
        await client.get(f"{API}/events/{event['id']}/activity", headers=owner.headers)
    ).json()
    assert [e["action"] for e in activity][:3] == [
        "event.image_removed",
        "event.image_added",
        "event.image_added",
    ]
