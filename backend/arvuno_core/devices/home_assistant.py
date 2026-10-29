import contextlib
import math
from typing import Any

import httpx

from arvuno_core.config import Settings
from arvuno_core.devices.errors import (
    ActionFailedError,
    ActionUnsupportedError,
    AdapterTimeoutError,
    AdapterUnavailableError,
    AuthorizationError,
    DeviceNotFoundError,
    DeviceUnavailableError,
    DeviceWriteDisabledError,
    InvalidActionParameterError,
)
from arvuno_core.devices.interface import DeviceEventSubscriber, SubscriptionHandle
from arvuno_core.devices.models import (
    ActionResult,
    AdapterHealth,
    Device,
    DeviceAction,
    DeviceActionName,
    DeviceCapability,
    DevicePermissions,
    DeviceRiskLevel,
    DeviceState,
    DeviceStateName,
    DeviceType,
)
from arvuno_core.devices.verification import DeviceStateVerifier

_ATTRIBUTE_ALLOWLIST = {
    "area_id",
    "battery",
    "brightness",
    "brightness_pct",
    "current_temperature",
    "device_class",
    "friendly_name",
    "humidity",
    "temperature",
    "unit_of_measurement",
}


class HomeAssistantAdapter:
    """Small REST adapter for explicitly allowlisted Home Assistant entities."""

    adapter_id = "home_assistant"
    version = "1.0.0"

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
        verifier: DeviceStateVerifier | None = None,
    ) -> None:
        self._settings = settings
        self._allowed_ids = set(settings.home_assistant_allowed_entity_ids)
        self._injected_client = client
        self._owned_client: httpx.AsyncClient | None = None
        self._verifier = verifier or DeviceStateVerifier()

    async def health_check(self) -> AdapterHealth:
        if not self._settings.home_assistant_url or not self._settings.home_assistant_token:
            return AdapterHealth(
                status="disconnected",
                adapter_id=self.adapter_id,
                detail="Home Assistant URL or token is not configured.",
            )
        try:
            response = await self._client().get("/api/", headers=self._headers())
        except httpx.TimeoutException:
            return AdapterHealth(
                status="disconnected",
                adapter_id=self.adapter_id,
                detail="Home Assistant health check timed out.",
            )
        except httpx.HTTPError:
            return AdapterHealth(
                status="disconnected",
                adapter_id=self.adapter_id,
                detail="Home Assistant is unreachable.",
            )
        if response.status_code in {401, 403}:
            return AdapterHealth(
                status="disconnected",
                adapter_id=self.adapter_id,
                detail="Home Assistant authorization failed.",
            )
        if response.status_code >= 400:
            return AdapterHealth(
                status="degraded",
                adapter_id=self.adapter_id,
                detail="Home Assistant returned an unexpected health status.",
            )
        return AdapterHealth(
            status="healthy",
            adapter_id=self.adapter_id,
            detail="Home Assistant is reachable.",
        )

    async def get_devices(self) -> list[Device]:
        # Fetch one allowlisted entity at a time so Arvuno never imports the full HA state list.
        return [self._device_from_entity(entity) for entity in await self._entities()]

    async def get_device(self, external_id: str) -> Device:
        return self._device_from_entity(await self._entity(external_id))

    async def get_state(self, external_id: str) -> DeviceState:
        return self._state_from_entity(await self._entity(external_id))

    async def execute_action(self, external_id: str, action: DeviceAction) -> ActionResult:
        entity = await self._entity(external_id)
        device = self._device_from_entity(entity)
        self._validate_action(device, action)
        before = self._state_from_entity(entity)
        if before.state == DeviceStateName.UNAVAILABLE:
            raise DeviceUnavailableError("The device is unavailable.")

        if action.action == DeviceActionName.READ_STATE:
            return self._success(action, external_id, "Device state was read.")

        if not self._settings.home_assistant_write_enabled:
            raise DeviceWriteDisabledError(
                "Real Home Assistant write operations are disabled.",
                detail="Enable ARVUNO_HOME_ASSISTANT_WRITE_ENABLED only in development.",
            )

        domain, service, payload = self._service(action, external_id)
        try:
            response = await self._client().post(
                f"/api/services/{domain}/{service}",
                json=payload,
                headers=self._headers(),
            )
        except httpx.TimeoutException as exc:
            raise AdapterTimeoutError("The Home Assistant action timed out.") from exc
        except httpx.HTTPError as exc:
            raise AdapterUnavailableError("Home Assistant is unreachable.") from exc
        self._raise_for_action_status(response.status_code)

        actual = await self.get_state(external_id)
        self._verifier.verify(action, before, actual)
        return self._success(action, external_id, "The action completed and state was verified.")

    async def subscribe_events(
        self,
        subscriber: DeviceEventSubscriber,
    ) -> SubscriptionHandle:
        raise ActionUnsupportedError(
            "Home Assistant event subscription is not enabled; use DeviceStatePoller.",
        )

    async def close(self) -> None:
        if self._owned_client is not None:
            await self._owned_client.aclose()
            self._owned_client = None

    def _client(self) -> httpx.AsyncClient:
        if self._injected_client is not None:
            return self._injected_client
        if self._owned_client is None:
            self._owned_client = httpx.AsyncClient(
                base_url=str(self._settings.home_assistant_url),
                timeout=self._settings.home_assistant_timeout_seconds,
            )
        return self._owned_client

    def _headers(self) -> dict[str, str]:
        token = self._settings.home_assistant_token
        headers = {"Authorization": f"Bearer {token.get_secret_value() if token else ''}"}
        return headers

    async def _entities(self) -> list[dict[str, Any]]:
        if not self._allowed_ids:
            return []
        return [await self._entity(entity_id) for entity_id in sorted(self._allowed_ids)]

    async def _entity(self, external_id: str) -> dict[str, Any]:
        if external_id not in self._allowed_ids:
            raise DeviceNotFoundError("The entity is outside Arvuno's configured allowlist.")
        if not self._settings.home_assistant_url or not self._settings.home_assistant_token:
            raise AdapterUnavailableError("Home Assistant is not fully configured.")
        try:
            response = await self._client().get(
                f"/api/states/{external_id}",
                headers=self._headers(),
            )
        except httpx.TimeoutException as exc:
            raise AdapterTimeoutError("The Home Assistant state request timed out.") from exc
        except httpx.HTTPError as exc:
            raise AdapterUnavailableError("Home Assistant is unreachable.") from exc
        if response.status_code in {401, 403}:
            raise AuthorizationError("Home Assistant authorization failed.")
        if response.status_code == 404:
            raise DeviceNotFoundError("The Home Assistant entity does not exist.")
        if response.status_code >= 400:
            raise ActionFailedError("Home Assistant returned an unexpected error.")
        entity = response.json()
        if entity.get("entity_id") != external_id:
            raise ActionFailedError("Home Assistant returned a different entity.")
        return entity

    def _device_from_entity(self, entity: dict[str, Any]) -> Device:
        external_id = str(entity["entity_id"])
        attributes = entity.get("attributes") or {}
        device_type = _device_type(external_id, attributes)
        state = _normalize_state(str(entity.get("state", "unknown")), device_type)
        capabilities = _capabilities(device_type)
        return Device(
            external_id=external_id,
            name=str(attributes.get("friendly_name") or external_id),
            device_type=device_type,
            area=_optional_str(attributes.get("area_id") or attributes.get("area")),
            capabilities=capabilities,
            risk_level=DeviceRiskLevel.LOW,
            is_online=state != DeviceStateName.UNAVAILABLE,
            metadata={
                "domain": external_id.split(".", 1)[0],
                "device_class": _optional_str(attributes.get("device_class")),
            },
            permissions=DevicePermissions(
                allowed_actions=[
                    item for capability in capabilities for item in capability.actions
                ],
                max_risk_level=DeviceRiskLevel.LOW,
            ),
        )

    def _state_from_entity(self, entity: dict[str, Any]) -> DeviceState:
        external_id = str(entity["entity_id"])
        attributes = entity.get("attributes") or {}
        raw_state = str(entity.get("state", "unknown"))
        device_type = _device_type(external_id, attributes)
        normalized_attributes = _standard_attributes(raw_state, attributes, device_type)
        return DeviceState(
            external_id=external_id,
            state=_normalize_state(raw_state, device_type),
            attributes=normalized_attributes,
            raw_state=raw_state[:255],
            observed_at=_now(),
        )

    def _validate_action(self, device: Device, action: DeviceAction) -> None:
        if device.device_type == DeviceType.UNKNOWN:
            raise ActionUnsupportedError("Actions are not allowed for unknown device types.")
        if action.action not in device.supported_actions:
            raise ActionUnsupportedError("The device does not support this action.")
        if action.action == DeviceActionName.SET_BRIGHTNESS:
            value = action.parameters.get("brightness_pct")
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
                raise InvalidActionParameterError(
                    "brightness_pct must be an integer from 1 to 100."
                )
        if action.action == DeviceActionName.SET_TEMPERATURE:
            value = action.parameters.get("temperature")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise InvalidActionParameterError("temperature must be a number.")
            if not math.isfinite(float(value)) or not 7 <= float(value) <= 35:
                raise InvalidActionParameterError("temperature must be between 7 and 35.")

    @staticmethod
    def _service(action: DeviceAction, external_id: str) -> tuple[str, str, dict[str, Any]]:
        if action.action in {
            DeviceActionName.TURN_ON,
            DeviceActionName.TURN_OFF,
            DeviceActionName.TOGGLE,
        }:
            return "homeassistant", action.action.value, {"entity_id": external_id}
        if action.action == DeviceActionName.SET_BRIGHTNESS:
            return (
                "light",
                "turn_on",
                {
                    "entity_id": external_id,
                    "brightness_pct": action.parameters["brightness_pct"],
                },
            )
        return (
            "climate",
            "set_temperature",
            {
                "entity_id": external_id,
                "temperature": action.parameters["temperature"],
            },
        )

    @staticmethod
    def _raise_for_action_status(status_code: int) -> None:
        if status_code in {401, 403}:
            raise AuthorizationError("Home Assistant authorization failed.")
        if status_code == 404:
            raise DeviceNotFoundError("The Home Assistant entity does not exist.")
        if status_code >= 400:
            raise ActionFailedError("Home Assistant rejected the action.")

    @staticmethod
    def _success(action: DeviceAction, external_id: str, message: str) -> ActionResult:
        return ActionResult(
            success=True,
            action_id=action.action_id,
            external_id=external_id,
            message=message,
        )


def _now():
    from arvuno_core.devices.models import utc_now

    return utc_now()


def _optional_str(value: object) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _device_type(entity_id: str, attributes: dict[str, Any]) -> DeviceType:
    domain = entity_id.split(".", 1)[0]
    device_class = str(attributes.get("device_class", "")).lower()
    if domain == "light":
        return DeviceType.LIGHT
    if domain == "switch":
        return DeviceType.SWITCH
    if domain == "sensor" and device_class == "temperature":
        return DeviceType.SENSOR_TEMPERATURE
    if domain == "sensor" and device_class == "humidity":
        return DeviceType.SENSOR_HUMIDITY
    if domain == "binary_sensor" and device_class in {"motion", "occupancy", "presence"}:
        return DeviceType.SENSOR_MOTION
    if domain == "binary_sensor" and device_class in {
        "opening",
        "contact",
        "door",
        "window",
        "garage_door",
    }:
        return DeviceType.SENSOR_CONTACT
    if domain == "climate":
        return DeviceType.CLIMATE
    if domain == "media_player":
        return DeviceType.MEDIA_PLAYER
    return DeviceType.UNKNOWN


def _normalize_state(raw_state: str, device_type: DeviceType) -> DeviceStateName:
    value = raw_state.strip().lower()
    if value in {"unavailable", "none"}:
        return DeviceStateName.UNAVAILABLE
    if value == "unknown" or value == "":
        return DeviceStateName.UNKNOWN
    if value in {"on", "open", "detected"}:
        if device_type == DeviceType.SENSOR_CONTACT:
            return DeviceStateName.OPEN
        if device_type == DeviceType.SENSOR_MOTION:
            return (
                DeviceStateName.DETECTED if value in {"on", "detected"} else DeviceStateName.CLEAR
            )
        return DeviceStateName.ON
    if value in {"off", "closed", "clear"}:
        if device_type == DeviceType.SENSOR_CONTACT:
            return DeviceStateName.CLOSED
        if device_type == DeviceType.SENSOR_MOTION:
            return DeviceStateName.CLEAR
        return DeviceStateName.OFF
    if device_type == DeviceType.MEDIA_PLAYER and value == "playing":
        return DeviceStateName.ON
    return DeviceStateName.UNKNOWN


def _standard_attributes(
    raw_state: str,
    attributes: dict[str, Any],
    device_type: DeviceType,
) -> dict[str, Any]:
    result = {
        key: attributes[key]
        for key in _ATTRIBUTE_ALLOWLIST
        if key in attributes and attributes[key] is not None
    }
    if "brightness" in result:
        try:
            result["brightness_pct"] = round(float(result.pop("brightness")) / 255 * 100)
        except (TypeError, ValueError):
            result.pop("brightness", None)
    if device_type == DeviceType.SENSOR_TEMPERATURE and "temperature" not in result:
        with contextlib.suppress(TypeError, ValueError):
            result["temperature"] = float(raw_state)
    if device_type == DeviceType.SENSOR_HUMIDITY and "humidity" not in result:
        with contextlib.suppress(TypeError, ValueError):
            result["humidity"] = float(raw_state)
    return result


def _capabilities(device_type: DeviceType) -> list[DeviceCapability]:
    if device_type == DeviceType.LIGHT:
        return [
            DeviceCapability(
                capability="power",
                actions=[
                    DeviceActionName.TURN_ON,
                    DeviceActionName.TURN_OFF,
                    DeviceActionName.TOGGLE,
                ],
            ),
            DeviceCapability(
                capability="brightness",
                actions=[DeviceActionName.SET_BRIGHTNESS],
                parameters={"brightness_pct": {"type": "integer", "minimum": 1, "maximum": 100}},
            ),
        ]
    if device_type in {DeviceType.SWITCH, DeviceType.MEDIA_PLAYER}:
        return [
            DeviceCapability(
                capability="power",
                actions=[
                    DeviceActionName.TURN_ON,
                    DeviceActionName.TURN_OFF,
                    DeviceActionName.TOGGLE,
                ],
            )
        ]
    if device_type == DeviceType.CLIMATE:
        return [
            DeviceCapability(
                capability="power",
                actions=[DeviceActionName.TURN_ON, DeviceActionName.TURN_OFF],
            ),
            DeviceCapability(
                capability="temperature",
                actions=[DeviceActionName.SET_TEMPERATURE],
                parameters={"temperature": {"type": "number", "minimum": 7, "maximum": 35}},
            ),
        ]
    return [
        DeviceCapability(
            capability="measurement",
            actions=[DeviceActionName.READ_STATE],
            risk_level=DeviceRiskLevel.LOW,
        )
    ]
