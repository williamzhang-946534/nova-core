from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field

from arvuno_core.perception.models import ActivePerceptionRequestView
from arvuno_core.tools.errors import ToolPermissionDeniedError, ToolValidationError
from arvuno_core.tools.models import ToolExecutionContext, ToolPermission, ToolRiskLevel
from arvuno_core.tools.registry import ToolDefinition, ToolRegistry


class ActivePerceptionExecuteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=64)


class ActivePerceptionExecuteOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request: ActivePerceptionRequestView


def register_active_perception_tool(
    registry: ToolRegistry,
    execution_provider: Callable[[str], Awaitable[ActivePerceptionRequestView]],
) -> None:
    """Register the read-only observation execution boundary."""

    async def execute_active_perception(
        _context: ToolExecutionContext,
        raw_input: ActivePerceptionExecuteInput,
    ) -> ActivePerceptionExecuteOutput:
        try:
            request = await execution_provider(raw_input.request_id)
        except Exception as exc:
            raise ToolPermissionDeniedError(
                "The active perception request could not be executed through its observer.",
                details={"request_id": raw_input.request_id},
            ) from exc
        if request.status != "fulfilled":
            raise ToolValidationError(
                "The active perception request did not reach the fulfilled state.",
                details={"request_id": request.id, "status": request.status},
            )
        return ActivePerceptionExecuteOutput(request=request)

    registry.register(
        ToolDefinition(
            name="active_perception_execute",
            version="1.0.0",
            description=(
                "Execute an explicitly authorized active-perception request through "
                "the configured read-only observer."
            ),
            category="active_perception",
            risk_level=ToolRiskLevel.READ_ONLY,
            default_permission=ToolPermission.ALLOW,
            requires_confirmation=False,
            enabled=True,
            input_type=ActivePerceptionExecuteInput,
            output_type=ActivePerceptionExecuteOutput,
            handler=execute_active_perception,
        )
    )


__all__ = [
    "ActivePerceptionExecuteInput",
    "ActivePerceptionExecuteOutput",
    "register_active_perception_tool",
]
