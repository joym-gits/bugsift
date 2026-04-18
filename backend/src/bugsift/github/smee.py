"""In-process smee.io webhook tunnel.

GitHub has to post webhooks over the public internet, but a self-hosted
bugsift typically runs on localhost. We bridge the gap by provisioning a
smee.io channel and running a background SSE loop that relays each event
to our own ``/api/webhooks/github``. Zero terminal work on the operator's
side.

The channel URL is cached in Redis at ``bugsift:smee_tunnel_url`` so it
survives backend restarts. Smee itself is stateless, so reusing an old
channel is fine.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from typing import Any

import httpx
from redis.asyncio import Redis

from bugsift.config import get_settings

logger = logging.getLogger(__name__)

TUNNEL_KEY = "bugsift:smee_tunnel_url"
RECONNECT_BACKOFF_SEC = 5.0

# Module-level handle so provision + lifespan can coordinate.
_forwarder_task: asyncio.Task | None = None
_forwarder_url: str | None = None
_redis_client: Redis | None = None


def _local_webhook_target() -> str:
    """URL the forwarder POSTs events to. Inside compose we resolve the
    backend service by name; outside compose, we loop back to localhost.
    """
    return "http://backend:8000/api/webhooks/github"


async def _redis() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(get_settings().redis_url)
    return _redis_client


async def get_tunnel_url() -> str | None:
    value = await (await _redis()).get(TUNNEL_KEY)
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else str(value)


async def store_tunnel_url(url: str) -> None:
    await (await _redis()).set(TUNNEL_KEY, url)


async def clear_tunnel_url() -> None:
    await (await _redis()).delete(TUNNEL_KEY)


async def provision_smee_channel(*, client: httpx.AsyncClient | None = None) -> str:
    """Hit ``https://smee.io/new`` and return the redirected channel URL."""
    close_after = client is None
    c = client or httpx.AsyncClient(follow_redirects=False)
    try:
        response = await c.head("https://smee.io/new", timeout=10.0)
    finally:
        if close_after:
            await c.aclose()
    location = response.headers.get("location")
    if response.status_code not in (301, 302, 303, 307, 308) or not location:
        raise RuntimeError(
            f"smee.io/new did not redirect (status={response.status_code})"
        )
    return location


async def ensure_tunnel_url() -> str:
    """Return a working smee URL, creating one on first use."""
    existing = await get_tunnel_url()
    if existing:
        return existing
    url = await provision_smee_channel()
    await store_tunnel_url(url)
    logger.info("smee: provisioned new tunnel %s", url)
    return url


# -------------------- forwarder --------------------


def parse_sse_event_data(raw: str) -> dict[str, Any] | None:
    """Parse a smee SSE ``data:`` payload into the event dict, or None.

    Smee's format (as of 2024) sends each event as a single ``data:`` line
    containing a JSON object with ``headers``, ``body``, ``query``, and
    ``timestamp``. A stray ``data: {}`` keep-alive line shows up between
    real events and should be ignored.
    """
    data = raw.strip()
    if not data or data == "{}":
        return None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


async def forward_event(
    event: dict[str, Any], target_url: str, *, client: httpx.AsyncClient
) -> None:
    headers = event.get("headers") or {}
    body = event.get("body")
    # Smee delivers the body pre-parsed as a dict; re-serialise it so the
    # payload bytes exactly match what GitHub sent (HMAC verification
    # depends on byte-for-byte identity).
    if isinstance(body, (dict, list)):
        payload_bytes = json.dumps(body, separators=(",", ":")).encode()
    elif isinstance(body, str):
        payload_bytes = body.encode()
    else:
        payload_bytes = b""

    # Strip hop-by-hop and infrastructure headers the receiving server
    # should recompute.
    drop = {"host", "content-length", "connection", "accept-encoding", "transfer-encoding"}
    safe_headers = {k: str(v) for k, v in headers.items() if k.lower() not in drop}
    safe_headers.setdefault("Content-Type", "application/json")

    try:
        await client.post(
            target_url, content=payload_bytes, headers=safe_headers, timeout=20.0
        )
    except httpx.HTTPError as e:
        logger.warning("smee forward failed: %s", e)


async def run_forwarder(smee_url: str, target_url: str) -> None:
    """Consume smee SSE forever, POSTing events to ``target_url``.

    Caller cancels the task to stop. Transient errors (disconnects, 5xx)
    reconnect after a short backoff.
    """
    logger.info("smee forwarder starting: %s -> %s", smee_url, target_url)
    headers = {"Accept": "text/event-stream", "User-Agent": "bugsift-smee/1.0"}
    while True:
        try:
            async with httpx.AsyncClient(timeout=None) as sse_client:
                async with sse_client.stream("GET", smee_url, headers=headers) as response:
                    response.raise_for_status()
                    async with httpx.AsyncClient() as post_client:
                        async for raw_line in response.aiter_lines():
                            if not raw_line.startswith("data:"):
                                continue
                            event = parse_sse_event_data(raw_line[len("data:") :])
                            if event is None or "body" not in event:
                                continue
                            await forward_event(event, target_url, client=post_client)
        except asyncio.CancelledError:
            logger.info("smee forwarder cancelled")
            raise
        except Exception as e:  # pragma: no cover - reconnect loop
            logger.warning(
                "smee stream error (%s); reconnecting in %.0fs",
                e,
                RECONNECT_BACKOFF_SEC,
            )
            await asyncio.sleep(RECONNECT_BACKOFF_SEC)


# -------------------- lifecycle --------------------


async def start_forwarder_if_url_present() -> None:
    """Called from the FastAPI lifespan. No-op if no tunnel URL stored."""
    url = await get_tunnel_url()
    if url:
        await start_forwarder(url)


async def start_forwarder(tunnel_url: str) -> None:
    """Start (or hot-swap) the singleton forwarder task."""
    global _forwarder_task, _forwarder_url
    if _forwarder_task is not None and not _forwarder_task.done():
        if _forwarder_url == tunnel_url:
            return  # already running against the right URL
        await stop_forwarder()
    _forwarder_url = tunnel_url
    _forwarder_task = asyncio.create_task(
        run_forwarder(tunnel_url, _local_webhook_target()),
        name="bugsift-smee-forwarder",
    )


async def stop_forwarder() -> None:
    global _forwarder_task, _forwarder_url
    if _forwarder_task is None:
        return
    _forwarder_task.cancel()
    with suppress(asyncio.CancelledError, Exception):
        await _forwarder_task
    _forwarder_task = None
    _forwarder_url = None


def forwarder_status() -> dict[str, Any]:
    """For the UI's status panel."""
    return {
        "running": _forwarder_task is not None and not _forwarder_task.done(),
        "tunnel_url": _forwarder_url,
    }
