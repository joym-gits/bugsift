"""Minimal installation-scoped GitHub API client.

Just the methods the triage loop needs in Phase 5: post an issue comment and
apply labels. Token lookup is delegated to :mod:`bugsift.github.app` which
caches installation tokens per §5.
"""

from __future__ import annotations

import httpx

from bugsift.github.app import GITHUB_API_URL, get_installation_token


class GithubClient:
    def __init__(self, installation_id: int) -> None:
        self._installation_id = installation_id

    async def post_issue_comment(self, repo_full_name: str, issue_number: int, body: str) -> dict:
        token = await get_installation_token(self._installation_id)
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
        token = await get_installation_token(self._installation_id)
        url = f"{GITHUB_API_URL}/repos/{repo_full_name}/issues/{issue_number}/labels"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, headers=_headers(token), json={"labels": labels}, timeout=30.0
            )
        response.raise_for_status()

    async def close_issue(self, repo_full_name: str, issue_number: int) -> None:
        token = await get_installation_token(self._installation_id)
        url = f"{GITHUB_API_URL}/repos/{repo_full_name}/issues/{issue_number}"
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                url, headers=_headers(token), json={"state": "closed"}, timeout=30.0
            )
        response.raise_for_status()


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
