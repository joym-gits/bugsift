"""Triage worker.

Upgraded in Phase 5 to run the real orchestrator (classify + comment). If no
LLM key is stored for the repo's owning user we still write a pending card so
the maintainer sees the issue in the dashboard, just flagged for manual review.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from bugsift.agent import orchestrator
from bugsift.agent.state import TriageState
from bugsift.agent.steps import ingest
from bugsift.db.models import Installation, LLMUsage, Repo, RepoConfig, TriageCard, User
from bugsift.db.session import SessionLocal
from bugsift.llm.factory import get_provider_for_user
from bugsift.retrieval.embedding import EmbeddingUnavailable, get_embedder_for_repo
from bugsift.security import crypto
from bugsift.usage import budget_status_for_repo

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "anthropic"


def process_issue_opened(payload: dict[str, Any]) -> None:
    """RQ entrypoint. Sync wrapper around async DB + LLM work."""
    asyncio.run(_process_issue_opened(payload))


async def _process_issue_opened(payload: dict[str, Any]) -> None:
    issue = payload.get("issue") or {}
    repo_payload = payload.get("repository") or {}
    github_repo_id = repo_payload.get("id")
    issue_number = issue.get("number")
    if not github_repo_id or not issue_number:
        logger.warning("issues.opened payload missing repo or issue id; skipping")
        return

    async with SessionLocal() as session:
        repo = (
            await session.execute(select(Repo).where(Repo.github_repo_id == github_repo_id))
        ).scalar_one_or_none()
        if repo is None:
            logger.warning(
                "issues.opened for unknown repo github_repo_id=%s; skipping", github_repo_id
            )
            return

        install = await session.get(Installation, repo.installation_id)
        if install is None:
            logger.warning("repo %s has no installation; skipping", repo.full_name)
            return

        existing = (
            await session.execute(
                select(TriageCard).where(
                    TriageCard.repo_id == repo.id, TriageCard.issue_number == issue_number
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            logger.info(
                "triage card already exists repo_id=%s issue_number=%s; skipping",
                repo.id,
                issue_number,
            )
            return

        config = await session.get(RepoConfig, repo.id)
        state = ingest.from_webhook_payload(
            payload=payload,
            repo_id=repo.id,
            repo_full_name=repo.full_name,
            repo_primary_language=repo.primary_language,
            repo_config=_config_dict(config),
        )

        # Pipeline needs a user and a provider. If the install isn't linked to
        # a user yet (user hasn't hit the setup callback), or the user hasn't
        # added an LLM key, we persist a flagged pending card and return.
        provider = None
        if install.user_id is not None:
            try:
                user = await _load_user(session, install.user_id)
                provider = await get_provider_for_user(session, user, DEFAULT_PROVIDER)
            except (KeyError, crypto.DecryptionFailed) as e:
                logger.warning(
                    "no usable %s key for user_id=%s: %s",
                    DEFAULT_PROVIDER,
                    install.user_id,
                    e,
                )

        if provider is None:
            _write_card(
                session,
                state,
                flag_reason="No LLM key configured for this installation.",
            )
            await session.commit()
            return

        # Dedup needs an embedding-capable provider. Degrade gracefully if
        # none — classify + comment still run.
        embed_provider = None
        embedding_dim: int | None = None
        try:
            embed_provider, choice = await get_embedder_for_repo(session, repo, install.user_id)
            embedding_dim = choice.dim
            if repo.embedding_model is None:
                repo.embedding_model = f"{choice.provider_name}:{choice.model}"
                repo.embedding_dim = choice.dim
                await session.flush()
        except EmbeddingUnavailable as e:
            logger.info("dedup disabled for %s: %s", repo.full_name, e)

        reproduce_languages = _reproduce_languages_from_config(config)
        state.monthly_budget_usd = float(config.monthly_budget_usd) if config else 10.0
        budget = await budget_status_for_repo(
            session, repo.id, state.monthly_budget_usd
        )

        try:
            state = await orchestrator.run(
                state,
                provider,
                session=session,
                embed_provider=embed_provider,
                embedding_dim=embedding_dim,
                reproduce_languages=reproduce_languages,
                budget_ok=not budget.is_exhausted,
            )
        except Exception:
            logger.exception(
                "orchestrator failed for %s#%s", state.repo_full_name, state.issue_number
            )
            state.short_circuit("orchestrator raised; see logs")

        card = _write_card(session, state)
        await session.flush()  # populate card.id so LLMUsage can reference it
        _record_llm_usage(session, state, card_id=card.id)
        await session.commit()

        _fire_slack_events(card, state)


def _fire_slack_events(card, state) -> None:
    """Enqueue slack notifications per card event. Safe to call on every
    triage run — the worker fans out to destinations and applies per-
    destination event filters."""
    from bugsift.workers import enqueue as enqueue_jobs

    try:
        enqueue_jobs.enqueue_slack_notification(card.id, "new_card")
        if state.regression_suspects:
            enqueue_jobs.enqueue_slack_notification(card.id, "regression")
    except Exception:
        logger.exception("slack: enqueue failed for card_id=%s; continuing", card.id)


def _reproduce_languages_from_config(config: RepoConfig | None) -> set[str] | None:
    """RepoConfig stores reproduce_languages as JSON. Accept either a list
    (``["python", "node"]``) or a dict with a ``languages`` key."""
    if config is None or not config.reproduce_languages_json:
        return None
    raw = config.reproduce_languages_json
    if isinstance(raw, dict):
        raw = raw.get("languages") or []
    if not isinstance(raw, list):
        return None
    return {str(x).strip().lower() for x in raw if str(x).strip()}


async def _load_user(session, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise KeyError(f"user_id={user_id} not found")
    return user


def _config_dict(config: RepoConfig | None) -> dict[str, Any]:
    if config is None:
        return {}
    return {
        "mode": config.mode,
        "tone": config.tone,
        "enabled_steps": config.enabled_steps_json,
        "auto_actions": config.auto_actions_json,
        "label_map": config.label_map_json,
        "reproduce_languages": config.reproduce_languages_json,
    }


def _write_card(
    session, state: TriageState, *, flag_reason: str | None = None
) -> TriageCard:
    card = TriageCard(
        repo_id=state.repo_id,
        issue_number=state.issue_number,
        status="pending",
        classification=state.classification,
        severity=state.severity,
        confidence=Decimal(f"{state.confidence:.3f}") if state.confidence is not None else None,
        rationale=state.rationale or flag_reason,
        duplicates_json=[d.__dict__ for d in state.duplicates] or None,
        reproduction_verdict=state.reproduction_verdict,
        reproduction_log=state.reproduction_log,
        suspected_files_json=[f.__dict__ for f in state.suspected_files] or None,
        suggested_assignees_json=list(state.suggested_assignees) or None,
        regression_suspects_json=[s.__dict__ for s in state.regression_suspects] or None,
        draft_comment=state.draft_comment,
        proposed_labels_json=state.proposed_labels or None,
        proposed_action=state.proposed_action,
        budget_limited=state.budget_limited,
        raw_payload_json=state.raw_payload,
    )
    session.add(card)
    logger.info(
        "triage card queued repo=%s issue=%s classification=%s action=%s",
        state.repo_full_name,
        state.issue_number,
        state.classification,
        state.proposed_action,
    )
    return card


def _record_llm_usage(session, state: TriageState, *, card_id: int) -> None:
    """Write one :class:`LLMUsage` row per LLM call this run produced."""
    for call in state.llm_calls:
        session.add(
            LLMUsage(
                repo_id=state.repo_id,
                card_id=card_id,
                provider=DEFAULT_PROVIDER,
                model=call.model,
                prompt_tokens=call.prompt_tokens,
                completion_tokens=call.completion_tokens,
                cost_usd=Decimal(f"{call.cost_usd:.6f}"),
                step_name=call.step,
            )
        )
