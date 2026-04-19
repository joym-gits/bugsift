FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/pyproject.toml
COPY src /app/src
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini

RUN pip install -e .

# Pre-download the default fastembed model so the first retrieval/dedup
# run doesn't pay a ~130 MB cold-start tax against the user's event loop.
ENV FASTEMBED_CACHE_PATH=/app/.fastembed_cache
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5')"

ENV PYTHONPATH=/app/src

EXPOSE 8000

CMD ["gunicorn", "bugsift.api.main:app", \
     "--bind", "0.0.0.0:8000", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "2", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
