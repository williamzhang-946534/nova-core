from pydantic import ValidationError

from arvuno_core.agent_runtime.errors import AgentValidationError
from arvuno_core.agent_runtime.models import (
    AgentToolDescriptor,
    ValidatedToolCall,
)
from arvuno_core.tools.models import ToolPermission
from arvuno_core.tools.registry import ToolDefinition, ToolRegistry


class RegistryToolCatalog:
    """Exposes a handler-free projection and validates model-selected tools."""

    def __init__(self, registry: ToolRegistry, *, permissions: dict[str, str]) -> None:
        self._registry = registry
        self._permissions = dict(permissions)

    async def catalog(self) -> list[AgentToolDescriptor]:
        return [
            _descriptor(item)
            for item in self._registry.catalog(enabled_only=True)
            if self._permission(item["name"], item["risk_level"], item["default_permission"])
            != "deny"
        ]

    async def validate(self, tool_name: str, raw_input: dict[str, object]) -> ValidatedToolCall:
        definition = self._registry.get(tool_name)
        if definition is None or not definition.enabled:
            raise AgentValidationError(
                "The model selected a tool that is not registered or enabled.",
                details={"tool_name": tool_name},
            )
        permission = self._permission(
            definition.name,
            definition.risk_level.value,
            definition.default_permission.value,
        )
        if permission == "deny":
            raise AgentValidationError(
                "The selected tool is disabled by the tool permission policy.",
                details={"tool_name": tool_name},
            )
        try:
            validated = definition.input_type.model_validate(raw_input)
        except ValidationError as exc:
            raise AgentValidationError(
                "The model generated invalid tool parameters.",
                details={
                    "tool_name": tool_name,
                    "errors": exc.errors(include_url=False),
                },
            ) from exc
        descriptor = _descriptor(_catalog_item(definition))
        return ValidatedToolCall(
            tool=descriptor,
            input=validated.model_dump(mode="json"),
        )

    def _permission(
        self,
        name: str,
        risk_level: str,
        default_permission: str,
    ) -> str:
        permission = self._permissions.get(name, default_permission)
        if permission == ToolPermission.ALLOW_READ_ONLY.value and risk_level != "read_only":
            return "deny"
        return permission


def _catalog_item(definition: ToolDefinition[object, object]) -> dict[str, object]:
    return {
        "name": definition.name,
        "version": definition.version,
        "description": definition.description,
        "category": definition.category,
        "input_schema": definition.input_type.model_json_schema(),
        "output_schema": definition.output_type.model_json_schema(),
        "risk_level": definition.risk_level.value,
        "default_permission": definition.default_permission.value,
        "requires_confirmation": definition.requires_confirmation,
        "enabled": definition.enabled,
    }


def _descriptor(item: dict[str, object]) -> AgentToolDescriptor:
    return AgentToolDescriptor.model_validate(item)


__all__ = ["RegistryToolCatalog"]
