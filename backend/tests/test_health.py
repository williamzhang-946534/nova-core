from fastapi.testclient import TestClient

from arvuno_core import __version__
from arvuno_core.app import create_app


def test_health_reports_process_status_without_external_dependencies() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["environment"] == "development"
    assert body["checked_at"].endswith("Z")
