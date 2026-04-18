from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from bugsift import __version__
from bugsift.api.auth import router as auth_router
from bugsift.api.keys import router as keys_router
from bugsift.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="bugsift",
        version=__version__,
        docs_url="/docs" if settings.env == "development" else None,
        redoc_url=None,
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

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.include_router(auth_router)
    app.include_router(keys_router)

    return app


app = create_app()
