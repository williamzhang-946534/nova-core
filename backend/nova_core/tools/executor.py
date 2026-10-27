import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from nova_core.devices.errors import (
    ActionFailedError,
    ActionUnsupportedError,
    AdapterTimeoutError,
    AdapterUnavailableError,
    AuthorizationError,
    DeviceError,
    DeviceNotFoundError,
    DeviceUnavailableError,
    DeviceWriteDisabledError,
    InvalidActionParameterError,
    StateVerificationFailedError,
)
from nova_core.events.models import (
    NovaEvent,
    NovaEventSource,
    NovaEventType,
    ToolExecutedPayload,
)
from nova_core.tools.confirmation import ConfirmationService, ConfirmationSubject
from nova_core.tools.errors import (
    ToolAdapterError,
    ToolAdapterTimeoutError,
    ToolConfirmationRequiredError,
    ToolDeviceUnavailableError,
    ToolError,
    ToolExecutionFailedError,
    ToolNotFoundError,
    ToolPermissionDeniedError,
    ToolPersistenceError,
    ToolRiskRejectedError,
    ToolStateConflictError,
    ToolValidationError,
)
from nova_core.tools.models import (
    ControlDeviceOutput,
    PermissionResult,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolRiskLevel,
)
from nova_core.tools.registry import ToolDefinition, ToolRegistry
from nova_core.tools.safety import SafetyDecision, SafetyPolicy
from nova_core.tools.storage import (
    ToolDefinitionRecord,
    ToolExecutionCreate,
    ToolExecutionStoreProtocol,
    ToolExecutionUpdate,
)

logger = logging.getLogger(__name__)


class ToolEventPublisherProtocol:
    async def publish(self, event: NovaEvent) -> None: ...


class ToolExecutor:
    """Runs the validated, authorized, audited, and post-checked tool chain."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        safety_policy: SafetyPolicy,
        confirmation_service: ConfirmationService,
        execution_store: ToolExecutionStoreProtocol,
        event_publisher: ToolEventPublisherProtocol | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        execution_id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._registry = registry
        self._safety_policy = safety_policy
        self._confirmation_service = confirmation_service
        self._execution_store = execution_store
        self._event_publisher = event_publisher
        self._clock = clock
        self._execution_id_factory = execution_id_factory

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    async def execute(
        self,
        tool_name: str,
        raw_input: dict[str, Any],
        *,
        context: ToolExecutionContext,
        confirmation_token: str | None = None,
        task_id: str | None = None,
        task_step_id: str | None = None,
    ) -> ToolExecutionResult:
        definition = self._registry.get(tool_name)
        if definition is None:
            logger.warning(
                "tool_execution_rejected_unregistered",
                extra={"tool_name": tool_name, "correlation_id": context.correlation_id},
            )
            raise ToolNotFoundError("The tool is not registered.")

        execution_id = self._execution_id_factory()
        started_at = self._clock()
        try:
            validated_input = definition.input_type.model_validate(raw_input)
        except ValidationError as exc:
            error = ToolValidationError(
                "The tool input is invalid.",
                details={"errors": exc.errors(include_url=False)},
            )
            decision = SafetyDecision(
                permission_result=PermissionResult.DENIED,
                risk_level=definition.risk_level,
                requires_confirmation=False,
                details={"reason": "input_schema_validation_failed"},
            )
            try:
                await self._prepare_execution(
                    definition,
                    execution_id,
                    started_at,
                    raw_input,
                    context,
                    task_id,
                    task_step_id,
                    status="rejected",
                    permission_result=PermissionResult.DENIED,
                )
                await self._finish_rejected(execution_id, started_at, decision, error)
            except ToolPersistenceError:
                logger.exception(
                    "tool_validation_rejection_persistence_failed",
                    extra={
                        "execution_id": execution_id,
                        "correlation_id": context.correlation_id,
                    },
                )
            error.details["execution_id"] = execution_id
            raise error from exc

        serialized_input = validated_input.model_dump(mode="json")
        await self._prepare_execution(
            definition,
            execution_id,
            started_at,
            serialized_input,
            context,
            task_id,
            task_step_id,
            status="validating",
            permission_result=PermissionResult.DENIED,
        )

        decision = await self._safety_policy.evaluate(definition, validated_input)
        if decision.permission_result is not PermissionResult.ALLOWED and (
            decision.permission_result is not PermissionResult.CONFIRMATION_REQUIRED
        ):
            error = self._safety_error(decision)
            await self._finish_rejected(execution_id, started_at, decision, error)
            raise error

        subject = self._confirmation_subject(tool_name, serialized_input, task_id)
        if decision.requires_confirmation:
            if confirmation_token is None:
                token = self._confirmation_service.issue(subject)
                await self._update(
                    execution_id,
                    started_at,
                    decision,
                    status="confirmation_required",
                    validation={"confirmation_required": True},
                )
                raise ToolConfirmationRequiredError(
                    "User confirmation is required before this tool can execute.",
                    details={
                        "execution_id": execution_id,
                        "confirmation_token": token,
                        "risk_level": decision.risk_level.value,
                        "safety": decision.details,
                    },
                )
            if not self._confirmation_service.consume(confirmation_token, subject):
                error = ToolPermissionDeniedError(
                    "The confirmation token is invalid, expired, or already used.",
                    details={"execution_id": execution_id},
                )
                await self._finish_rejected(
                    execution_id,
                    started_at,
                    decision,
                    error,
                    permission_result=PermissionResult.DENIED,
                )
                raise error

        try:
            output = await definition.handler(context, validated_input)
            serialized_output: dict[str, Any] | None = None
            if not isinstance(output, definition.output_type):
                raise TypeError("The tool handler returned an unexpected output type.")
            serialized_output = output.model_dump(mode="json")
            validated_output = definition.output_type.model_validate(serialized_output)
            verified = True
            if isinstance(validated_output, ControlDeviceOutput):
                verified = validated_output.verified
                if not verified:
                    raise ToolStateConflictError(
                        "The device action was not verified against its actual state.",
                        details={"execution_id": execution_id},
                    )
        except ToolError as exc:
            error = self._with_execution_id(exc, execution_id)
            await self._finish_failure(
                execution_id,
                started_at,
                decision,
                error,
                output=serialized_output,
            )
            raise error from exc
        except DeviceError as exc:
            error = self._with_execution_id(self._map_device_error(exc), execution_id)
            await self._finish_failure(execution_id, started_at, decision, error)
            raise error from exc
        except Exception as exc:
            error = self._with_execution_id(
                ToolExecutionFailedError(
                    "The tool execution failed.",
                    details={"execution_id": execution_id},
                ),
                execution_id,
            )
            await self._finish_failure(execution_id, started_at, decision, error)
            raise error from exc

        completed_at = self._clock()
        try:
            await self._update(
                execution_id,
                started_at,
                decision,
                status="completed",
                output=serialized_output,
                validation={"schema_valid": True, "verified": verified},
            )
        except ToolPersistenceError:
            raise

        await self._publish_execution_event(
            execution_id,
            tool_name,
            decision.risk_level,
            verified,
            context.correlation_id,
        )
        logger.info(
            "tool_execution_completed",
            extra={
                "execution_id": execution_id,
                "tool_name": tool_name,
                "risk_level": decision.risk_level.value,
                "permission_result": decision.permission_result.value,
                "verified": verified,
                "correlation_id": context.correlation_id,
                "duration_ms": _duration_ms(started_at, completed_at),
            },
        )
        return ToolExecutionResult(
            execution_id=execution_id,
            tool_name=tool_name,
            status="completed",
            input=serialized_input,
            output=serialized_output,
            verified=verified,
            risk_level=decision.risk_level,
            permission_result=decision.permission_result,
            correlation_id=context.correlation_id,
        )

    async def _prepare_execution(
        self,
        definition: ToolDefinition[Any, Any],
        execution_id: str,
        started_at: datetime,
        serialized_input: dict[str, Any],
        context: ToolExecutionContext,
        task_id: str | None,
        task_step_id: str | None,
        status: str = "validating",
        permission_result: PermissionResult = PermissionResult.DENIED,
    ) -> None:
        try:
            await asyncio.to_thread(
                self._execution_store.register_definition,
                ToolDefinitionRecord(
                    name=definition.name,
                    version=definition.version,
                    description=definition.description,
                    category=definition.category,
                    input_schema=definition.input_type.model_json_schema(),
                    output_schema=definition.output_type.model_json_schema(),
                    risk_level=definition.risk_level.value,
                    default_permission=definition.default_permission.value,
                    requires_confirmation=definition.requires_confirmation,
                    enabled=definition.enabled,
                ),
            )
            await asyncio.to_thread(
                self._execution_store.create_execution,
                ToolExecutionCreate(
                    id=execution_id,
                    tool_name=definition.name,
                    task_id=task_id,
                    task_step_id=task_step_id,
                    status=status,
                    input=serialized_input,
                    risk_level=definition.risk_level.value,
                    permission_result=permission_result.value,
                    correlation_id=context.correlation_id,
                    started_at=started_at,
                ),
            )
        except Exception as exc:
            raise ToolPersistenceError(
                "The tool execution could not be recorded.",
                details={"execution_id": execution_id},
            ) from exc

    async def _finish_rejected(
        self,
        execution_id: str,
        started_at: datetime,
        decision: SafetyDecision,
        error: ToolError,
        *,
        permission_result: PermissionResult | None = None,
    ) -> None:
        try:
            await self._update(
                execution_id,
                started_at,
                decision,
                status="rejected",
                error={
                    "code": error.code,
                    "message": error.message,
                    "safety": decision.details,
                },
                permission_result=permission_result,
            )
        except ToolPersistenceError as persistence_error:
            logger.exception(
                "tool_rejection_persistence_failed",
                extra={"execution_id": execution_id},
            )
            raise persistence_error from error

    async def _finish_failure(
        self,
        execution_id: str,
        started_at: datetime,
        decision: SafetyDecision,
        error: ToolError,
        output: dict[str, Any] | None = None,
    ) -> None:
        try:
            await self._update(
                execution_id,
                started_at,
                decision,
                status="failed",
                error={"code": error.code, "message": error.message, "details": error.details},
                output=output,
                validation=(
                    {"schema_valid": True, "verified": False} if output is not None else None
                ),
            )
        except ToolPersistenceError as persistence_error:
            logger.exception(
                "tool_failure_persistence_failed",
                extra={"execution_id": execution_id},
            )
            raise persistence_error from error

    async def _update(
        self,
        execution_id: str,
        started_at: datetime,
        decision: SafetyDecision,
        *,
        status: str,
        output: dict[str, Any] | None = None,
        validation: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        permission_result: PermissionResult | None = None,
    ) -> datetime:
        completed_at = self._clock()
        try:
            await asyncio.to_thread(
                self._execution_store.update_execution,
                execution_id,
                ToolExecutionUpdate(
                    status=status,
                    output=output,
                    validation=validation,
                    risk_level=decision.risk_level.value,
                    permission_result=(permission_result or decision.permission_result).value,
                    error=error,
                    completed_at=completed_at,
                    duration_ms=_duration_ms(started_at, completed_at),
                ),
            )
        except Exception as exc:
            raise ToolPersistenceError(
                "The tool execution result could not be recorded.",
                details={"execution_id": execution_id},
            ) from exc
        return completed_at

    async def _publish_execution_event(
        self,
        execution_id: str,
        tool_name: str,
        risk_level: ToolRiskLevel,
        verified: bool,
        correlation_id: str,
    ) -> None:
        if self._event_publisher is None:
            return
        event = NovaEvent(
            event_type=NovaEventType.TOOL_EXECUTED,
            source=NovaEventSource.TOOL,
            subject_type="tool_execution",
            subject_id=execution_id,
            payload=ToolExecutedPayload(
                tool_name=tool_name,
                tool_execution_id=execution_id,
                status="success",
                risk_level=risk_level.value,
                verified=verified,
            ),
            correlation_id=correlation_id,
            occurred_at=self._clock(),
        )
        try:
            await self._event_publisher.publish(event)
        except Exception:
            logger.exception(
                "tool_execution_event_publish_failed",
                extra={"execution_id": execution_id, "correlation_id": correlation_id},
            )

    @staticmethod
    def _confirmation_subject(
        tool_name: str,
        serialized_input: dict[str, Any],
        task_id: str | None,
    ) -> ConfirmationSubject:
        canonical_input = _canonical_json(serialized_input)
        fingerprint = hashlib.sha256(canonical_input.encode("utf-8")).hexdigest()
        return ConfirmationSubject(
            tool_name=tool_name,
            input_fingerprint=fingerprint,
            task_id=task_id,
        )

    @staticmethod
    def _safety_error(decision: SafetyDecision) -> ToolError:
        details = {
            "safety": decision.details,
            "risk_level": decision.risk_level.value,
        }
        if decision.permission_result in {
            PermissionResult.DEVICE_UNAVAILABLE,
        }:
            return ToolDeviceUnavailableError(
                "The device is unavailable.",
                details=details,
            )
        if decision.permission_result is PermissionResult.RISK_EXCEEDED:
            return ToolRiskRejectedError(
                "The tool request exceeds the configured risk policy.",
                details=details,
            )
        return ToolPermissionDeniedError(
            "The tool request is not allowed.",
            details=details,
        )

    @staticmethod
    def _map_device_error(exc: DeviceError) -> ToolError:
        if isinstance(exc, DeviceNotFoundError):
            return ToolPermissionDeniedError("The device is not available to Nova.")
        if isinstance(exc, DeviceUnavailableError):
            return ToolDeviceUnavailableError("The device is unavailable.")
        if isinstance(exc, AdapterTimeoutError):
            return ToolAdapterTimeoutError(
                "The device adapter timed out.",
                details={"detail": exc.detail} if exc.detail else {},
            )
        if isinstance(exc, AdapterUnavailableError | AuthorizationError):
            return ToolAdapterError("The device adapter failed.")
        if isinstance(exc, ActionUnsupportedError | InvalidActionParameterError):
            return ToolValidationError("The device rejected the action parameters.")
        if isinstance(exc, DeviceWriteDisabledError):
            return ToolStateConflictError("Device write operations are disabled.")
        if isinstance(exc, StateVerificationFailedError):
            return ToolStateConflictError(
                "The device did not reach its expected state.",
                details={"detail": exc.detail} if exc.detail else {},
            )
        if isinstance(exc, ActionFailedError):
            return ToolExecutionFailedError("The device action failed.")
        return ToolExecutionFailedError("The device action could not be completed.")

    @staticmethod
    def _with_execution_id(error: ToolError, execution_id: str) -> ToolError:
        details = dict(error.details)
        details["execution_id"] = execution_id
        return type(error)(error.message, details=details)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _duration_ms(started_at: datetime, completed_at: datetime) -> int:
    return max(0, int((completed_at - started_at).total_seconds() * 1000))


__all__ = ["ToolEventPublisherProtocol", "ToolExecutor"]
