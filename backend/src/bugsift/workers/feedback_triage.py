"""Triage worker for widget-submitted feedback reports.

Mirrors :mod:`bugsift.workers.triage` but takes a ``FeedbackReport`` row
instead of a GitHub webhook payload. Runs the same orchestrator so
classify / dedup / retrieval / reproduction behave identically, and
persists a :class:`TriageCard` with ``source='feedback'``. Slice 3
adds duplicate-report collapsing; this slice is 1:1 (one card per
report).
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from sqlalchemy import select

from bugsift.agent import orchestrator
from bugsift.agent.state import TriageState
from bugsift.agent.steps import ingest_feedback
from bugsift.db.models import (
    FeedbackApp,
    FeedbackReport,
    Installation,
    LLMUsage,
    Repo,
    RepoConfig,
    TriageCard,
    User,
)
from bugsift.db.session import SessionLocal
from bugsift.feedback import dedup as feedback_dedup
from bugsift.llm.factory import get_provider_for_user
from bugsift.llm.local_embed import LocalEmbeddingProvider
from bugsift.retrieval.embedding import EmbeddingUnavailable, get_embedder_for_repo
from bugsift.security import crypto
from bugsift.usage import budget_status_for_repo
from bugsift.workers.triage import DEFAULT_PROVIDER, _config_dict, _reproduce_languages_from_config

logger = logging.getLogger(__name__)


def process_feedback_report(report_id: int) -> None:
    """RQ entrypoint. Sync wrapper around async DB + LLM work."""
    asyncio.run(_process_feedback_report(report_id))


async def _process_feedback_report(report_id: int) -> None:
    async with SessionLocal() as session:
        report = await session.get(FeedbackReport, report_id)
        if report is None:
            logger.warning("feedback triage: report_id=%s not found", report_id)
            return

        # Idempotency: if we already built a card for this report (e.g.
        # the job was retried after a restart), do nothing.
        existing = (
            await session.execute(
                select(TriageCard).where(TriageCard.id == report.card_id)
            )
        ).scalar_one_or_none() if report.card_id else None
        if existing is not None:
            logger.info(
                "feedback triage: report_id=%s already linked to card_id=%s; skipping",
                report_id,
                report.card_id,
            )
            return

        # Collapse near-duplicates before spending any LLM budget. We
        # embed the raw body (not the context appendix) so the same bug
        # reported from different URLs still merges.
        vector: list[float] | None = None
        try:
            vector = await LocalEmbeddingProvider().embed(report.body_text)
        except Exception:
            logger.exception(
                "feedback dedup: local embed failed for report_id=%s; "
                "falling through to full pipeline",
                report_id,
            )
        if vector is not None:
            report.embedding_384 = vector
            await session.flush()
            match = await feedback_dedup.find_mergeable_card(
                session, report=report, vector=vector
            )
            if match is not None:
                await feedback_dedup.attach_report_to_card(
                    session, report=report, card_id=match.merged_into_card_id
                )
                await session.commit()
                logger.info(
                    "feedback merged report_id=%s into card_id=%s sim=%.3f",
                    report_id,
                    match.merged_into_card_id,
                    match.similarity,
                )
                return

        app = await session.get(FeedbackApp, report.app_id)
        if app is None or app.default_repo_id is None:
            logger.warning(
                "feedback triage: report_id=%s app has no default_repo_id; cannot triage",
                report_id,
            )
            return

        repo = await session.get(Repo, app.default_repo_id)
        if repo is None:
            logger.warning(
                "feedback triage: report_id=%s default_repo_id=%s not found",
                report_id,
                app.default_repo_id,
            )
            return

        install = await session.get(Installation, repo.installation_id)
        if install is None or install.user_id is None:
            logger.warning(
                "feedback triage: repo %s has no installation/user; writing flagged card",
                repo.full_name,
            )
            # Even without a user/LLM, persist a pending card so the
            # report is visible in the dashboard.
            state = _bare_state(report, repo)
            card = _write_card(
                session,
                state,
                report=report,
                flag_reason="Installation has no linked user; cannot run triage.",
            )
            await session.flush()
            report.card_id = card.id
            await session.commit()
            return

        config = await session.get(RepoConfig, repo.id)
        state = ingest_feedback.from_feedback_report(
            report=report,
            repo_id=repo.id,
            repo_full_name=repo.full_name,
            repo_primary_language=repo.primary_language,
            repo_config=_config_dict(config),
        )

        provider = None
        try:
            user = await _load_user(session, install.user_id)
            provider = await get_provider_for_user(session, user, DEFAULT_PROVIDER)
        except (KeyError, crypto.DecryptionFailed) as e:
            logger.warning(
                "feedback triage: no usable %s key for user_id=%s: %s",
                DEFAULT_PROVIDER,
                install.user_id,
                e,
            )

        if provider is None:
            card = _write_card(
                session,
                state,
                report=report,
                flag_reason="No LLM key configured for this installation.",
            )
            await session.flush()
            report.card_id = card.id
            await session.commit()
            return

        embed_provider = None
        embedding_dim: int | None = None
        try:
            embed_provider, choice = await get_embedder_for_repo(
                session, repo, install.user_id
            )
            embedding_dim = choice.dim
            if repo.embedding_model is None:
                repo.embedding_model = f"{choice.provider_name}:{choice.model}"
                repo.embedding_dim = choice.dim
                await session.flush()
        except EmbeddingUnavailable as e:
            logger.info("feedback triage: dedup disabled for %s: %s", repo.full_name, e)

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
                "feedback orchestrator failed for report_id=%s", report_id
            )
            state.short_circuit("orchestrator raised; see logs")

        card = _write_card(session, state, report=report)
        await session.flush()
        report.card_id = card.id
        _record_llm_usage(session, state, card_id=card.id)
        await session.commit()


def _bare_state(report: FeedbackReport, repo: Repo) -> TriageState:
    return ingest_feedback.from_feedback_report(
        report=report,
        repo_id=repo.id,
        repo_full_name=repo.full_name,
        repo_primary_language=repo.primary_language,
        repo_config={},
    )


async def _load_user(session, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise KeyError(f"user_id={user_id} not found")
    return user


def _write_card(
    session,
    state: TriageState,
    *,
    report: FeedbackReport,
    flag_reason: str | None = None,
) -> TriageCard:
    card = TriageCard(
        repo_id=state.repo_id,
        source="feedback",
        # NULL until the operator approves and a GitHub issue is opened.
        issue_number=None,
        feedback_report_ids_json=[report.id],
        status="pending",
        classification=state.classification,
        confidence=(
            Decimal(f"{state.confidence:.3f}") if state.confidence is not None else None
        ),
        rationale=state.rationale or flag_reason,
        duplicates_json=[d.__dict__ for d in state.duplicates] or None,
        reproduction_verdict=state.reproduction_verdict,
        reproduction_log=state.reproduction_log,
        suspected_files_json=[f.__dict__ for f in state.suspected_files] or None,
        draft_comment=state.draft_comment,
        proposed_labels_json=state.proposed_labels or None,
        proposed_action=state.proposed_action,
        budget_limited=state.budget_limited,
        raw_payload_json=state.raw_payload,
    )
    session.add(card)
    logger.info(
        "feedback card queued repo=%s report_id=%s classification=%s action=%s",
        state.repo_full_name,
        report.id,
        state.classification,
        state.proposed_action,
    )
    return card


def _record_llm_usage(session, state: TriageState, *, card_id: int) -> None:
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
