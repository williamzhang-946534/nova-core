import asyncio
import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from nova_core.config import Settings
from nova_core.devices.errors import (
    AdapterTimeoutError,
    AuthorizationError,
    DeviceNotFoundError,
    DeviceUnavailableError,
    DeviceWriteDisabledError,
    InvalidActionParameterError,
)
from nova_core.devices.home_assistant import HomeAssistantAdapter
from nova_core.devices.models import DeviceAction, DeviceStateName, DeviceType


def run(coroutine):
    return asyncio.run(coroutine)


def ha_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "home_assistant_url": "https://home-assistant.local",
        "home_assistant_token": SecretStr("local-test-token"),
        "home_assistant_allowed_entity_ids": ["light.living_room"],
        **overrides,
    }
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def entity(
    entity_id: str = "light.living_room",
    state: str = "off",
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "state": state,
        "attributes": attributes
        or {
            "friendly_name": "Living Room Light",
            "area_id": "living_room",
            "device_class": "light",
            "brightness": 51,
        },
        "last_changed": "2026-01-01T00:00:00Z",
        "last_updated": "2026-01-01T00:00:00Z",
        "context": {"id": "not-imported"},
    }


def client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://home-assistant.local",
        transport=httpx.MockTransport(handler),
    )


def test_health_check_and_scoped_state_normalization() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/":
            return httpx.Response(200, json={"message": "API running."})
        if request.url.path == "/api/states/light.living_room":
            return httpx.Response(200, json=entity(state="on", attributes={}))
        if request.url.path == "/api/states":
            raise AssertionError("Nova must not import the full Home Assistant state list")
        return httpx.Response(404)

    async def scenario() -> None:
        http = client(handler)
        adapter = HomeAssistantAdapter(ha_settings(), client=http)
        health = await adapter.health_check()
        devices = await adapter.get_devices()
        state = await adapter.get_state("light.living_room")
        await http.aclose()
        return health, devices, state

    health, devices, state = run(scenario())
    assert health.status == "healthy"
    assert [device.external_id for device in devices] == ["light.living_room"]
    assert devices[0].device_type == DeviceType.LIGHT
    assert state.state == DeviceStateName.ON
    assert requests[0].headers["Authorization"] == "Bearer local-test-token"
    assert all(request.url.path != "/api/states" for request in requests)


def test_empty_allowlist_imports_no_entities() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("No request should be made")

    async def scenario() -> list[Any]:
        http = client(handler)
        adapter = HomeAssistantAdapter(
            ha_settings(home_assistant_allowed_entity_ids=[]),
            client=http,
        )
        devices = await adapter.get_devices()
        await http.aclose()
        return devices

    devices = run(scenario())
    assert devices == []


def test_home_assistant_maps_sensor_and_unavailable_states() -> None:
    entities = {
        "binary_sensor.front_door": entity(
            "binary_sensor.front_door",
            "on",
            {"friendly_name": "Front Door", "device_class": "door"},
        ),
        "sensor.temperature": entity(
            "sensor.temperature",
            "23.5",
            {"friendly_name": "Temperature", "device_class": "temperature"},
        ),
        "light.offline": entity("light.offline", "unavailable", {"friendly_name": "Offline"}),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        entity_id = request.url.path.removeprefix("/api/states/")
        if entity_id in entities:
            return httpx.Response(200, json=entities[entity_id])
        return httpx.Response(404)

    async def scenario() -> list[Any]:
        http = client(handler)
        adapter = HomeAssistantAdapter(
            ha_settings(home_assistant_allowed_entity_ids=list(entities)),
            client=http,
        )
        result = [(await adapter.get_device(key), await adapter.get_state(key)) for key in entities]
        await http.aclose()
        return result

    result = run(scenario())
    assert result[0][0].device_type == DeviceType.SENSOR_CONTACT
    assert result[0][1].state == DeviceStateName.OPEN
    assert result[1][0].device_type == DeviceType.SENSOR_TEMPERATURE
    assert result[1][1].attributes["temperature"] == 23.5
    assert result[2][0].is_online is False
    assert result[2][1].state == DeviceStateName.UNAVAILABLE


def test_home_assistant_write_is_disabled_by_default_and_validated() -> None:
    posted: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posted.append(request)
        return httpx.Response(200, json=entity())

    async def scenario() -> None:
        http = client(handler)
        adapter = HomeAssistantAdapter(ha_settings(), client=http)
        try:
            await adapter.execute_action(
                "light.living_room",
                DeviceAction(action="set_brightness", parameters={"brightness_pct": 0}),
            )
        finally:
            await http.aclose()

    with pytest.raises(InvalidActionParameterError):
        run(scenario())

    async def disabled_write() -> None:
        http = client(handler)
        adapter = HomeAssistantAdapter(ha_settings(), client=http)
        try:
            await adapter.execute_action(
                "light.living_room",
                DeviceAction(action="turn_on"),
            )
        finally:
            await http.aclose()

    with pytest.raises(DeviceWriteDisabledError):
        run(disabled_write())
    assert posted == []


def test_home_assistant_write_uses_adapter_service_mapping_and_verifies_state() -> None:
    current = entity(state="off")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            assert request.url.path == "/api/services/light/turn_on"
            assert json.loads(request.read()) == {
                "entity_id": "light.living_room",
                "brightness_pct": 72,
            }
            current["state"] = "on"
            current["attributes"]["brightness"] = 184
            return httpx.Response(200, json=[{"context": {"id": "ignored"}}])
        return httpx.Response(200, json=current)

    async def scenario() -> Any:
        http = client(handler)
        adapter = HomeAssistantAdapter(
            ha_settings(home_assistant_write_enabled=True),
            client=http,
        )
        result = await adapter.execute_action(
            "light.living_room",
            DeviceAction(action="set_brightness", parameters={"brightness_pct": 72}),
        )
        state = await adapter.get_state("light.living_room")
        await http.aclose()
        return result, state

    result, state = run(scenario())
    assert result.success
    assert state.attributes["brightness_pct"] == 72


def test_home_assistant_authorization_not_found_timeout_and_unavailable_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("Authorization") != "Bearer local-test-token":
            return httpx.Response(401)
        if request.url.path == "/api/states/light.unauthorized":
            return httpx.Response(401)
        if request.url.path == "/api/states/light.denied":
            return httpx.Response(404)
        if request.url.path == "/api/states/light.timeout":
            raise httpx.ConnectTimeout("timed out", request=request)
        return httpx.Response(200, json=entity(state="unavailable"))

    async def scenario() -> None:
        http = client(handler)
        denied_adapter = HomeAssistantAdapter(
            ha_settings(home_assistant_allowed_entity_ids=["light.denied"]),
            client=http,
        )
        unavailable_adapter = HomeAssistantAdapter(
            ha_settings(home_assistant_allowed_entity_ids=["light.living_room"]),
            client=http,
        )
        timeout_adapter = HomeAssistantAdapter(
            ha_settings(home_assistant_allowed_entity_ids=["light.timeout"]),
            client=http,
        )
        unauthorized_adapter = HomeAssistantAdapter(
            ha_settings(home_assistant_allowed_entity_ids=["light.unauthorized"]),
            client=http,
        )
        try:
            await denied_adapter.get_device("light.denied")
        except Exception as exc:
            denied_error = exc
        try:
            await unavailable_adapter.execute_action(
                "light.living_room",
                DeviceAction(action="turn_on"),
            )
        except Exception as exc:
            unavailable_error = exc
        try:
            await timeout_adapter.get_state("light.timeout")
        except Exception as exc:
            timeout_error = exc
        try:
            await unauthorized_adapter.get_state("light.unauthorized")
        except Exception as exc:
            unauthorized_error = exc
        await http.aclose()
        return denied_error, unavailable_error, timeout_error, unauthorized_error

    denied_error, unavailable_error, timeout_error, unauthorized_error = run(scenario())
    assert isinstance(denied_error, DeviceNotFoundError)
    assert isinstance(unavailable_error, DeviceUnavailableError)
    assert isinstance(timeout_error, AdapterTimeoutError)
    assert isinstance(unauthorized_error, AuthorizationError)
    errors = [error for error in locals().values() if isinstance(error, Exception)]
    assert all("local-test-token" not in str(error) for error in errors)


def test_home_assistant_connection_and_authorization_health_errors() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    async def scenario() -> tuple[Any, Any]:
        http = client(handler)
        adapter = HomeAssistantAdapter(ha_settings(), client=http)
        unauthorized = await adapter.health_check()
        await http.aclose()

        unreachable_client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: (_ for _ in ()).throw(
                    httpx.ConnectError("unreachable", request=request)
                )
            )
        )
        unreachable_adapter = HomeAssistantAdapter(ha_settings(), client=unreachable_client)
        disconnected = await unreachable_adapter.health_check()
        await unreachable_client.aclose()
        return unauthorized, disconnected

    unauthorized, disconnected = run(scenario())
    assert unauthorized.status == "disconnected"
    assert disconnected.status == "disconnected"
