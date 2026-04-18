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
async def test_forward_event_re_signs_with_stored_webhook_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Smee gives us a parsed body, not the raw bytes GitHub signed. The
    forwarder re-signs with our stored webhook secret so the receiver's
    HMAC check passes; this test pins that contract.
    """
    import hashlib
    import hmac as hmac_mod

    async def _fake_secret() -> str:
        return "my-wh-secret"

    monkeypatch.setattr(smee, "_load_webhook_secret", _fake_secret)

    captured: dict = {}

    def handler(request: httpx.Request) -> Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content
        return Response(202, json={"status": "queued"})

    respx.post("http://backend/webhook").mock(side_effect=handler)

    event = {
        "headers": {
            "X-GitHub-Event": "issues",
            "X-Hub-Signature-256": "sha256=stale-upstream-sig",  # must be overwritten
            "Host": "smee.io",  # must be stripped
            "Content-Length": "999",  # must be stripped
        },
        "body": {"action": "opened", "issue": {"number": 7}},
    }
    async with httpx.AsyncClient() as client:
        await smee.forward_event(event, "http://backend/webhook", client=client)

    expected_body = json.dumps(
        {"action": "opened", "issue": {"number": 7}}, separators=(",", ":")
    ).encode()
    assert captured["body"] == expected_body

    expected_sig = hmac_mod.new(b"my-wh-secret", expected_body, hashlib.sha256).hexdigest()
    assert captured["headers"]["x-hub-signature-256"] == f"sha256={expected_sig}"
    assert captured["headers"]["x-github-event"] == "issues"


@respx.mock
async def test_forward_event_drops_signature_when_no_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Degenerate case: App credentials haven't landed yet. We still
    forward so the receiver can diagnose via a 401 rather than silently
    dropping events."""

    async def _no_secret() -> str | None:
        return None

    monkeypatch.setattr(smee, "_load_webhook_secret", _no_secret)

    captured: dict = {}

    def handler(request: httpx.Request) -> Response:
        captured["headers"] = dict(request.headers)
        return Response(202)

    respx.post("http://backend/webhook").mock(side_effect=handler)
    event = {"headers": {"X-GitHub-Event": "issues"}, "body": {"a": 1}}
    async with httpx.AsyncClient() as client:
        await smee.forward_event(event, "http://backend/webhook", client=client)
    assert "x-hub-signature-256" not in captured["headers"]


@respx.mock
async def test_forward_event_accepts_raw_string_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _no_secret() -> str | None:
        return None

    monkeypatch.setattr(smee, "_load_webhook_secret", _no_secret)

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
