from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from bugsift import __version__
from bugsift.api.auth import router as auth_router
from bugsift.api.cards import router as cards_router
from bugsift.api.feedback import router as feedback_router
from bugsift.api.github import router as github_router
from bugsift.api.github_settings import router as github_settings_router
from bugsift.api.keys import router as keys_router
from bugsift.api.llm import router as llm_router
from bugsift.api.manifest import router as manifest_router
from bugsift.api.repos import router as repos_router
from bugsift.api.slack import router as slack_router
from bugsift.api.usage import router as usage_router
from bugsift.api.webhooks import router as webhooks_router
from bugsift.api.widget import router as widget_router
from bugsift.config import get_settings
from bugsift.github import smee

logger = logging.getLogger(__name__)

# Without this, gunicorn's uvicorn worker leaves the root logger at WARNING,
# so our `logger.info(...)` calls (webhook dispatch, enqueue traces) silently
# vanish — hiding exactly the diagnostics we need when issues don't appear.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    force=True,
)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Start the in-process smee forwarder if a tunnel URL is already
    provisioned, then hand control to the app. Shutdown stops the task
    cleanly so tests don't leak background coroutines.
    """
    try:
        await smee.start_forwarder_if_url_present()
    except Exception:  # pragma: no cover - startup resilience
        logger.exception("smee forwarder failed to start; webhooks will not flow until fixed")
    try:
        yield
    finally:
        await smee.stop_forwarder()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="bugsift",
        version=__version__,
        docs_url="/docs" if settings.env == "development" else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    # Session is a signed cookie holding `user_id` and OAuth state. Secret must
    # not be empty in production; in dev we fall back to a local default so the
    # stack can boot before the operator fills .env.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret or "dev-only-insecure-replace-me",
        same_site="lax",
        https_only=settings.env == "production",
        session_cookie="bugsift_session",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.public_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # The feedback widget runs on arbitrary third-party origins and never
    # needs cookies, so it gets its own wide-open CORS layer scoped to the
    # ingest path and the widget script. The dashboard CORS above is still
    # the only one that allows credentials.
    @app.middleware("http")
    async def _widget_cors(request, call_next):
        path = request.url.path
        is_widget_path = path.endswith("/ingest/feedback") or path.endswith("/widget.js")
        if is_widget_path and request.method == "OPTIONS":
            # Answer the CORS preflight directly — the router never sees it.
            from fastapi import Response as _Response
            return _Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": request.headers.get("origin", "*"),
                    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type, X-Bugsift-App-Key",
                    "Access-Control-Max-Age": "600",
                },
            )
        response = await call_next(request)
        if is_widget_path:
            response.headers["Access-Control-Allow-Origin"] = request.headers.get("origin", "*")
            response.headers["Vary"] = "Origin"
        return response

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.include_router(auth_router)
    app.include_router(keys_router)
    app.include_router(webhooks_router)
    app.include_router(github_router)
    app.include_router(cards_router)
    app.include_router(repos_router)
    app.include_router(llm_router)
    app.include_router(usage_router)
    app.include_router(manifest_router)
    app.include_router(github_settings_router)
    app.include_router(feedback_router)
    app.include_router(widget_router)
    app.include_router(slack_router)

    return app


app = create_app()
