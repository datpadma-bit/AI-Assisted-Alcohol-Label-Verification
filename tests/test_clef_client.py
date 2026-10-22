import httpx
import pytest

from app.clef_client import ClefClient
from app.config import settings


@pytest.mark.asyncio
async def test_workers_ai_request_uses_bearer_token(monkeypatch):
    monkeypatch.setattr(settings, "cloudflare_account_id", "test-account")
    monkeypatch.setattr(settings, "cloudflare_api_token", "test-token")
    monkeypatch.setattr(settings, "clef_base_url", "")
    received_authorization = None

    async def handle_request(request):
        nonlocal received_authorization
        received_authorization = request.headers["Authorization"]
        return httpx.Response(200, json={"result": {"answers": {}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle_request)) as http_client:
        async with ClefClient(http_client) as client:
            answers = await client.decide("state", {})

    assert answers == {}
    assert received_authorization == "Bearer test-token"
