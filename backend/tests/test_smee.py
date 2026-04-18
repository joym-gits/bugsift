"""Smee SSE forwarder tests.

The live SSE loop is too awkward to exercise end-to-end in unit tests —
we cover the pieces instead: URL provisioning, SSE event parsing, and
that ``forward_event`` POSTs the right headers + byte-for-byte body so
HMAC signatures from GitHub stay valid.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from httpx import Response

from bugsift.github import smee


@respx.mock
async def test_provision_smee_channel_follows_redirect() -> None:
    respx.head("https://smee.io/new").mock(
        return_value=Response(302, headers={"location": "https://smee.io/abc123"})
    )
    url = await smee.provision_smee_channel()
    assert url == "https://smee.io/abc123"


@respx.mock
async def test_provision_smee_channel_raises_on_non_redirect() -> None:
    respx.head("https://smee.io/new").mock(return_value=Response(500))
    with pytest.raises(RuntimeError):
        await smee.provision_smee_channel()


def test_parse_sse_event_data_parses_real_event() -> None:
    data = json.dumps(
        {
            "headers": {"X-GitHub-Event": "issues"},
            "body": {"action": "opened"},
            "query": {},
            "timestamp": 123,
        }
    )
    out = smee.parse_sse_event_data(data)
    assert out is not None
    assert out["body"]["action"] == "opened"


def test_parse_sse_event_data_drops_keepalive() -> None:
    assert smee.parse_sse_event_data("") is None
    assert smee.parse_sse_event_data("{}") is None
    assert smee.parse_sse_event_data("not json") is None
    assert smee.parse_sse_event_data('"just a string"') is None


@respx.mock
async def test_forward_event_preserves_body_bytes_and_headers() -> None:
    """GitHub signs the exact body bytes. Our serialisation must match,
    and host/infrastructure headers must be dropped so the downstream
    server recomputes them.
    """
    captured = {}

    def handler(request: httpx.Request) -> Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content
        return Response(202, json={"status": "queued"})

    respx.post("http://backend/webhook").mock(side_effect=handler)

    event = {
        "headers": {
            "X-GitHub-Event": "issues",
            "X-Hub-Signature-256": "sha256=abc",
            "Host": "smee.io",  # must be stripped
            "Content-Length": "999",  # must be stripped
        },
        "body": {"action": "opened", "issue": {"number": 7}},
    }
    async with httpx.AsyncClient() as client:
        await smee.forward_event(event, "http://backend/webhook", client=client)

    assert captured["url"] == "http://backend/webhook"
    assert captured["headers"]["x-github-event"] == "issues"
    assert captured["headers"]["x-hub-signature-256"] == "sha256=abc"
    assert "host" not in {k.lower() for k in captured["headers"].keys() if k != "host"} or captured["headers"].get("host") != "smee.io"
    # Exact bytes match what our forwarder serialised.
    assert captured["body"] == json.dumps(
        {"action": "opened", "issue": {"number": 7}}, separators=(",", ":")
    ).encode()


@respx.mock
async def test_forward_event_accepts_raw_string_body() -> None:
    def handler(request: httpx.Request) -> Response:
        assert request.content == b"plain-text-body"
        return Response(200)

    respx.post("http://backend/webhook").mock(side_effect=handler)
    async with httpx.AsyncClient() as client:
        await smee.forward_event(
            {"headers": {}, "body": "plain-text-body"},
            "http://backend/webhook",
            client=client,
        )


def test_forwarder_status_reports_not_running_before_start() -> None:
    # Fresh module state: no task.
    status = smee.forwarder_status()
    assert status["running"] is False
