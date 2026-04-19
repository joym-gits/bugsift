"""Minimal installation-scoped GitHub API client.

Just the methods the triage loop needs in Phase 5: post an issue comment and
apply labels. Token lookup is delegated to :mod:`bugsift.github.app` which
caches installation tokens per §5.
"""

from __future__ import annotations

import httpx

from bugsift.github.app import GITHUB_API_URL, get_installation_token


class GithubClient:
    def __init__(
        self,
        installation_id: int,
        *,
        app_id: str | None = None,
        private_key_pem: str | None = None,
    ) -> None:
        """Optional ``app_id`` + ``private_key_pem`` let the caller inject
        DB-stored App credentials (the onboarding flow persists these there);
        when omitted, the token mint falls back to env-based ``Settings``.
        """
        self._installation_id = installation_id
        self._app_id = app_id
        self._private_key_pem = private_key_pem

    async def _token(self) -> str:
        return await get_installation_token(
            self._installation_id,
            app_id=self._app_id,
            private_key_pem=self._private_key_pem,
        )

    async def post_issue_comment(self, repo_full_name: str, issue_number: int, body: str) -> dict:
        token = await self._token()
        url = f"{GITHUB_API_URL}/repos/{repo_full_name}/issues/{issue_number}/comments"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=_headers(token),
                json={"body": body},
                timeout=30.0,
            )
        response.raise_for_status()
        return response.json()

    async def add_labels(self, repo_full_name: str, issue_number: int, labels: list[str]) -> None:
        if not labels:
            return
        token = await self._token()
        url = f"{GITHUB_API_URL}/repos/{repo_full_name}/issues/{issue_number}/labels"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, headers=_headers(token), json={"labels": labels}, timeout=30.0
            )
        response.raise_for_status()

    async def close_issue(self, repo_full_name: str, issue_number: int) -> None:
        token = await self._token()
        url = f"{GITHUB_API_URL}/repos/{repo_full_name}/issues/{issue_number}"
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                url, headers=_headers(token), json={"state": "closed"}, timeout=30.0
            )
        response.raise_for_status()

    async def create_issue(
        self,
        repo_full_name: str,
        *,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> dict:
        """Open a new issue in ``repo_full_name``. Returns GitHub's response
        JSON so the caller can pull the new ``number`` and ``html_url``.

        Used by the feedback-approve flow: widget-sourced reports that
        the maintainer confirmed become real GitHub issues here, not
        comments on an existing one.
        """
        token = await self._token()
        url = f"{GITHUB_API_URL}/repos/{repo_full_name}/issues"
        payload: dict = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, headers=_headers(token), json=payload, timeout=30.0
            )
        response.raise_for_status()
        return response.json()


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
