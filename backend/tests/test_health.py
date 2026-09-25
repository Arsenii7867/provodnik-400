from app import __version__


def test_health_reports_version_and_db(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["scenarios"] == 0
    assert body["db"] == "sqlite"


def test_openapi_operations_have_summary_and_tags(client):
    spec = client.get("/openapi.json").json()
    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            assert operation.get("summary"), f"{method} {path} без summary"
            assert operation.get("tags"), f"{method} {path} без tags"
