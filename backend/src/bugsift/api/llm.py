from __future__ import annotations

import logging
import time
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from bugsift.api.deps import get_current_user, get_session
from bugsift.db.models import User
from bugsift.llm.base import ChatMessage, LLMProviderError
from bugsift.llm.factory import get_provider_for_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/llm", tags=["llm"])

Provider = Literal["anthropic", "openai", "google", "ollama"]


class TestKeyRequest(BaseModel):
    provider: Provider


class TestKeyResponse(BaseModel):
    ok: bool
    provider: Provider
    model: str | None = None
    sample: str | None = None
    latency_ms: int | None = None
    error: str | None = None


@router.post("/test", response_model=TestKeyResponse)
async def test_key(
    body: TestKeyRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TestKeyResponse:
    try:
        provider = await get_provider_for_user(session, user, body.provider)
    except KeyError as e:
        return TestKeyResponse(ok=False, provider=body.provider, error=str(e))

    started = time.perf_counter()
    try:
        response = await provider.complete(
            [ChatMessage(role="user", content="Reply with the single word: ok")],
            max_tokens=16,
            temperature=0.0,
        )
    except LLMProviderError as e:
        logger.warning("llm test failed provider=%s status=%s", body.provider, e.status_code)
        return TestKeyResponse(ok=False, provider=body.provider, error=str(e))
    except Exception as e:  # pragma: no cover - network/timeout surface
        logger.exception("llm test unexpected failure provider=%s", body.provider)
        return TestKeyResponse(ok=False, provider=body.provider, error=f"{type(e).__name__}: {e}")

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return TestKeyResponse(
        ok=True,
        provider=body.provider,
        model=response.model,
        sample=response.content[:200],
        latency_ms=elapsed_ms,
    )
