from pathlib import Path

from fastapi.testclient import TestClient

from arvuno_core.app import create_app
from arvuno_core.config import Settings


def isolated_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        backup_dir=tmp_path / "backups",
    )


def test_correlation_id_is_returned_and_can_be_provided(tmp_path: Path) -> None:
    client = TestClient(create_app(isolated_settings(tmp_path)))

    response = client.get("/health", headers={"X-Correlation-ID": "test-correlation"})

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "test-correlation"


def test_correlation_id_is_generated_when_missing(tmp_path: Path) -> None:
    client = TestClient(create_app(isolated_settings(tmp_path)))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"]
