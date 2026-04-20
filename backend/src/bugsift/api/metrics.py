"""Admin metrics dashboard — throughput, cost, outcome mix.

Single endpoint that rolls up everything the operator needs to tell
execs what bugsift is doing. Read-only; admin-only. Scope is global
across the deployment (all users, all repos) because the audience is
the admin running the instance.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Text, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_session
from bugsift.auth.roles import Role, require_role
from bugsift.db.models import LLMUsage, TriageCard, User

router = APIRouter(prefix="/metrics", tags=["metrics"])


class TimeSeriesPoint(BaseModel):
    date: str
    value: float


class CountByKey(BaseModel):
    key: str
    value: float


class OutcomeMix(BaseModel):
    pending: int
    posted: int
    skipped: int


class MetricsResponse(BaseModel):
    window_days: int
    cards_created: int
    cards_by_day: list[TimeSeriesPoint]
    outcome_mix: OutcomeMix
    approval_rate: float  # posted / (posted + skipped), or 0 if none decided
    cost_by_day_usd: list[TimeSeriesPoint]
    cost_by_provider_usd: list[CountByKey]
    cost_by_model_usd: list[CountByKey]
    cost_by_step_usd: list[CountByKey]
    total_cost_usd: float
    classification_mix: list[CountByKey]
    severity_mix: list[CountByKey]
    pii_scrub_rate: float  # share of cards in window where PII was scrubbed
    # SLA compliance — of cards in window that had an SLA set, what
    # share were decided (posted or skipped) without a breach alert.
    # Null when no card in the window carried an SLA.
    sla_compliance_rate: float | None
    sla_cards_total: int


@router.get("", response_model=MetricsResponse)
async def metrics(
    days: int = 30,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_role(Role.admin)),
) -> MetricsResponse:
    days = max(1, min(days, 365))
    since = datetime.now(timezone.utc) - timedelta(days=days)

    cards_by_day = await _cards_by_day(session, since, days)
    outcomes = await _outcome_mix(session, since)
    approval_rate = _approval_rate(outcomes)
    cost_by_day = await _cost_by_day(session, since, days)
    cost_provider = await _cost_by_key(session, since, LLMUsage.provider)
    cost_model = await _cost_by_key(session, since, LLMUsage.model)
    cost_step = await _cost_by_key(session, since, LLMUsage.step_name)
    classification_mix = await _card_key_mix(session, since, TriageCard.classification)
    severity_mix = await _card_key_mix(session, since, TriageCard.severity)
    total_cost = sum(p.value for p in cost_by_day)
    cards_created = sum(int(p.value) for p in cards_by_day)
    pii_rate = await _pii_scrub_rate(session, since)
    sla_rate, sla_total = await _sla_compliance(session, since)

    return MetricsResponse(
        window_days=days,
        cards_created=cards_created,
        cards_by_day=cards_by_day,
        outcome_mix=outcomes,
        approval_rate=approval_rate,
        cost_by_day_usd=cost_by_day,
        cost_by_provider_usd=cost_provider,
        cost_by_model_usd=cost_model,
        cost_by_step_usd=cost_step,
        total_cost_usd=total_cost,
        classification_mix=classification_mix,
        severity_mix=severity_mix,
        pii_scrub_rate=pii_rate,
        sla_compliance_rate=sla_rate,
        sla_cards_total=sla_total,
    )


async def _cards_by_day(
    session: AsyncSession, since: datetime, days: int
) -> list[TimeSeriesPoint]:
    stmt = (
        select(
            func.date_trunc("day", TriageCard.created_at).label("day"),
            func.count().label("n"),
        )
        .where(TriageCard.created_at >= since)
        .group_by("day")
        .order_by("day")
    )
    rows = (await session.execute(stmt)).all()
    return _fill_daily_series(rows, since, days)


async def _cost_by_day(
    session: AsyncSession, since: datetime, days: int
) -> list[TimeSeriesPoint]:
    stmt = (
        select(
            func.date_trunc("day", LLMUsage.created_at).label("day"),
            func.coalesce(func.sum(LLMUsage.cost_usd), 0).label("cost"),
        )
        .where(LLMUsage.created_at >= since)
        .group_by("day")
        .order_by("day")
    )
    rows = (await session.execute(stmt)).all()
    return _fill_daily_series(rows, since, days)


def _fill_daily_series(
    rows: list, since: datetime, days: int
) -> list[TimeSeriesPoint]:
    # Ensure every day in the window shows up, even empty ones — the
    # chart looks weird without zeros in the gaps.
    by_day: dict[str, float] = {}
    for day, value in rows:
        by_day[day.date().isoformat()] = float(value or 0)
    out: list[TimeSeriesPoint] = []
    cursor = since.date()
    end = (datetime.now(timezone.utc)).date()
    while cursor <= end:
        iso = cursor.isoformat()
        out.append(TimeSeriesPoint(date=iso, value=by_day.get(iso, 0.0)))
        cursor += timedelta(days=1)
    return out


async def _outcome_mix(session: AsyncSession, since: datetime) -> OutcomeMix:
    stmt = (
        select(TriageCard.status, func.count())
        .where(TriageCard.created_at >= since)
        .group_by(TriageCard.status)
    )
    rows = (await session.execute(stmt)).all()
    counts = {status: int(n) for status, n in rows}
    return OutcomeMix(
        pending=counts.get("pending", 0),
        posted=counts.get("posted", 0),
        skipped=counts.get("skipped", 0),
    )


def _approval_rate(mix: OutcomeMix) -> float:
    decided = mix.posted + mix.skipped
    if decided == 0:
        return 0.0
    return mix.posted / decided


async def _cost_by_key(
    session: AsyncSession, since: datetime, column
) -> list[CountByKey]:
    stmt = (
        select(column, func.coalesce(func.sum(LLMUsage.cost_usd), 0))
        .where(LLMUsage.created_at >= since)
        .group_by(column)
        .order_by(func.sum(LLMUsage.cost_usd).desc())
    )
    rows = (await session.execute(stmt)).all()
    return [CountByKey(key=str(k or "unknown"), value=float(v or 0)) for k, v in rows]


async def _card_key_mix(
    session: AsyncSession, since: datetime, column
) -> list[CountByKey]:
    stmt = (
        select(column, func.count())
        .where(TriageCard.created_at >= since)
        .group_by(column)
        .order_by(func.count().desc())
    )
    rows = (await session.execute(stmt)).all()
    return [CountByKey(key=str(k or "unclassified"), value=float(n)) for k, n in rows]


async def _sla_compliance(
    session: AsyncSession, since: datetime
) -> tuple[float | None, int]:
    """Share of SLA-bearing cards in the window that weren't breached.

    Denominator: cards with a non-null ``sla_minutes`` created in the
    window. Numerator: that same set minus rows with a breach alert.
    Pending cards without a breach (yet) count as compliant — a
    breach-then-resolved card stays marked breached.
    """
    total = (
        await session.execute(
            select(func.count())
            .select_from(TriageCard)
            .where(TriageCard.created_at >= since, TriageCard.sla_minutes.is_not(None))
        )
    ).scalar_one()
    if not total:
        return None, 0
    breached = (
        await session.execute(
            select(func.count())
            .select_from(TriageCard)
            .where(
                TriageCard.created_at >= since,
                TriageCard.sla_minutes.is_not(None),
                TriageCard.sla_breach_alerted_at.is_not(None),
            )
        )
    ).scalar_one()
    compliant = int(total) - int(breached)
    return float(compliant) / float(total), int(total)


async def _pii_scrub_rate(session: AsyncSession, since: datetime) -> float:
    total = (
        await session.execute(
            select(func.count()).select_from(TriageCard).where(TriageCard.created_at >= since)
        )
    ).scalar_one()
    if not total:
        return 0.0
    # A non-null, non-empty redaction dict means something was scrubbed.
    # Postgres-specific ``jsonb_typeof`` would be tighter; the
    # json_typeof check stays portable.
    scrubbed = (
        await session.execute(
            select(func.count())
            .select_from(TriageCard)
            .where(
                TriageCard.created_at >= since,
                TriageCard.pii_redacted_json.is_not(None),
                # Exclude empty ``{}`` — only real hits count as scrubbed.
                cast(TriageCard.pii_redacted_json, Text) != "{}",
            )
        )
    ).scalar_one()
    return float(scrubbed) / float(total)
