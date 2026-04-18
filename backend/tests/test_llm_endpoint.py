from __future__ import annotations

import pytest
import pytest_asyncio
import respx
from httpx import Response

from bugsift.api.deps import get_current_user, get_optional_user
from bugsift.db.models import User, UserApiKey
from bugsift.llm.anthropic import API_BASE as ANTHROPIC_BASE
from bugsift.security import crypto


@pytest_asyncio.fixture
async def logged_in_with_anthropic(client, session):
    user = User(github_id=42, github_login="maintainer", email="m@example.com")
    session.add(user)
    await session.commit()
    await session.refresh(user)

    session.add(
        UserApiKey(
            user_id=user.id,
            provider="anthropic",
            encrypted_key=crypto.encrypt("sk-ant-live-key"),
            masked_hint="sk-•••• live",
        )
    )
    await session.commit()

    async def _fake_user() -> User:
        return user

    client.app.dependency_overrides[get_current_user] = _fake_user
    client.app.dependency_overrides[get_optional_user] = _fake_user
    yield user
    client.app.dependency_overrides.pop(get_current_user, None)
    client.app.dependency_overrides.pop(get_optional_user, None)


def test_test_endpoint_requires_login(client) -> None:
    assert client.post("/llm/test", json={"provider": "anthropic"}).status_code == 401


@respx.mock
def test_test_endpoint_happy_path(client, logged_in_with_anthropic: User) -> None:
    respx.post(f"{ANTHROPIC_BASE}/v1/messages").mock(
        return_value=Response(
            200,
            json={
                "model": "claude-sonnet-4-6",
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 4, "output_tokens": 1},
            },
        )
    )
    r = client.post("/llm/test", json={"provider": "anthropic"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["provider"] == "anthropic"
    assert body["sample"] == "ok"
    assert body["model"] == "claude-sonnet-4-6"
    assert isinstance(body["latency_ms"], int)


@respx.mock
def test_test_endpoint_returns_ok_false_on_provider_error(
    client, logged_in_with_anthropic: User
) -> None:
    respx.post(f"{ANTHROPIC_BASE}/v1/messages").mock(
        return_value=Response(401, text='{"type":"error","error":{"message":"invalid x-api-key"}}')
    )
    r = client.post("/llm/test", json={"provider": "anthropic"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "invalid x-api-key" in body["error"]


@pytest.mark.asyncio
async def test_test_endpoint_returns_ok_false_when_no_key(client, session) -> None:
    user = User(github_id=77, github_login="keyless", email=None)
    session.add(user)
    await session.commit()
    await session.refresh(user)

    async def _fake_user() -> User:
        return user

    client.app.dependency_overrides[get_current_user] = _fake_user
    try:
        r = client.post("/llm/test", json={"provider": "anthropic"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert "no anthropic key" in body["error"]
    finally:
        client.app.dependency_overrides.pop(get_current_user, None)
