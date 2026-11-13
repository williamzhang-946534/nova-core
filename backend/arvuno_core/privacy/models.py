from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PrivacyErasureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_id: str = Field(min_length=1, max_length=255)
    conversation_ids: list[str] = Field(default_factory=list, max_length=100)
    confirm_local_user: bool = False


class PrivacyImpact(BaseModel):
    owner_id: str
    memories: int
    memory_consents: int
    preferences: int
    multimodal_consents: int
    data_access_grants: int
    media_assets: int
    capture_sessions: int
    conversations: int
    messages: int
    provider_logs: int
    audit_records_preserved: int


class PrivacyErasureResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    owner_id: str
    result: dict[str, int]
    media_files_failed: list[str] = Field(default_factory=list)
    audit_records_preserved: int
    completed_at: datetime
