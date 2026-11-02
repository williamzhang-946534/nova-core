from fastapi.testclient import TestClient

from arvuno_core.app import create_app
from arvuno_core.devices.errors import AdapterTimeoutError, AdapterUnavailableError


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


def test_device_adapter_errors_use_structured_api_contract() -> None:
    app = create_app()

    @app.get("/__adapter_unavailable_test")
    def adapter_unavailable_test() -> None:
        raise AdapterUnavailableError("Home Assistant is unreachable.")

    @app.get("/__adapter_timeout_test")
    def adapter_timeout_test() -> None:
        raise AdapterTimeoutError("The Home Assistant state request timed out.")

    client = TestClient(app, raise_server_exceptions=False)
    unavailable = client.get("/__adapter_unavailable_test")
    timeout = client.get("/__adapter_timeout_test")

    assert unavailable.status_code == 502
    assert unavailable.json()["error"]["code"] == "ADAPTER_ERROR"
    assert unavailable.json()["error"]["details"]["device_code"] == "adapter_unavailable"
    assert timeout.status_code == 504
    assert timeout.json()["error"]["code"] == "ADAPTER_TIMEOUT"
    assert timeout.json()["error"]["correlation_id"]
