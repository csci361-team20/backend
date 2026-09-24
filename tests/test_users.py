import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.anyio
async def test_users_router_exists():
    assert app is not None


@pytest.mark.anyio
async def test_get_users():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/users/")

    assert response.status_code == 200
    assert response.json() == {"1": "neo"}


@pytest.mark.anyio
async def test_unknown_users_route_returns_404():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/users/unknown")

    assert response.status_code == 404
