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


def test_openapi_document_is_available_and_contains_health(tmp_path: Path) -> None:
    client = TestClient(create_app(isolated_settings(tmp_path)))

    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert "/health" in schema["paths"]
