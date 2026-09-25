#!/usr/bin/env bash
# Все проверки проекта одной командой: тесты и линтер сервера, валидатор сценариев,
# тесты и сборка фронта. Останавливается на первой ошибке.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
python="$root/backend/.venv/Scripts/python.exe"
if [ ! -x "$python" ]; then
  python="$root/backend/.venv/bin/python"
fi

cd "$root/backend"
"$python" -m pytest -q
"$python" -m ruff check .
"$python" -m ruff format --check .
if [ -f app/scenarios/validator.py ]; then
  "$python" -m app.scenarios.validator ../content
fi

cd "$root/frontend"
npm test --silent
npm run build --silent

echo "Все проверки прошли"
