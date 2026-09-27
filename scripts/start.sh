#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

no_browser=false
timeout_seconds="${START_TIMEOUT_SECONDS:-120}"
app_url="${APP_URL:-}"

while (($#)); do
  case "$1" in
    --no-browser) no_browser=true ;;
    --timeout)
      [[ $# -ge 2 ]] || { echo "--timeout requires a number of seconds." >&2; exit 2; }
      timeout_seconds="$2"
      shift
      ;;
    --url)
      [[ $# -ge 2 ]] || { echo "--url requires an application URL." >&2; exit 2; }
      app_url="$2"
      shift
      ;;
    -h|--help)
      echo "Usage: scripts/start.sh [--no-browser] [--timeout SECONDS] [--url URL]"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

[[ "$timeout_seconds" =~ ^[0-9]+$ ]] && ((timeout_seconds >= 10)) || {
  echo "Timeout must be an integer of at least 10 seconds." >&2
  exit 2
}

if [[ ! -e .env ]]; then
  [[ -f .env.example ]] || { echo "Missing .env.example in $repo_root." >&2; exit 1; }
  cp -- .env.example .env
  echo "Created .env from .env.example."
fi

command -v docker >/dev/null 2>&1 || {
  echo "Docker is not installed or is not in PATH." >&2
  exit 1
}
docker compose version >/dev/null 2>&1 || {
  echo "Docker Compose v2 is unavailable. Install or update Docker Desktop/Engine." >&2
  exit 1
}
docker info >/dev/null 2>&1 || {
  echo "Docker Engine is unavailable. Start it and run this script again." >&2
  exit 1
}
command -v curl >/dev/null 2>&1 || {
  echo "curl is required for the readiness check." >&2
  exit 1
}

echo "Building and starting Provodnik 400..."
docker compose up --build --detach

if [[ -z "$app_url" ]]; then
  published="$(docker compose port app 8000 2>/dev/null || true)"
  if [[ "$published" =~ :([0-9]+)$ ]]; then
    app_url="http://localhost:${BASH_REMATCH[1]}"
  else
    app_url="http://localhost:8000"
  fi
fi
app_url="${app_url%/}"
ready_url="$app_url/api/health/ready"
deadline=$((SECONDS + timeout_seconds))

echo "Waiting for $ready_url ..."
until curl --fail --silent --show-error --max-time 3 "$ready_url" >/dev/null 2>&1; do
  if ((SECONDS >= deadline)); then
    docker compose ps || true
    echo "The application did not become ready within ${timeout_seconds}s." >&2
    echo "Inspect it with: docker compose logs --tail=100 app" >&2
    exit 1
  fi
  sleep 2
done

echo "Provodnik 400 is ready: $app_url"
if [[ "$no_browser" == false ]]; then
  case "$(uname -s)" in
    Darwin*) open "$app_url" || echo "Open $app_url in your browser." ;;
    Linux*)
      if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$app_url" >/dev/null 2>&1 || echo "Open $app_url in your browser."
      else
        echo "Open $app_url in your browser."
      fi
      ;;
    MINGW*|MSYS*|CYGWIN*) cmd.exe /c start "" "$app_url" || echo "Open $app_url in your browser." ;;
    *) echo "Open $app_url in your browser." ;;
  esac
fi
