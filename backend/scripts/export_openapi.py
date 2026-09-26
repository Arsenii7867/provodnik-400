"""Выгрузка описания API в docs/openapi.json, чтобы его читали без запуска сервера:
из папки backend `python scripts/export_openapi.py`. После изменения маршрутов файл
перегенерируют этой же командой; тест сравнивает его с живым /openapi.json."""

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.main import create_app  # noqa: E402


def main():
    target = BACKEND_DIR.parent / "docs" / "openapi.json"
    spec = create_app().openapi()
    target.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OpenAPI: путей {len(spec['paths'])}, записано в {target}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
