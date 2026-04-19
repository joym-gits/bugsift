from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from bugsift.db.types import JSONB

SUPPORTED_EMBEDDING_DIMS = (1536, 768)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    github_login: Mapped[str] = mapped_column(String(80), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    api_keys: Mapped[list[UserApiKey]] = relationship(back_populates="user", cascade="all, delete-orphan")
    installations: Mapped[list[Installation]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserApiKey(Base):
    __tablename__ = "user_api_keys"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_user_provider"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # anthropic | openai | google | ollama
    encrypted_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    masked_hint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped[User] = relationship(back_populates="api_keys")


class Installation(Base):
    __tablename__ = "installations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    github_installation_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    installed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User | None] = relationship(back_populates="installations")
    repos: Mapped[list[Repo]] = relationship(back_populates="installation", cascade="all, delete-orphan")


class Repo(Base):
    __tablename__ = "repos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    installation_id: Mapped[int] = mapped_column(
        ForeignKey("installations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    github_repo_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    default_branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")
    primary_language: Mapped[str | None] = mapped_column(String(64), nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    indexing_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")

    # Embedding provider + dimension is fixed per-repo at first index. Changing
    # requires a full re-index. Null until the first index completes.
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_dim: Mapped[int | None] = mapped_column(Integer, nullable=True)

    installation: Mapped[Installation] = relationship(back_populates="repos")
    config: Mapped[RepoConfig | None] = relationship(back_populates="repo", uselist=False, cascade="all, delete-orphan")


class RepoConfig(Base):
    __tablename__ = "repo_configs"

    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="dry-run")
    monthly_budget_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=10)
    tone: Mapped[str] = mapped_column(String(32), nullable=False, default="professional")
    enabled_steps_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    auto_actions_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    label_map_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    reproduce_languages_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    repo: Mapped[Repo] = relationship(back_populates="config")


class TriageCard(Base):
    __tablename__ = "triage_cards"
    # The old ``uq_repo_issue`` constraint is now a partial index in the
    # migration (unique only when ``source='github'``) so multiple
    # feedback-sourced cards per repo are allowed. Feedback cards carry
    # ``issue_number=None`` until the operator approves and a real GitHub
    # issue is opened for them.
    __table_args__ = ()

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True)
    # Where this card came from. ``github`` = webhook/backfill of a real
    # issue. ``feedback`` = widget-submitted user report that has not
    # become a GitHub issue yet.
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="github", index=True)
    issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # For ``source='feedback'`` cards: list of feedback_report ids that
    # collapsed into this one card (slice 3 dedup). Always at least one.
    feedback_report_ids_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Populated on approve: the GitHub issue number the card turned into.
    github_issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    classification: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # ``blocker`` | ``high`` | ``medium`` | ``low`` | ``None``. Computed
    # deterministically from classification + reproduction verdict +
    # regression suspects + number of user reports. See
    # :mod:`bugsift.agent.severity`.
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    duplicates_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reproduction_verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reproduction_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    suspected_files_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Recent pushes that touched any of ``suspected_files_json`` and
    # landed before this card's ``created_at`` — the regression
    # correlator's output.
    regression_suspects_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    draft_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_labels_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    proposed_action: Mapped[str | None] = mapped_column(String(48), nullable=True)
    budget_limited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    final_comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class PushEvent(Base):
    """A GitHub ``push`` we've seen against a repo's default branch.

    Populated from the webhook handler; each row is a single push (which
    may bundle many commits). We flatten the commits into their first
    line + touched paths union so the regression correlator can overlap
    those paths against a card's ``suspected_files_json`` without hauling
    the whole webhook payload around.
    """

    __tablename__ = "push_events"
    __table_args__ = (
        UniqueConstraint("repo_id", "commit_sha", name="uq_push_event_sha"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(
        ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    message_first_line: Mapped[str] = mapped_column(Text, nullable=False, default="")
    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_login: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pushed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    touched_paths_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CodeChunk(Base):
    __tablename__ = "code_chunks"
    __table_args__ = (UniqueConstraint("repo_id", "file_path", "start_line", name="uq_chunk_location"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Exactly one of the three embedding columns is populated per row; the
    # repo's embedding_dim tells callers which to use. The 384 column hosts
    # the built-in ``local`` provider (fastembed / bge-small-en-v1.5).
    embedding_1536: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    embedding_768: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
    embedding_384: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class IssueEmbedding(Base):
    __tablename__ = "issue_embeddings"
    __table_args__ = (UniqueConstraint("repo_id", "issue_number", name="uq_issue_embedding"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True)
    issue_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body_excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    embedding_1536: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    embedding_768: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
    embedding_384: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class LLMUsage(Base):
    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True)
    card_id: Mapped[int | None] = mapped_column(ForeignKey("triage_cards.id", ondelete="SET NULL"), nullable=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False, default=0)
    step_name: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class FeedbackApp(Base):
    """An app the operator embeds the bugsift widget in.

    Each app gets a ``public_key`` (safe to ship in the widget's ``<script>``
    tag) and a default GitHub repo where approved feedback becomes issues.
    The ``allowed_origins`` list narrows which browser origins may POST to
    the ingest endpoint — ``None`` means accept any origin (useful for
    mobile / non-browser callers). ``target_branch`` overrides the repo's
    default branch for analysis + future reproduction runs tied to this
    app; ``None`` means "use whatever the repo's default is".
    """

    __tablename__ = "feedback_apps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    public_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    allowed_origins_json: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    default_repo_id: Mapped[int | None] = mapped_column(
        ForeignKey("repos.id", ondelete="SET NULL"), nullable=True
    )
    target_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RepoAnalysis(Base):
    """Hierarchical LLM analysis of a (repo, branch).

    Produced by :mod:`bugsift.workers.analyze` and displayed on the
    feedback-app detail page. One row per ``(repo_id, branch)`` — if
    multiple feedback apps target the same branch of the same repo
    they share this analysis. Operator corrections (free-form chat
    edits) are stored in ``overrides_json`` and re-applied when the
    worker regenerates.

    Status machine:
    - ``pending`` — job queued, worker hasn't picked it up yet
    - ``running`` — mid-analysis
    - ``ready`` — ``structured_json`` + ``mermaid_src`` populated
    - ``failed`` — ``error_detail`` carries the reason
    """

    __tablename__ = "repo_analyses"
    __table_args__ = (
        UniqueConstraint("repo_id", "branch", name="uq_repo_analysis_branch"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(
        ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    branch: Mapped[str] = mapped_column(String(255), nullable=False)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True
    )
    structured_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    mermaid_src: Mapped[str | None] = mapped_column(Text, nullable=True)
    overrides_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class FeedbackReport(Base):
    """A single bug report submitted through the widget.

    Multiple reports can collapse to one ``TriageCard`` (see slice 3
    dedup); ``card_id`` is filled in once triage has decided what group
    this belongs to. Raw body + captured browser context stay on this
    row so we can always rebuild the card or re-run the pipeline.
    """

    __tablename__ = "feedback_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_id: Mapped[int] = mapped_column(
        ForeignKey("feedback_apps.id", ondelete="CASCADE"), nullable=False, index=True
    )
    card_id: Mapped[int | None] = mapped_column(
        ForeignKey("triage_cards.id", ondelete="SET NULL"), nullable=True, index=True
    )
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    console_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    screenshot_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # sha256 of the reporter id the host app passed in (never plaintext).
    reporter_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Anything else the widget sent — last N clicks, feature flags, etc.
    client_meta_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # sha256 of a normalized body for deterministic dedup of the same user
    # submitting twice in a row.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Embedding of the report body, computed at triage time using the
    # built-in local provider (384-dim / bge-small-en-v1.5). Used to
    # collapse near-duplicate user reports into one card.
    embedding_384: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)
    # Client IP at ingest time — kept short-term for rate limiting and
    # abuse forensics only; no long-term analytics use.
    ingest_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SlackDestination(Base):
    """A Slack Incoming Webhook destination the operator connected.

    Incoming Webhooks are channel-scoped URLs created by the user in
    their workspace (``https://api.slack.com/apps`` → create app →
    Incoming Webhooks → Activate → Add New Webhook to Workspace). No
    OAuth app registration required on our side for v1; interactive
    buttons are deferred until we have a public bugsift URL + Slack App
    signing secret.

    ``events_json`` is a flag set describing which card-lifecycle events
    trigger a message. Empty => notify on all. We default to the high-
    signal subset on create: new card + regression hit, not every skip.
    """

    __tablename__ = "slack_destinations"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_slack_dest_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    webhook_url_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # Human-readable hints so the settings UI can show which channel
    # the webhook belongs to without us having to make another Slack
    # API call. Slack's webhook response includes "channel" on the
    # configuration page; we capture what the user pasted or leave blank.
    channel_hint: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Flag set. Missing keys read as False. See bugsift.slack.notifier
    # for the canonical event names.
    events_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GithubAppCredentials(Base):
    """Singleton (id == 1) — the operator's registered bugsift GitHub App.

    Written by the manifest flow. Secrets are Fernet-encrypted at rest using
    the same key that protects user_api_keys. One App per deployment.
    """

    __tablename__ = "github_app_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    github_app_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_login: Mapped[str] = mapped_column(String(255), nullable=False)
    html_url: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    client_secret_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    webhook_secret_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    private_key_pem_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
