from typing import Any

from arvuno_core.robots.errors import (
    RobotAdapterUnavailableError,
    RobotCapabilityDisabledError,
    RobotConnectionError,
    RobotInvalidParameterError,
    RobotNotFoundError,
    RobotSafetyStateError,
    RobotUnavailableError,
)
from arvuno_core.robots.models import (
    RegisteredRobotTaskRequest,
    RobotCapabilityName,
    RobotTaskRequestCreate,
)
from arvuno_core.robots.service import RobotApplicationService
from arvuno_core.tools.errors import (
    ToolExecutionFailedError,
    ToolPermissionDeniedError,
    ToolStateConflictError,
    ToolValidationError,
)
from arvuno_core.tools.models import (
    RobotActionInput,
    RobotActionOutput,
    RobotCapabilitiesInput,
    RobotCapabilitiesOutput,
    RobotConsentsInput,
    RobotConsentsOutput,
    RobotStatusInput,
    RobotStatusOutput,
    RobotTaskHistoryInput,
    RobotTaskHistoryOutput,
    ToolExecutionContext,
    ToolPermission,
    ToolRiskLevel,
)
from arvuno_core.tools.registry import ToolDefinition, ToolRegistry


def register_robot_tools(
    registry: ToolRegistry,
    robot_service: RobotApplicationService,
) -> None:
    """Register robot tools that can execute only through ToolExecutor."""

    async def robot_status(
        _context: ToolExecutionContext,
        raw_input: RobotStatusInput,
    ) -> RobotStatusOutput:
        try:
            state = await robot_service.state(raw_input.robot_id)
        except RobotNotFoundError as exc:
            raise ToolPermissionDeniedError("The robot is not available to Arvuno.") from exc
        except RobotAdapterUnavailableError as exc:
            raise ToolExecutionFailedError("The robot adapter is unavailable.") from exc
        return RobotStatusOutput(
            robot_id=raw_input.robot_id,
            state=state.model_dump(mode="json"),
        )

    async def robot_capabilities(
        _context: ToolExecutionContext,
        raw_input: RobotCapabilitiesInput,
    ) -> RobotCapabilitiesOutput:
        try:
            capabilities = await robot_service.capabilities(raw_input.robot_id)
        except RobotNotFoundError as exc:
            raise ToolPermissionDeniedError("The robot is not available to Arvuno.") from exc
        return RobotCapabilitiesOutput(
            robot_id=raw_input.robot_id,
            capabilities=[capability.model_dump(mode="json") for capability in capabilities],
        )

    async def robot_consents(
        _context: ToolExecutionContext,
        raw_input: RobotConsentsInput,
    ) -> RobotConsentsOutput:
        capability = RobotCapabilityName(raw_input.capability) if raw_input.capability else None
        try:
            consents = await robot_service.list_consents(
                raw_input.robot_id,
                capability=capability,
                active_only=raw_input.active_only,
            )
        except RobotNotFoundError as exc:
            raise ToolPermissionDeniedError("The robot is not available to Arvuno.") from exc
        return RobotConsentsOutput(
            robot_id=raw_input.robot_id,
            consents=[consent.model_dump(mode="json") for consent in consents],
        )

    async def robot_task_history(
        _context: ToolExecutionContext,
        raw_input: RobotTaskHistoryInput,
    ) -> RobotTaskHistoryOutput:
        try:
            requests = await robot_service.list_task_requests(
                raw_input.robot_id,
                limit=raw_input.limit,
            )
        except RobotNotFoundError as exc:
            raise ToolPermissionDeniedError("The robot is not available to Arvuno.") from exc
        return RobotTaskHistoryOutput(
            robot_id=raw_input.robot_id,
            requests=[request.model_dump(mode="json") for request in requests],
        )

    async def execute_action(
        tool_name: str,
        capability: RobotCapabilityName,
        context: ToolExecutionContext,
        raw_input: RobotActionInput,
    ) -> RobotActionOutput:
        if not context.task_system:
            raise ToolPermissionDeniedError(
                "Robot actions can execute only through the task system."
            )
        if context.task_id is None or context.task_step_id is None:
            raise ToolPermissionDeniedError("Robot actions require task and task step identifiers.")
        if context.tool_execution_id is None:
            raise ToolExecutionFailedError(
                "The robot action does not have a tool execution identifier."
            )

        parameters = _action_parameters(capability, raw_input)
        request = RobotTaskRequestCreate(
            capability=capability,
            parameters=parameters,
            requested_by="task_system",
            origin_type="task_system",
            task_id=context.task_id,
            idempotency_key=f"tool-execution:{context.tool_execution_id}",
            confirmed=False,
            correlation_id=context.correlation_id,
        )
        try:
            stored = await robot_service.execute_preauthorized_task_request(
                raw_input.robot_id,
                request,
                task_id=context.task_id,
                task_step_id=context.task_step_id,
                tool_execution_id=context.tool_execution_id,
            )
        except RobotNotFoundError as exc:
            raise ToolPermissionDeniedError("The robot is not available to Arvuno.") from exc
        except (RobotConnectionError, RobotUnavailableError) as exc:
            raise ToolStateConflictError("The robot is unavailable.") from exc
        except RobotCapabilityDisabledError as exc:
            raise ToolPermissionDeniedError(
                "The robot capability is not enabled for execution."
            ) from exc
        except RobotInvalidParameterError as exc:
            raise ToolValidationError("The robot rejected the action parameters.") from exc
        except RobotSafetyStateError as exc:
            raise ToolStateConflictError(exc.message) from exc

        if stored.status != "succeeded":
            error = dict(stored.error or {})
            if stored.status == "timeout":
                raise ToolStateConflictError(
                    "The robot action timed out.",
                    details={"robot_request_id": stored.id, **error},
                )
            raise ToolExecutionFailedError(
                "The robot action did not complete successfully.",
                details={"robot_request_id": stored.id, **error},
            )
        return _action_output(raw_input.robot_id, stored, context)

    async def robot_observe_scene(
        context: ToolExecutionContext,
        raw_input: RobotActionInput,
    ) -> RobotActionOutput:
        return await execute_action(
            "robot_observe_scene",
            RobotCapabilityName.OBSERVE_SCENE,
            context,
            raw_input,
        )

    async def robot_look_at(
        context: ToolExecutionContext,
        raw_input: RobotActionInput,
    ) -> RobotActionOutput:
        return await execute_action(
            "robot_look_at",
            RobotCapabilityName.LOOK_AT,
            context,
            raw_input,
        )

    async def robot_speak(
        context: ToolExecutionContext,
        raw_input: RobotActionInput,
    ) -> RobotActionOutput:
        return await execute_action(
            "robot_speak",
            RobotCapabilityName.SPEAK,
            context,
            raw_input,
        )

    async def robot_listen(
        context: ToolExecutionContext,
        raw_input: RobotActionInput,
    ) -> RobotActionOutput:
        return await execute_action(
            "robot_listen",
            RobotCapabilityName.LISTEN,
            context,
            raw_input,
        )

    async def robot_safe_stop(
        context: ToolExecutionContext,
        raw_input: RobotActionInput,
    ) -> RobotActionOutput:
        return await execute_action(
            "robot_safe_stop",
            RobotCapabilityName.REQUEST_SAFE_STOP,
            context,
            raw_input,
        )

    async def robot_idle(
        context: ToolExecutionContext,
        raw_input: RobotActionInput,
    ) -> RobotActionOutput:
        return await execute_action(
            "robot_idle",
            RobotCapabilityName.ENTER_IDLE_POSE,
            context,
            raw_input,
        )

    definitions = (
        ToolDefinition(
            name="robot_status",
            version="1.0.0",
            description="Read the latest registered robot state projection.",
            category="robot_query",
            risk_level=ToolRiskLevel.READ_ONLY,
            default_permission=ToolPermission.ALLOW,
            requires_confirmation=False,
            enabled=True,
            input_type=RobotStatusInput,
            output_type=RobotStatusOutput,
            handler=robot_status,
        ),
        ToolDefinition(
            name="robot_capabilities",
            version="1.0.0",
            description="Read the discovered and governed robot capability projection.",
            category="robot_query",
            risk_level=ToolRiskLevel.READ_ONLY,
            default_permission=ToolPermission.ALLOW,
            requires_confirmation=False,
            enabled=True,
            input_type=RobotCapabilitiesInput,
            output_type=RobotCapabilitiesOutput,
            handler=robot_capabilities,
        ),
        ToolDefinition(
            name="robot_consents",
            version="1.0.0",
            description="Read persisted robot consent grants and their effective state.",
            category="robot_query",
            risk_level=ToolRiskLevel.READ_ONLY,
            default_permission=ToolPermission.ALLOW,
            requires_confirmation=False,
            enabled=True,
            input_type=RobotConsentsInput,
            output_type=RobotConsentsOutput,
            handler=robot_consents,
        ),
        ToolDefinition(
            name="robot_task_history",
            version="1.0.0",
            description="Read persisted robot task requests and execution results.",
            category="robot_query",
            risk_level=ToolRiskLevel.READ_ONLY,
            default_permission=ToolPermission.ALLOW,
            requires_confirmation=False,
            enabled=True,
            input_type=RobotTaskHistoryInput,
            output_type=RobotTaskHistoryOutput,
            handler=robot_task_history,
        ),
        ToolDefinition(
            name="robot_observe_scene",
            version="1.0.0",
            description="Run a consented desktop robot scene observation.",
            category="robot_control",
            risk_level=ToolRiskLevel.MEDIUM,
            default_permission=ToolPermission.ALLOW,
            requires_confirmation=True,
            enabled=True,
            input_type=RobotActionInput,
            output_type=RobotActionOutput,
            handler=robot_observe_scene,
        ),
        ToolDefinition(
            name="robot_look_at",
            version="1.0.0",
            description="Run a consented desktop robot look-at action.",
            category="robot_control",
            risk_level=ToolRiskLevel.MEDIUM,
            default_permission=ToolPermission.ALLOW,
            requires_confirmation=True,
            enabled=True,
            input_type=RobotActionInput,
            output_type=RobotActionOutput,
            handler=robot_look_at,
        ),
        ToolDefinition(
            name="robot_speak",
            version="1.0.0",
            description="Run a consented desktop robot speech action.",
            category="robot_control",
            risk_level=ToolRiskLevel.LOW,
            default_permission=ToolPermission.ALLOW,
            requires_confirmation=True,
            enabled=True,
            input_type=RobotActionInput,
            output_type=RobotActionOutput,
            handler=robot_speak,
        ),
        ToolDefinition(
            name="robot_listen",
            version="1.0.0",
            description="Run a consented desktop robot listening action.",
            category="robot_control",
            risk_level=ToolRiskLevel.MEDIUM,
            default_permission=ToolPermission.ALLOW,
            requires_confirmation=True,
            enabled=True,
            input_type=RobotActionInput,
            output_type=RobotActionOutput,
            handler=robot_listen,
        ),
        ToolDefinition(
            name="robot_safe_stop",
            version="1.0.0",
            description="Request the desktop robot's independently enforced safe stop.",
            category="robot_safety",
            risk_level=ToolRiskLevel.LOW,
            default_permission=ToolPermission.ALLOW,
            requires_confirmation=False,
            enabled=True,
            input_type=RobotActionInput,
            output_type=RobotActionOutput,
            handler=robot_safe_stop,
        ),
        ToolDefinition(
            name="robot_idle",
            version="1.0.0",
            description="Move the desktop robot to its configured idle pose.",
            category="robot_control",
            risk_level=ToolRiskLevel.MEDIUM,
            default_permission=ToolPermission.ALLOW,
            requires_confirmation=True,
            enabled=True,
            input_type=RobotActionInput,
            output_type=RobotActionOutput,
            handler=robot_idle,
        ),
    )
    for definition in definitions:
        registry.register(definition)


def _action_parameters(
    capability: RobotCapabilityName,
    raw_input: RobotActionInput,
) -> dict[str, Any]:
    if capability is RobotCapabilityName.SPEAK:
        if raw_input.text is None:
            raise ToolValidationError("robot_speak requires text.")
        return {"text": raw_input.text}
    if capability is RobotCapabilityName.LOOK_AT and raw_input.target is not None:
        return {"target": raw_input.target}
    return {}


def _action_output(
    robot_id: str,
    stored: RegisteredRobotTaskRequest,
    context: ToolExecutionContext,
) -> RobotActionOutput:
    assert stored.result is not None
    return RobotActionOutput(
        robot_id=robot_id,
        request_id=stored.id,
        capability=stored.capability.value,
        status=stored.status.value,
        result=stored.result,
        verified=True,
        tool_execution_id=context.tool_execution_id or "",
        task_id=stored.task_id,
        task_step_id=stored.task_step_id,
        correlation_id=stored.correlation_id,
    )


__all__ = ["register_robot_tools"]
