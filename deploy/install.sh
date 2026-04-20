#!/usr/bin/env bash
# bugsift — one-command self-host installer.
#
#   curl -fsSL https://github.com/joym-gits/bugsift/releases/latest/download/install.sh | bash
#
# Or, if you want to review it first (you should):
#
#   curl -fsSLo install.sh https://github.com/joym-gits/bugsift/releases/latest/download/install.sh
#   less install.sh
#   bash install.sh
#
# The installer:
#   1. Verifies docker + docker compose are available.
#   2. Downloads docker-compose.prod.yml next to itself.
#   3. Generates a Fernet encryption key, a session signing secret,
#      and a bootstrap token — everything needed to boot, with no
#      hand-editing of ``.env``.
#   4. Pulls the pre-built images from GitHub Container Registry.
#   5. Runs ``alembic upgrade head``.
#   6. Starts the stack and prints the onboarding URL + bootstrap token.
#
# Re-running the script on an existing directory is safe — if ``.env``
# already exists, it's left alone.
#
# Pinning a specific release:
#
#   BUGSIFT_IMAGE_TAG=v0.1.0 \
#     curl -fsSL https://github.com/joym-gits/bugsift/releases/download/v0.1.0/install.sh | bash

set -euo pipefail

# --- config ----------------------------------------------------------------

: "${BUGSIFT_DIR:=$PWD/bugsift}"
# Default to the ``latest`` release — the URL is stable across releases
# because GitHub redirects ``releases/latest/download/<name>`` to the
# newest asset. Override ``BUGSIFT_ASSET_URL`` for a pinned version
# (e.g. https://github.com/.../releases/download/v0.1.0) or a fork.
# ``BUGSIFT_RAW_URL`` is kept for backward compat with older install
# commands that pulled from raw.githubusercontent.com.
: "${BUGSIFT_ASSET_URL:=https://github.com/joym-gits/bugsift/releases/latest/download}"
: "${BUGSIFT_RAW_URL:=$BUGSIFT_ASSET_URL}"
: "${BUGSIFT_PUBLIC_PORT:=8080}"
: "${BUGSIFT_PUBLIC_URL:=http://localhost:${BUGSIFT_PUBLIC_PORT}}"
: "${BUGSIFT_ENV:=production}"
: "${BUGSIFT_IMAGE_OWNER:=joym-gits}"
: "${BUGSIFT_IMAGE_TAG:=latest}"

# --- utils -----------------------------------------------------------------

c_reset='\033[0m'
c_bold='\033[1m'
c_dim='\033[2m'
c_primary='\033[38;5;208m'  # warm orange to match the dashboard
c_ok='\033[38;5;114m'
c_warn='\033[38;5;220m'
c_err='\033[38;5;203m'

say()  { printf '%b%s%b\n' "$c_primary" "$1" "$c_reset"; }
info() { printf '  %s\n' "$1"; }
ok()   { printf '%b✓%b %s\n' "$c_ok" "$c_reset" "$1"; }
warn() { printf '%b!%b %s\n' "$c_warn" "$c_reset" "$1"; }
die()  { printf '%b✗ %s%b\n' "$c_err" "$1" "$c_reset" >&2; exit 1; }

need() {
  command -v "$1" >/dev/null 2>&1 || die "$1 is required but not installed. See $2"
}

# Cross-platform random base64 — macOS and most Linux have openssl.
rand_url_b64() {
  openssl rand -base64 "${1:-48}" | tr -d '\n' | tr '+/' '-_' | tr -d '='
}

# Fernet wants exactly 32 bytes of url-safe base64. openssl rand 32
# then re-encode to the base64url alphabet works on every platform.
fernet_key() {
  openssl rand -base64 32 | tr '+/' '-_'
}

# --- pre-flight ------------------------------------------------------------

say "bugsift installer"
info "target: $BUGSIFT_DIR"

need openssl "https://www.openssl.org"
need docker  "https://docs.docker.com/engine/install/"
need curl    "https://curl.se"

if ! docker compose version >/dev/null 2>&1; then
  die "docker compose plugin not found. Upgrade Docker Desktop, or install docker-compose-plugin."
fi

if ! docker info >/dev/null 2>&1; then
  die "docker daemon is not running or you don't have permission to talk to it."
fi

mkdir -p "$BUGSIFT_DIR"
cd "$BUGSIFT_DIR"

# --- compose file ----------------------------------------------------------

if [ ! -f docker-compose.yml ]; then
  info "downloading docker-compose.yml"
  # Release assets land at ``<asset_url>/docker-compose.prod.yml``; the
  # legacy ``raw.githubusercontent.com/.../deploy/...`` URL layout is
  # still tolerated so someone running the installer from a non-
  # released fork can set ``BUGSIFT_ASSET_URL`` to the raw path.
  if [[ "$BUGSIFT_ASSET_URL" == *"/raw.githubusercontent.com/"* ]]; then
    compose_url="$BUGSIFT_ASSET_URL/deploy/docker-compose.prod.yml"
  else
    compose_url="$BUGSIFT_ASSET_URL/docker-compose.prod.yml"
  fi
  curl -fsSLo docker-compose.yml "$compose_url"
  ok "docker-compose.yml written"
else
  info "docker-compose.yml already exists — left alone"
fi

# --- .env ------------------------------------------------------------------

if [ -f .env ]; then
  warn ".env already exists — leaving secrets alone. Delete it to regenerate."
else
  info "generating secrets + .env"
  BUGSIFT_ENCRYPTION_KEY="$(fernet_key)"
  BUGSIFT_SESSION_SECRET="$(rand_url_b64 48)"
  BUGSIFT_BOOTSTRAP_TOKEN="$(rand_url_b64 32)"
  POSTGRES_PASSWORD="$(rand_url_b64 24)"

  cat >.env <<EOF
# ----- Core -----
BUGSIFT_ENV=${BUGSIFT_ENV}
BUGSIFT_PUBLIC_URL=${BUGSIFT_PUBLIC_URL}
BUGSIFT_PUBLIC_PORT=${BUGSIFT_PUBLIC_PORT}

BUGSIFT_ENCRYPTION_KEY=${BUGSIFT_ENCRYPTION_KEY}
BUGSIFT_SESSION_SECRET=${BUGSIFT_SESSION_SECRET}
BUGSIFT_BOOTSTRAP_TOKEN=${BUGSIFT_BOOTSTRAP_TOKEN}
BUGSIFT_TRUST_PROXY=1

# ----- Image source (override to pin a specific tag or fork) -----
BUGSIFT_IMAGE_OWNER=${BUGSIFT_IMAGE_OWNER}
BUGSIFT_IMAGE_TAG=${BUGSIFT_IMAGE_TAG}

# ----- Database -----
POSTGRES_USER=bugsift
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_DB=bugsift
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
DATABASE_URL=postgresql+asyncpg://bugsift:${POSTGRES_PASSWORD}@postgres:5432/bugsift

# ----- Redis -----
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_URL=redis://redis:6379/0

# ----- Frontend -----
NEXT_PUBLIC_API_BASE_URL=${BUGSIFT_PUBLIC_URL}/api

# ----- GitHub App -----
# Left blank on purpose. Onboarding wizard will register an App for
# you and populate the db-stored credentials. You don't need to touch
# these unless you want to bring your own App.
GITHUB_APP_ID=
GITHUB_APP_CLIENT_ID=
GITHUB_APP_CLIENT_SECRET=
GITHUB_APP_WEBHOOK_SECRET=
GITHUB_APP_PRIVATE_KEY=
GITHUB_APP_PRIVATE_KEY_PATH=
EOF
  ok ".env written"
  chmod 600 .env
fi

# Re-read values from whatever .env we ended up with — matters for
# the post-install hint on idempotent reruns.
# shellcheck disable=SC1091
set -a; . ./.env; set +a

# --- pull + boot -----------------------------------------------------------

info "pulling images"
docker compose pull

info "running database migrations"
# Start only what's needed for migrations first so we can fail fast if
# the DB isn't reachable.
docker compose up -d postgres redis
docker compose run --rm backend alembic upgrade head

info "starting stack"
docker compose up -d

# --- final hint ------------------------------------------------------------

echo
ok "bugsift is up"
printf "%b  dashboard:%b       %s\n"       "$c_bold" "$c_reset" "$BUGSIFT_PUBLIC_URL"
printf "%b  bootstrap token:%b %s\n"       "$c_bold" "$c_reset" "$BUGSIFT_BOOTSTRAP_TOKEN"
printf "%b  env file:%b        %s/.env\n"  "$c_bold" "$c_reset" "$BUGSIFT_DIR"
echo
printf "%bNext steps%b\n" "$c_primary" "$c_reset"
info "1. Open the dashboard and click 'Register GitHub App'."
info "2. When prompted, paste the bootstrap token above."
info "3. Install the App on a repo and add your LLM provider key."
info "   Full guide: https://github.com/${BUGSIFT_IMAGE_OWNER}/bugsift/blob/main/deploy/README.md"
echo
printf "%bDay-to-day commands%b\n" "$c_dim" "$c_reset"
info "  cd $BUGSIFT_DIR"
info "  docker compose logs -f backend       # watch logs"
info "  docker compose pull && docker compose up -d  # upgrade"
info "  docker compose down                  # stop"
echo
