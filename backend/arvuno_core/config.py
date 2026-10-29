from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

ToolPermissionSetting = Literal[
    "allow",
    "allow_read_only",
    "allow_low_risk",
    "require_confirmation",
    "deny",
]

AIStructuredOutputMode = Literal["json_schema", "json_object", "prompt_only"]


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or a local .env file."""

    app_name: str = "Arvuno Core"
    environment: Literal["development", "test", "production"] = "development"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"
    api_token: SecretStr | None = None
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"]
    )
    data_dir: Path = Field(default_factory=lambda: PROJECT_ROOT / "data")
    database_filename: str = Field(default="arvuno.sqlite3", min_length=1)
    database_path: Path | None = None
    log_dir: Path = Field(default_factory=lambda: PROJECT_ROOT / "logs")
    log_filename: str = Field(default="arvuno-backend.log", min_length=1)
    backup_dir: Path = Field(default_factory=lambda: PROJECT_ROOT / "backups")
    backup_retention_count: int = Field(default=10, ge=1, le=1000)
    home_assistant_url: HttpUrl | None = None
    home_assistant_token: SecretStr | None = None
    home_assistant_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    home_assistant_allowed_entity_ids: list[str] = Field(default_factory=list)
    home_assistant_write_enabled: bool = False
    device_poll_interval_seconds: int = Field(default=30, ge=1, le=3600)
    tool_confirmation_ttl_seconds: int = Field(default=300, ge=1, le=86400)
    tool_permissions: dict[str, ToolPermissionSetting] = Field(
        default_factory=lambda: {
            "list_devices": "allow",
            "get_device_state": "allow",
            "get_environment_state": "allow",
            "control_device": "allow_low_risk",
        }
    )
    event_retention_days: int = Field(default=180, ge=1, le=3650)
    diagnostic_event_retention_days: int = Field(default=90, ge=1, le=3650)
    long_term_event_types: list[str] = Field(
        default_factory=lambda: [
            "task_started",
            "task_completed",
            "task_failed",
            "tool_executed",
            "user_confirmed",
        ]
    )
    default_environment_name: str = Field(default="home", min_length=1, max_length=255)
    ai_provider: Literal["mock", "openai_compatible"] = "mock"
    ai_base_url: str | None = None
    ai_model: str | None = None
    ai_api_key: SecretStr | None = None
    ai_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    ai_max_retries: int = Field(default=2, ge=0, le=3)
    ai_structured_output_mode: AIStructuredOutputMode = "json_schema"
    ai_retry_backoff_seconds: float = Field(default=0.2, ge=0, le=10)

    model_config = SettingsConfigDict(
        env_prefix="ARVUNO_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("database_filename", "log_filename")
    @classmethod
    def reject_unsafe_filename(cls, value: str) -> str:
        if Path(value).name != value or value in {".", ".."}:
            raise ValueError("Filename must be a single file name without a directory component")
        return value

    @field_validator("home_assistant_allowed_entity_ids", mode="before")
    @classmethod
    def parse_allowed_entity_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        return value

    @field_validator("home_assistant_allowed_entity_ids")
    @classmethod
    def require_valid_entity_ids(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        for entity_id in value:
            if not entity_id or entity_id not in entity_id.strip() or "." not in entity_id:
                raise ValueError("Allowed entity IDs must be non-empty Home Assistant entity IDs")
            seen.add(entity_id)
        if len(seen) != len(value):
            raise ValueError("Allowed entity IDs must not contain duplicates")
        return value

    @model_validator(mode="after")
    def require_security_settings_in_production(self) -> "Settings":
        if self.environment == "production" and not (
            self.api_token and self.api_token.get_secret_value().strip()
        ):
            raise ValueError("ARVUNO_API_TOKEN is required when ARVUNO_ENV is production")
        if self.environment == "production" and self.home_assistant_write_enabled:
            raise ValueError(
                "ARVUNO_HOME_ASSISTANT_WRITE_ENABLED can only be enabled for controlled "
                "development validation"
            )
        return self

    @model_validator(mode="after")
    def require_complete_openai_compatible_settings(self) -> "Settings":
        if self.ai_provider != "openai_compatible":
            return self
        missing = [
            name
            for name, value in (
                ("ARVUNO_AI_BASE_URL", self.ai_base_url),
                ("ARVUNO_AI_MODEL", self.ai_model),
            )
            if value is None or not str(value).strip()
        ]
        if self.ai_api_key is None or not self.ai_api_key.get_secret_value().strip():
            missing.append("ARVUNO_AI_API_KEY")
        if missing:
            raise ValueError(f"Missing OpenAI-compatible AI settings: {', '.join(missing)}")
        if self.ai_base_url is not None and not self.ai_base_url.rstrip("/").startswith(
            ("http://", "https://")
        ):
            raise ValueError("ARVUNO_AI_BASE_URL must be an HTTP URL")
        return self

    def resolve_path(self, path: Path) -> Path:
        resolved = path if path.is_absolute() else PROJECT_ROOT / path
        return resolved.expanduser().resolve()

    @property
    def resolved_data_dir(self) -> Path:
        return self.resolve_path(self.data_dir)

    @property
    def resolved_log_dir(self) -> Path:
        return self.resolve_path(self.log_dir)

    @property
    def resolved_backup_dir(self) -> Path:
        return self.resolve_path(self.backup_dir)

    @property
    def resolved_database_path(self) -> Path:
        path = self.database_path or self.resolved_data_dir / self.database_filename
        return self.resolve_path(path)

    @property
    def database_url(self) -> str:
        return f"sqlite+pysqlite:///{self.resolved_database_path.as_posix()}"

    @property
    def resolved_log_file(self) -> Path:
        return self.resolve_path(self.log_dir / self.log_filename)

    def local_directories(self) -> tuple[Path, Path, Path]:
        return self.resolved_data_dir, self.resolved_log_dir, self.resolved_backup_dir

    def ensure_local_directories(self) -> None:
        directories = (*self.local_directories(), self.resolved_database_path.parent)
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
