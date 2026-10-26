from fastapi.testclient import TestClient

from nova_core.app import create_app


def test_request_validation_uses_standard_error_contract() -> None:
    app = create_app()

    @app.get("/__validation_test")
    def validation_test(value: int) -> dict[str, int]:
        return {"value": value}

    client = TestClient(app)
    response = client.get("/__validation_test")

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["correlation_id"]
    assert error["details"]["errors"][0]["location"] == ["query", "value"]


def test_unexpected_error_hides_internal_details() -> None:
    app = create_app()

    @app.get("/__internal_error_test")
    def internal_error_test() -> None:
        raise RuntimeError("sensitive internal detail")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/__internal_error_test")

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "INTERNAL_ERROR"
    assert error["message"] == "An internal server error occurred."
    assert "sensitive internal detail" not in response.text
