from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request

from arvuno_core.api.security import require_api_token
from arvuno_core.config import Settings
from arvuno_core.logging_config import correlation_id_var
from arvuno_core.schemas.tools import (
    ToolCatalogData,
    ToolCatalogItem,
    ToolExecuteRequest,
    ToolExecutionData,
    ToolExecutionDataWrapper,
)
from arvuno_core.tools.executor import ToolExecutor
from arvuno_core.tools.models import ToolExecutionContext

router = APIRouter(prefix="/api/tools", tags=["Tools"], dependencies=[Depends(require_api_token)])


def get_tool_executor(request: Request) -> ToolExecutor:
    executor = getattr(request.app.state, "tool_executor", None)
    if not isinstance(executor, ToolExecutor):
        raise RuntimeError("The tool executor is unavailable.")
    return executor


def get_catalog_settings(request: Request) -> Settings:
    settings = request.app.state.settings
    if not isinstance(settings, Settings):
        raise RuntimeError("The application settings are unavailable.")
    return settings


@router.get("", response_model=ToolCatalogData)
async def list_tools(
    executor: Annotated[ToolExecutor, Depends(get_tool_executor)],
    settings: Annotated[Settings, Depends(get_catalog_settings)],
) -> ToolCatalogData:
    permissions = settings.tool_permissions
    tools = [
        ToolCatalogItem.model_validate(item)
        for item in executor.registry.catalog(enabled_only=True)
        if permissions.get(item["name"], item["default_permission"]) != "deny"
        and not (
            permissions.get(item["name"], item["default_permission"]) == "allow_read_only"
            and item["risk_level"] != "read_only"
        )
    ]
    return ToolCatalogData(data=tools)


@router.post("/{tool_name}/execute", response_model=ToolExecutionDataWrapper)
async def execute_tool(
    tool_name: str,
    request: ToolExecuteRequest,
    raw_request: Request,
    executor: Annotated[ToolExecutor, Depends(get_tool_executor)],
) -> ToolExecutionDataWrapper:
    correlation_id = (
        correlation_id_var.get() or raw_request.headers.get("X-Correlation-ID") or str(uuid4())
    )
    result = await executor.execute(
        tool_name,
        request.input,
        context=ToolExecutionContext(
            correlation_id=correlation_id,
            task_id=request.task_id,
            task_step_id=request.task_step_id,
        ),
        confirmation_token=request.confirmation_token,
        task_id=request.task_id,
        task_step_id=request.task_step_id,
    )
    return ToolExecutionDataWrapper(data=ToolExecutionData.model_validate(result.model_dump()))
