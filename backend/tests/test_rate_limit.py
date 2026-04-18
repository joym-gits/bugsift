from __future__ import annotations

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis

from bugsift.github import rate_limit


@pytest_asyncio.fixture(autouse=True)
async def _fake_redis(monkeypatch: pytest.MonkeyPatch):
    client = FakeRedis(decode_responses=True)
    monkeypatch.setattr(rate_limit, "_redis", client)
    yield client
    await client.aclose()


async def test_under_limit_allows_events() -> None:
    for _ in range(5):
        assert await rate_limit.allow_installation_event(123, limit=10) is True


async def test_crossing_limit_returns_false() -> None:
    for _ in range(3):
        assert await rate_limit.allow_installation_event(7, limit=3) is True
    assert await rate_limit.allow_installation_event(7, limit=3) is False
    assert await rate_limit.allow_installation_event(7, limit=3) is False


async def test_different_installations_are_independent() -> None:
    for _ in range(3):
        assert await rate_limit.allow_installation_event(1, limit=3) is True
    # Install 2 has its own window.
    assert await rate_limit.allow_installation_event(2, limit=3) is True
