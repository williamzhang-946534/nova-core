from fastapi.testclient import TestClient

from nova_core.app import create_app


def test_correlation_id_is_returned_and_can_be_provided() -> None:
    client = TestClient(create_app())

    response = client.get("/health", headers={"X-Correlation-ID": "test-correlation"})

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "test-correlation"


def test_correlation_id_is_generated_when_missing() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"]
