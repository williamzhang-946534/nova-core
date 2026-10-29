from typing import Any

from pydantic import BaseModel, Field

from arvuno_core.tools.models import ToolExecutionResult


class ToolCatalogItem(BaseModel):
    name: str
    version: str
    description: str
    category: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    risk_level: str
    default_permission: str
    requires_confirmation: bool
    enabled: bool


class ToolCatalogData(BaseModel):
    data: list[ToolCatalogItem]


class ToolExecuteRequest(BaseModel):
    input: dict[str, Any]
    confirmation_token: str | None = Field(default=None, min_length=1, max_length=512)
    task_id: str | None = Field(default=None, min_length=36, max_length=36)
    task_step_id: str | None = Field(default=None, min_length=36, max_length=36)


class ToolExecutionData(ToolExecutionResult):
    pass


class ToolExecutionDataWrapper(BaseModel):
    data: ToolExecutionData
