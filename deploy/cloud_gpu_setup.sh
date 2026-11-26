#!/usr/bin/env bash
# One-command SupoClip Cloud GPU setup (RunPod, Vast.ai, Ubuntu GPU VMs).
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Pain899/supoclip.git}"
APP_DIR="${APP_DIR:-supoclip}"

if [ ! -f "docker-compose.yml" ]; then
  if [ ! -d "$APP_DIR" ]; then
    git clone "$REPO_URL" "$APP_DIR"
  fi
  cd "$APP_DIR"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker..."
  curl -fsSL https://get.docker.com | sh
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Installing Docker Compose plugin..."
  apt-get update -qq && apt-get install -y -qq docker-compose-plugin
fi

if [ ! -f ".env" ]; then
  cp .env.example .env
fi

set_env() {
  local key="$1" val="$2"
  if grep -qE "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${val}|" .env
  else
    echo "${key}=${val}" >> .env
  fi
}

gen_hex() {
  openssl rand -hex 32
}

if ! grep -qE '^GOOGLE_API_KEY=AIza' .env; then
  read -rsp "Enter GOOGLE_API_KEY (AIzaSy... from Google AI Studio): " GOOGLE_KEY
  echo ""
  if [ -n "${GOOGLE_KEY:-}" ]; then
    set_env "GOOGLE_API_KEY" "$GOOGLE_KEY"
  fi
fi

set_env "SELF_HOST" "true"
set_env "FRONTEND_PORT" "3107"
set_env "FRONTEND_BUILD_TARGET" "production"
set_env "NODE_ENV" "production"
set_env "BACKEND_CPU_ONLY" "false"
set_env "TRANSCRIPTION_PROVIDER" "whisper"
set_env "WHISPER_MODEL_SIZE" "small"
set_env "WHISPER_UNLOAD_AFTER_TRANSCRIBE" "true"
set_env "LLM" "google-gla:gemini-2.5-flash"
set_env "MAX_CLIPS" "20"
set_env "FAST_MODE_MAX_CLIPS" "20"
set_env "MIN_VIRALITY_SCORE" "78"
set_env "YOUTUBE_DOWNLOAD_MAX_BYTES" "10000000000"

grep -qE '^BETTER_AUTH_SECRET=.+' .env || set_env "BETTER_AUTH_SECRET" "$(gen_hex)"
grep -qE '^BACKEND_AUTH_SECRET=.+' .env || set_env "BACKEND_AUTH_SECRET" "$(gen_hex)"
grep -qE '^APP_SETTINGS_ENCRYPTION_KEY=.+' .env || set_env "APP_SETTINGS_ENCRYPTION_KEY" "$(gen_hex)"

echo "Starting SupoClip containers..."
docker compose up -d --build

echo ""
echo "SupoClip is starting!"
echo "If accessing from your PC via SSH tunnel, run on Windows:"
echo "  ssh -L 3107:localhost:3107 -L 8000:localhost:8000 <user>@<server-ip>"
echo "Then open: http://localhost:3107"
