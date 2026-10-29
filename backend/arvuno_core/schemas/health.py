from datetime import UTC, datetime

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    environment: str
    checked_at: str = Field(default_factory=utc_now_iso)
