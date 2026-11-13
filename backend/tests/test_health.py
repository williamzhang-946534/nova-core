from pathlib import Path

from fastapi.testclient import TestClient

from arvuno_core import __version__
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


def test_health_reports_process_status_without_external_dependencies(tmp_path: Path) -> None:
    client = TestClient(create_app(isolated_settings(tmp_path)))

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["environment"] == "test"
    assert body["checked_at"].endswith("Z")
