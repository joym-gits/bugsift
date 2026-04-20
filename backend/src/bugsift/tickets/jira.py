"""Minimal Jira Cloud REST client.

Only the three endpoints the approve flow needs:

- ``GET /rest/api/3/myself`` — credential smoke test; called on
  destination save.
- ``GET /rest/api/3/project/search`` — enumerate projects the token
  can see so the UI can populate a project picker.
- ``POST /rest/api/2/issue`` — create a new issue with a plain-text
  description. v2 accepts plain strings / wiki markup; v3 requires
  ADF and adds no value for our use case, so we stick with v2 until
  Atlassian actually retires it on Cloud.

Auth is HTTP Basic with ``email:api_token`` — the standard Jira Cloud
REST pattern. Tokens are created by the user at
``https://id.atlassian.com/manage-profile/security/api-tokens``.
Self-hosted Jira Server works too; just pass the base URL.
"""

from __future__ import annotations

import logging
from base64 import b64encode
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JiraProject:
    id: str
    key: str
    name: str


@dataclass(frozen=True)
class JiraCreatedIssue:
    id: str
    key: str
    url: str


class JiraAuthError(RuntimeError):
    """Raised when Jira rejects the credentials."""


class JiraApiError(RuntimeError):
    """Raised for any other non-2xx response."""


class JiraClient:
    def __init__(
        self,
        *,
        site_url: str,
        user_email: str,
        api_token: str,
    ) -> None:
        self._site = site_url.rstrip("/")
        self._email = user_email
        self._token = api_token

    def _headers(self) -> dict[str, str]:
        creds = f"{self._email}:{self._token}".encode("utf-8")
        return {
            "Authorization": f"Basic {b64encode(creds).decode('ascii')}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def validate(self) -> dict[str, Any]:
        """Hit ``/myself`` — fast, cheap, returns the account the
        token belongs to. Raises :class:`JiraAuthError` on 401/403."""
        url = f"{self._site}/rest/api/3/myself"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers(), timeout=10.0)
        if response.status_code in (401, 403):
            raise JiraAuthError(
                f"Jira rejected credentials ({response.status_code}); "
                "check the site URL, email, and API token."
            )
        if response.status_code != 200:
            # Response body can contain internal error hints we don't want
            # surfacing to the caller; log it server-side and raise a clean
            # error so the handler doesn't leak it via HTTPException.detail.
            logger.warning(
                "jira /myself returned %s: %s",
                response.status_code,
                response.text[:200],
            )
            raise JiraApiError(
                f"Jira /myself returned HTTP {response.status_code}"
            )
        return response.json()

    async def list_projects(self, *, limit: int = 50) -> list[JiraProject]:
        """Enumerate projects visible to the token. One page only —
        most Jira orgs have well under 50 projects that matter, and
        the UI only needs a pickable dropdown."""
        url = f"{self._site}/rest/api/3/project/search"
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=self._headers(),
                params={"maxResults": limit, "orderBy": "name"},
                timeout=15.0,
            )
        if response.status_code in (401, 403):
            raise JiraAuthError(
                f"Jira rejected credentials on /project/search ({response.status_code})"
            )
        if response.status_code != 200:
            logger.warning(
                "jira list_projects returned %s: %s",
                response.status_code,
                response.text[:200],
            )
            return []
        try:
            payload = response.json()
        except ValueError:
            return []
        values = payload.get("values") if isinstance(payload, dict) else None
        if not isinstance(values, list):
            return []
        out: list[JiraProject] = []
        for item in values:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            if not key:
                continue
            out.append(
                JiraProject(
                    id=str(item.get("id", "")),
                    key=key,
                    name=str(item.get("name") or key),
                )
            )
        return out

    async def create_issue(
        self,
        *,
        project_key: str,
        issue_type: str,
        summary: str,
        description: str,
        labels: list[str] | None = None,
    ) -> JiraCreatedIssue:
        """Create an issue. Returns the ``id`` / ``key`` / human URL
        (``{site}/browse/{key}``) — Jira's API returns ``self`` pointing
        at the REST endpoint, not the UI page the user wants to click."""
        url = f"{self._site}/rest/api/2/issue"
        payload: dict[str, Any] = {
            "fields": {
                "project": {"key": project_key},
                "issuetype": {"name": issue_type},
                "summary": summary[:255],  # Jira's summary cap
                "description": description,
            }
        }
        cleaned_labels = [lbl.strip() for lbl in (labels or []) if lbl and lbl.strip()]
        if cleaned_labels:
            # Jira labels can't contain spaces; silently replace so a
            # ``needs info`` GitHub label doesn't make the whole create
            # request fail.
            payload["fields"]["labels"] = [
                l.replace(" ", "-") for l in cleaned_labels
            ]

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, headers=self._headers(), json=payload, timeout=20.0
            )
        if response.status_code in (401, 403):
            raise JiraAuthError(
                f"Jira rejected credentials on issue create ({response.status_code})"
            )
        if response.status_code >= 400:
            logger.warning(
                "jira create-issue returned %s: %s",
                response.status_code,
                response.text[:400],
            )
            raise JiraApiError(
                f"Jira create-issue failed (HTTP {response.status_code})"
            )
        try:
            body = response.json()
        except ValueError as e:
            raise JiraApiError("Jira create-issue returned non-JSON body") from e
        key = str(body.get("key") or "")
        issue_id = str(body.get("id") or "")
        if not key:
            logger.warning("jira create-issue missing 'key' in response body=%s", body)
            raise JiraApiError("Jira create-issue missing 'key' in response")
        return JiraCreatedIssue(
            id=issue_id,
            key=key,
            url=f"{self._site}/browse/{key}",
        )
