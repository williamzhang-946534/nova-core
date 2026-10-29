from fastapi.testclient import TestClient

from arvuno_core.app import create_app


def test_openapi_document_is_available_and_contains_health() -> None:
    client = TestClient(create_app())

    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert "/health" in schema["paths"]
