import json
from pathlib import Path

from app import __version__

MIN_PATHS = 12
OPENAPI_EXPORT = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"


def test_health_reports_version_and_db(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["scenarios"] >= 1
    assert body["content_errors"] == 0
    assert body["db"] == "sqlite"


def test_openapi_operations_have_summary_and_tags(client):
    spec = client.get("/openapi.json").json()
    assert len(spec["paths"]) >= MIN_PATHS
    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            assert operation.get("summary"), f"{method} {path} без summary"
            assert operation.get("tags"), f"{method} {path} без tags"


def test_openapi_has_no_anonymous_body_schemas(client):
    spec = client.get("/openapi.json").json()
    anonymous = [name for name in spec["components"]["schemas"] if name.startswith("Body_")]
    assert anonymous == []


def test_openapi_export_is_current(client):
    """docs/openapi.json перегенерируется скриптом scripts/export_openapi.py после изменения маршрутов."""
    exported = json.loads(OPENAPI_EXPORT.read_text(encoding="utf-8"))
    assert exported == client.get("/openapi.json").json()
