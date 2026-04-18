#!/usr/bin/env bash
# Convenience bootstrap: copy .env, generate the required secrets if they are
# still blank, and print next steps. Safe to re-run.
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "created .env from .env.example"
fi

fill_if_blank() {
  local key="$1"
  local value="$2"
  if grep -E "^${key}=$" .env > /dev/null; then
    # portable in-place edit
    awk -v k="$key" -v v="$value" 'BEGIN{FS=OFS="="} $1==k && NF==2 && $2=="" {print k"="v; next} {print}' .env > .env.tmp
    mv .env.tmp .env
    echo "filled ${key}"
  fi
}

if command -v python3 > /dev/null; then
  enc_key=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null || true)
  sess_secret=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))" 2>/dev/null || true)
  [[ -n "${enc_key}" ]] && fill_if_blank "BUGSIFT_ENCRYPTION_KEY" "${enc_key}"
  [[ -n "${sess_secret}" ]] && fill_if_blank "BUGSIFT_SESSION_SECRET" "${sess_secret}"
fi

echo
echo "next: docker-compose up --build"
