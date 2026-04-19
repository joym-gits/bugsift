"""Tests for the Slack Incoming Webhook integration."""

from __future__ import annotations

import pytest
import pytest_asyncio
import respx
from fakeredis.aioredis import FakeRedis
from httpx import Response

from bugsift.api.deps import get_current_user, get_optional_user
from bugsift.db.models import (
    Installation,
    Repo,
    SlackDestination,
    TriageCard,
    User,
)
from bugsift.github import rate_limit
from bugsift.security import crypto
from bugsift.slack import notifier
from bugsift.workers.slack import _notify_card_event


VALID_WEBHOOK = "https://hooks.slack.com/services/T000/B000/XXXXXXXXXXXX"


@pytest_asyncio.fixture(autouse=True)
async def _fake_redis(monkeypatch: pytest.MonkeyPatch):
    client = FakeRedis(decode_responses=True)
    monkeypatch.setattr(rate_limit, "_redis", client)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def logged_in(client, session):
    user = User(github_id=1, github_login="m", email=None)
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


def test_create_rejects_bad_url(client, logged_in: User):
    r = client.post(
        "/slack/destinations",
        json={
            "name": "bad",
            "webhook_url": "https://not-slack.example.com/hook",
        },
    )
    assert r.status_code == 400


def test_create_list_patch_delete(client, logged_in: User):
    r = client.post(
        "/slack/destinations",
        json={
            "name": "prod-alerts",
            "webhook_url": VALID_WEBHOOK,
            "channel_hint": "#triage",
        },
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["channel_hint"] == "#triage"
    assert created["webhook_hint"].startswith("…/") or created[
        "webhook_hint"
    ] == "XXXXXX"
    # Default events: new_card + regression, not approved.
    assert created["events"]["new_card"] is True
    assert created["events"]["regression"] is True
    assert created["events"]["approved"] is False

    # Update toggles approved on.
    r_patch = client.patch(
        f"/slack/destinations/{created['id']}",
        json={
            "events": {"new_card": True, "approved": True, "regression": True}
        },
    )
    assert r_patch.status_code == 200
    assert r_patch.json()["events"]["approved"] is True

    # List sees the updated destination.
    rlist = client.get("/slack/destinations").json()
    assert len(rlist) == 1 and rlist[0]["events"]["approved"] is True

    # Delete.
    r_del = client.delete(f"/slack/destinations/{created['id']}")
    assert r_del.status_code == 204
    assert client.get("/slack/destinations").json() == []


def test_test_endpoint_posts_to_webhook(client, logged_in: User):
    r = client.post(
        "/slack/destinations",
        json={"name": "t", "webhook_url": VALID_WEBHOOK},
    )
    dest_id = r.json()["id"]

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(VALID_WEBHOOK).mock(return_value=Response(200, text="ok"))
        r_test = client.post(f"/slack/destinations/{dest_id}/test")
        assert r_test.status_code == 200
        body = r_test.json()
        assert body["ok"] is True
        assert body["status_code"] == 200
        assert route.called
        # The posted JSON carried Block Kit blocks + a fallback text.
        request = route.calls[0].request
        import json as _json

        body_sent = _json.loads(request.content.decode())
        assert "bugsift" in body_sent["text"].lower()
        assert isinstance(body_sent["blocks"], list)


def test_test_endpoint_surfaces_non_200(client, logged_in: User):
    r = client.post(
        "/slack/destinations",
        json={"name": "t", "webhook_url": VALID_WEBHOOK},
    )
    dest_id = r.json()["id"]

    with respx.mock() as mock:
        mock.post(VALID_WEBHOOK).mock(
            return_value=Response(400, text="invalid_payload")
        )
        r_test = client.post(f"/slack/destinations/{dest_id}/test")
        assert r_test.status_code == 200
        body = r_test.json()
        assert body["ok"] is False
        assert body["status_code"] == 400
        assert "invalid_payload" in (body["detail"] or "")


def test_should_notify_honours_flags(session):
    dest = SlackDestination(
        user_id=1,
        name="n",
        webhook_url_encrypted=b"x",
        events_json={"new_card": True, "approved": False},
    )
    assert notifier.should_notify(dest, "new_card") is True
    assert notifier.should_notify(dest, "approved") is False
    # Unknown event never notifies.
    assert notifier.should_notify(dest, "unknown") is False


def test_should_notify_empty_flags_uses_defaults(session):
    dest = SlackDestination(
        user_id=1,
        name="n",
        webhook_url_encrypted=b"x",
        events_json={},
    )
    # Defaults fire new_card + regression but not approved.
    assert notifier.should_notify(dest, "new_card") is True
    assert notifier.should_notify(dest, "regression") is True
    assert notifier.should_notify(dest, "approved") is False


def test_build_card_blocks_contains_expected_sections():
    card = TriageCard(
        id=7,
        repo_id=1,
        source="github",
        issue_number=42,
        status="pending",
        classification="bug",
        confidence=0.91,
        rationale="A real defect",
        suspected_files_json=[
            {"file_path": "app/save.py", "line_range": "1-10", "rationale": "trace"}
        ],
        regression_suspects_json=[
            {
                "commit_sha": "a" * 40,
                "short_sha": "a" * 7,
                "message_first_line": "fix: save",
                "pr_number": 77,
                "author_login": "alice",
            }
        ],
    )
    blocks = notifier.build_card_blocks(
        card=card,
        event=notifier.EVENT_NEW_CARD,
        card_url="http://localhost:8080/dashboard",
        repo_full_name="acme/web",
    )
    texts = [
        str(b.get("text", {}).get("text", "")) if isinstance(b.get("text"), dict) else ""
        for b in blocks
    ]
    assert any("acme/web #42" in t for t in texts)
    assert any("app/save.py" in t for t in texts)
    assert any("PR #77" in t for t in texts)
    # Action block always present with the deep link.
    actions = [b for b in blocks if b["type"] == "actions"]
    assert actions and actions[0]["elements"][0]["url"] == "http://localhost:8080/dashboard"


@pytest.mark.asyncio
async def test_worker_dispatches_to_destinations(session, monkeypatch):
    """End-to-end: worker fan-out picks the right destinations, gates
    by event flags, and calls the notifier once per matching dest."""
    user = User(github_id=9, github_login="x", email=None)
    session.add(user)
    await session.flush()
    install = Installation(github_installation_id=1, user_id=user.id)
    session.add(install)
    await session.flush()
    repo = Repo(
        installation_id=install.id,
        github_repo_id=1,
        full_name="acme/web",
        default_branch="main",
        indexing_status="ready",
    )
    session.add(repo)
    await session.flush()
    card = TriageCard(
        repo_id=repo.id,
        source="github",
        issue_number=1,
        status="pending",
        classification="bug",
    )
    session.add(card)
    await session.flush()

    session.add_all([
        SlackDestination(
            user_id=user.id,
            name="opt-in",
            webhook_url_encrypted=crypto.encrypt(VALID_WEBHOOK),
            events_json={"new_card": True},
        ),
        SlackDestination(
            user_id=user.id,
            name="opt-out",
            webhook_url_encrypted=crypto.encrypt(VALID_WEBHOOK),
            events_json={"new_card": False},
        ),
    ])
    await session.commit()
    await session.refresh(card)

    # Point worker's SessionLocal at the test session so it sees our rows.
    class _Ctx:
        def __init__(self, s):
            self._s = s
        async def __aenter__(self):
            return self._s
        async def __aexit__(self, *_exc):
            return False

    from bugsift.workers import slack as slack_worker

    monkeypatch.setattr(slack_worker, "SessionLocal", lambda: _Ctx(session))

    calls: list[tuple[int, str]] = []

    async def _fake_post(destination, *, card, event, card_url, repo_full_name, lead_report_text=None):
        calls.append((destination.id, event))
        return notifier.SlackDeliveryResult(ok=True, status_code=200, detail=None)

    monkeypatch.setattr(slack_worker.notifier, "post_card_event", _fake_post)

    await _notify_card_event(card.id, "new_card")
    # Only the opted-in destination fired.
    assert len(calls) == 1
    assert calls[0][1] == "new_card"
