from __future__ import annotations

import pytest
import pytest_asyncio

from bugsift.api.deps import get_current_user, get_optional_user
from bugsift.db.models import User, UserApiKey
from bugsift.security import crypto


@pytest_asyncio.fixture
async def logged_in(client, session):
    user = User(github_id=42, github_login="octocat", email="o@example.com")
    session.add(user)
    await session.commit()
    await session.refresh(user)

    async def _fake_user() -> User:
        return user

    client.app.dependency_overrides[get_current_user] = _fake_user
    client.app.dependency_overrides[get_optional_user] = _fake_user
    yield user
    client.app.dependency_overrides.pop(get_current_user, None)
    client.app.dependency_overrides.pop(get_optional_user, None)


def test_list_keys_requires_login(client) -> None:
    assert client.get("/keys").status_code == 401


def test_create_list_delete_key(client, logged_in: User) -> None:
    created = client.post(
        "/keys", json={"provider": "anthropic", "key": "sk-ant-api03-abcdef1234567890"}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["provider"] == "anthropic"
    assert body["masked_hint"].startswith("sk-")
    assert body["masked_hint"].endswith("7890")
    assert "sk-ant-api03-abcdef" not in body["masked_hint"]

    listed = client.get("/keys").json()
    assert len(listed) == 1
    assert listed[0]["id"] == body["id"]
    assert "encrypted_key" not in listed[0]

    assert client.delete(f"/keys/{body['id']}").status_code == 204
    assert client.get("/keys").json() == []


def test_create_key_replaces_existing_for_same_provider(client, logged_in: User) -> None:
    client.post("/keys", json={"provider": "anthropic", "key": "sk-ant-first-1234567890"})
    client.post("/keys", json={"provider": "anthropic", "key": "sk-ant-second-abcdefgh"})
    listed = client.get("/keys").json()
    assert len(listed) == 1
    assert listed[0]["masked_hint"].endswith("efgh")


@pytest.mark.asyncio
async def test_cannot_delete_another_users_key(client, logged_in: User, session) -> None:
    other = User(github_id=99, github_login="other", email=None)
    session.add(other)
    await session.commit()
    await session.refresh(other)

    foreign = UserApiKey(
        user_id=other.id,
        provider="anthropic",
        encrypted_key=crypto.encrypt("sk-other-key-abcdefgh"),
        masked_hint="sk-••••••efgh",
    )
    session.add(foreign)
    await session.commit()
    await session.refresh(foreign)

    assert client.delete(f"/keys/{foreign.id}").status_code == 404
