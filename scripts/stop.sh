#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

command -v docker >/dev/null 2>&1 || {
  echo "Docker is not installed or is not in PATH." >&2
  exit 1
}
docker compose version >/dev/null 2>&1 || {
  echo "Docker Compose v2 is unavailable. Install or update Docker Desktop/Engine." >&2
  exit 1
}

docker compose down --remove-orphans
echo "Provodnik 400 stopped. Named data volumes were preserved."
