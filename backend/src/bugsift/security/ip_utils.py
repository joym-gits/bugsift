"""Per-request client-IP resolution.

Rate limits and abuse counters must be keyed on the *real* client, not
on the socket peer — when the backend sits behind nginx every request
appears to come from the nginx container, so a naive
``request.client.host`` collapses every abuser into one bucket.

We trust ``X-Real-IP`` (set by nginx via
``proxy_set_header X-Real-IP $remote_addr``) when ``trust_proxy`` is on.
Deployments that run the backend directly (no proxy) flip the env flag
off so clients can't spoof the header.
"""

from __future__ import annotations

from fastapi import Request

from bugsift.config import get_settings


def client_ip(request: Request) -> str:
    """Return the caller's IP. Falls back to the socket peer if no
    trusted proxy header is present, or if proxy trust is disabled."""
    settings = get_settings()
    if settings.trust_proxy:
        real_ip = request.headers.get("x-real-ip", "").strip()
        if real_ip:
            return real_ip
    peer = request.client.host if request.client else None
    return peer or "unknown"
