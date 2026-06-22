from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND / "src"))

from bugsift.config import get_settings  # noqa: E402


def _masked_url(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.netloc.split("@")[-1]
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


async def main() -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)

    print(f"DATABASE_URL={_masked_url(settings.database_url)}")
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    sa.text("select current_database(), current_user, version()")
                )
            ).one()
            vector_available = await conn.scalar(
                sa.text(
                    "select exists (select 1 from pg_available_extensions where name = 'vector')"
                )
            )
            vector_installed = await conn.scalar(
                sa.text("select exists (select 1 from pg_extension where extname = 'vector')")
            )

        print(f"database={row[0]} user={row[1]}")
        print(row[2].split(",", 1)[0])
        print(f"vector_available={vector_available}")
        print(f"vector_installed={vector_installed}")
        return 0 if vector_available else 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
