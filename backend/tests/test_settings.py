from pathlib import Path

import pytest
from pydantic import ValidationError

from nova_core.config import PROJECT_ROOT, Settings


def settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_local_paths_resolve_against_project_root_by_default() -> None:
    test_settings = settings(data_dir=Path("custom-data"), database_filename="nova.sqlite3")

    assert test_settings.resolved_data_dir == PROJECT_ROOT / "custom-data"
    assert test_settings.resolved_database_path == PROJECT_ROOT / "custom-data" / "nova.sqlite3"
    assert test_settings.database_url == (
        f"sqlite+pysqlite:///{(PROJECT_ROOT / 'custom-data' / 'nova.sqlite3').as_posix()}"
    )


def test_explicit_database_path_can_live_in_a_nested_local_directory(tmp_path: Path) -> None:
    database_path = tmp_path / "storage" / "nested" / "nova.sqlite3"
    test_settings = settings(database_path=database_path)

    test_settings.ensure_local_directories()

    assert database_path.parent.is_dir()


def test_database_and_log_filenames_cannot_escape_their_directories() -> None:
    with pytest.raises(ValidationError, match="single file name"):
        settings(database_filename="../escaped.sqlite3")

    with pytest.raises(ValidationError, match="single file name"):
        settings(log_filename="nested/nova.log")


def test_production_requires_a_non_empty_api_token() -> None:
    with pytest.raises(ValidationError, match="NOVA_API_TOKEN"):
        settings(environment="production")

    test_settings = settings(environment="production", api_token=" local-token ")
    assert test_settings.api_token is not None
    assert test_settings.api_token.get_secret_value() == " local-token "


def test_home_assistant_defaults_are_safe_and_allowlist_is_parseable() -> None:
    test_settings = settings(home_assistant_allowed_entity_ids="light.living_room, switch.airer")

    assert test_settings.home_assistant_url is None
    assert test_settings.home_assistant_token is None
    assert test_settings.home_assistant_timeout_seconds == 10.0
    assert test_settings.home_assistant_allowed_entity_ids == [
        "light.living_room",
        "switch.airer",
    ]
    assert test_settings.home_assistant_write_enabled is False
    assert test_settings.device_poll_interval_seconds == 30


def test_home_assistant_write_enabled_is_rejected_in_production() -> None:
    with pytest.raises(ValidationError, match="HOME_ASSISTANT_WRITE_ENABLED"):
        settings(
            environment="production",
            api_token="local-token",
            home_assistant_write_enabled=True,
        )


def test_event_retention_settings_are_configurable() -> None:
    test_settings = settings(
        event_retention_days=120,
        diagnostic_event_retention_days=45,
        long_term_event_types=["task_started", "tool_executed"],
        default_environment_name="apartment",
    )

    assert test_settings.event_retention_days == 120
    assert test_settings.diagnostic_event_retention_days == 45
    assert test_settings.long_term_event_types == ["task_started", "tool_executed"]
    assert test_settings.default_environment_name == "apartment"

    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        settings(event_retention_days=0)
