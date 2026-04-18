"""RQ worker entrypoint.

Phase 1: starts an RQ worker listening on the default queue. No jobs are
enqueued yet, so the worker sits idle — this is expected. Real job functions
land in later phases under `bugsift.workers.triage` and `bugsift.workers.indexing`.
"""

from __future__ import annotations

import logging

from redis import Redis
from rq import Queue, Worker

from bugsift.config import get_settings

logger = logging.getLogger(__name__)

QUEUES = ["default", "triage", "indexing"]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    connection = Redis.from_url(settings.redis_url)
    queues = [Queue(name, connection=connection) for name in QUEUES]
    logger.info("starting bugsift worker on queues=%s", QUEUES)
    Worker(queues, connection=connection).work(with_scheduler=False)


if __name__ == "__main__":
    main()
