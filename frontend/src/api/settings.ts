import { requestJson } from "./client";
import type {
  SystemSettings,
  SystemSettingsResponse,
  SystemSettingsUpdateRequest,
} from "@/types/settings";
import { isBoolean, isNumber, isOneOf, isRecord, isString } from "@/utils/validation";

function isSettings(value: unknown): value is SystemSettings {
  return (
    isRecord(value) &&
    isRecord(value.runtime) &&
    isString(value.runtime.app_name) &&
    isString(value.runtime.environment) &&
    isOneOf(value.runtime.ai_provider, ["mock", "openai_compatible"] as const) &&
    isBoolean(value.runtime.home_assistant_configured) &&
    isBoolean(value.runtime.home_assistant_write_enabled) &&
    isNumber(value.runtime.home_assistant_entity_limit) &&
    isNumber(value.runtime.device_poll_interval_seconds) &&
    isNumber(value.runtime.event_retention_days) &&
    isNumber(value.runtime.diagnostic_event_retention_days) &&
    isString(value.runtime.default_environment_name) &&
    isRecord(value.web_console) &&
    isNumber(value.web_console.event_poll_interval_seconds)
  );
}

export function getSettings(): Promise<SystemSettings> {
  return requestJson<SystemSettingsResponse>(
    "/api/settings",
    (value): value is SystemSettingsResponse =>
      isRecord(value) && isRecord(value.data) && isSettings(value.data),
  ).then((response) => response.data);
}

export function updateSettings(request: SystemSettingsUpdateRequest): Promise<SystemSettings> {
  return requestJson<SystemSettingsResponse>(
    "/api/settings",
    (value): value is SystemSettingsResponse =>
      isRecord(value) && isRecord(value.data) && isSettings(value.data),
    { method: "PATCH", body: request },
  ).then((response) => response.data);
}
