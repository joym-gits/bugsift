"""Per-installation webhook rate limiting (\u00a79).

Max 60 issue events per installation per minute. Excess events are dropped
with a warning; real backoff-and-requeue lands alongside budget enforcement
in Phase 9.

The implementation is a plain Redis INCR with a 60-second TTL on first hit.
Good enough for v1 at the scale we expect; if we ever need a smoother window
we can swap in a sliding-log variant.
"""

from __future__ import annotations

import logging

from redis.asyncio import Redis

from bugsift.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 60
WINDOW_SECONDS = 60

_redis: Redis | None = None


def _client() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


async def allow_installation_event(installation_id: int, *, limit: int | None = None) -> bool:
    """Return ``True`` if this event is within the per-minute budget.

    Every call bumps the counter. On the first hit of a new window we set a
    60s TTL. Crossing the limit logs a warning and returns ``False``.

    ``limit`` defaults to the module-level :data:`DEFAULT_LIMIT`, re-read on
    each call so tests can monkeypatch it.
    """
    effective_limit = limit if limit is not None else DEFAULT_LIMIT
    key = f"rate:install:{installation_id}"
    client = _client()
    count = await client.incr(key)
    if count == 1:
        await client.expire(key, WINDOW_SECONDS)
    if count > effective_limit:
        logger.warning(
            "installation=%s rate-limited: %d events this minute (limit=%d)",
            installation_id,
            count,
            effective_limit,
        )
        return False
    return True


async def reset_for_tests() -> None:
    """Flush the one rate-limit module cache. Tests only."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
    _redis = None
