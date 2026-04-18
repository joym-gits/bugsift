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
    __table_args__ = (UniqueConstraint("repo_id", "issue_number", name="uq_repo_issue"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True)
    issue_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    classification: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    duplicates_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reproduction_verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reproduction_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    suspected_files_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    draft_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_labels_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    proposed_action: Mapped[str | None] = mapped_column(String(48), nullable=True)
    budget_limited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    final_comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class CodeChunk(Base):
    __tablename__ = "code_chunks"
    __table_args__ = (UniqueConstraint("repo_id", "file_path", "start_line", name="uq_chunk_location"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Exactly one of the two embedding columns is populated per row; the
    # repo's embedding_dim tells callers which to use. A CHECK constraint in
    # the migration enforces the XOR.
    embedding_1536: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    embedding_768: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
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
