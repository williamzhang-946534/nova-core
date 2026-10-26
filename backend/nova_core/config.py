from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or a local .env file."""

    app_name: str = "Nova Core"
    environment: Literal["development", "test", "production"] = "development"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"
    api_token: SecretStr | None = None
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"]
    )
    data_dir: Path = Field(default_factory=lambda: PROJECT_ROOT / "data")
    database_filename: str = Field(default="nova.sqlite3", min_length=1)
    database_path: Path | None = None
    log_dir: Path = Field(default_factory=lambda: PROJECT_ROOT / "logs")
    log_filename: str = Field(default="nova-backend.log", min_length=1)
    backup_dir: Path = Field(default_factory=lambda: PROJECT_ROOT / "backups")
    backup_retention_count: int = Field(default=10, ge=1, le=1000)

    model_config = SettingsConfigDict(
        env_prefix="NOVA_",
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

    @model_validator(mode="after")
    def require_security_settings_in_production(self) -> "Settings":
        if self.environment == "production" and not (
            self.api_token and self.api_token.get_secret_value().strip()
        ):
            raise ValueError("NOVA_API_TOKEN is required when NOVA_ENV is production")
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
