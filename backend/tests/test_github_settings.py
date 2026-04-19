"""Authenticated GitHub-settings endpoints."""

from __future__ import annotations

import pytest
import pytest_asyncio

from bugsift.api.deps import get_current_user, get_optional_user
from bugsift.db.models import GithubAppCredentials, Installation, Repo, User
from bugsift.security import crypto


@pytest_asyncio.fixture
async def logged_in(client, session):
    user = User(github_id=1, github_login="joym-gits", email=None)
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


@pytest_asyncio.fixture
async def installed_app(session, logged_in: User) -> GithubAppCredentials:
    row = GithubAppCredentials(
        id=1,
        github_app_id=424242,
        slug="bugsift-test",
        name="bugsift-test",
        owner_login="joym-gits",
        html_url="https://github.com/apps/bugsift-test",
        client_id="Iv23liTESTCLIENTID",
        client_secret_encrypted=crypto.encrypt("super-secret-client-7890"),
        webhook_secret_encrypted=crypto.encrypt("whsec-longwebhooksecretXYZ"),
        private_key_pem_encrypted=crypto.encrypt("-----BEGIN RSA PRIVATE KEY-----\nabc123\n"),
    )
    session.add(row)
    # one installation + two repos owned by this user so the counts surface
    install = Installation(github_installation_id=99999, user_id=logged_in.id)
    session.add(install)
    await session.flush()
    session.add(
        Repo(
            installation_id=install.id,
            github_repo_id=1,
            full_name="joym-gits/a",
            default_branch="main",
            indexing_status="pending",
        )
    )
    session.add(
        Repo(
            installation_id=install.id,
            github_repo_id=2,
            full_name="joym-gits/b",
            default_branch="main",
            indexing_status="pending",
        )
    )
    await session.commit()
    yield row
    from bugsift.github import config as app_cfg

    app_cfg.clear_cache()


def test_app_details_requires_auth(client) -> None:
    assert client.get("/github/app").status_code == 401


def test_app_details_unconfigured_when_no_row(client, logged_in) -> None:
    body = client.get("/github/app").json()
    assert body["configured"] is False
    assert body["github_app_id"] is None
    assert body["client_id"] is None


def test_app_details_masks_secrets(client, logged_in, installed_app) -> None:
    body = client.get("/github/app").json()
    assert body["configured"] is True
    assert body["github_app_id"] == 424242
    assert body["name"] == "bugsift-test"
    # Client id is not a secret, but even if it were we wouldn't be dumping
    # the plaintext webhook secret / client secret — masks only.
    assert body["client_id"] == "Iv23liTESTCLIENTID"
    assert "super-secret-client-7890" not in str(body)
    assert "whsec-long" not in str(body)
    # masked_hint format: prefix + bullets + suffix
    assert "•" in body["client_secret_masked"]
    assert body["client_secret_masked"].endswith("7890")
    assert body["webhook_secret_masked"].endswith("tXYZ")
    # PEM fingerprint is 16 hex chars, not the key itself
    assert body["private_key_fingerprint"] is not None
    assert len(body["private_key_fingerprint"]) == 16
    assert "BEGIN" not in body["private_key_fingerprint"]
    # Install / repo counts scoped to this user
    assert body["installations_count"] == 1
    assert body["repos_count"] == 2


def test_installations_requires_auth(client) -> None:
    assert client.get("/github/installations").status_code == 401


def test_installations_lists_current_users_installs(client, logged_in, installed_app) -> None:
    body = client.get("/github/installations").json()
    assert len(body) == 1
    row = body[0]
    assert row["github_installation_id"] == 99999
    assert row["repo_count"] == 2
    assert row["suspended_at"] is None


@pytest.mark.asyncio
async def test_installations_excludes_other_users(client, logged_in, session) -> None:
    # Add an installation for a different user; must not appear.
    stranger = User(github_id=999, github_login="stranger", email=None)
    session.add(stranger)
    await session.flush()
    session.add(Installation(github_installation_id=88888, user_id=stranger.id))
    await session.commit()

    body = client.get("/github/installations").json()
    ids = {row["github_installation_id"] for row in body}
    assert 88888 not in ids
