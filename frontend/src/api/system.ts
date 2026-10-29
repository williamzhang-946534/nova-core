import { requestJson } from "./client";
import type { EventSummary, SystemStatus } from "@/types/console";
import { isNumber, isOneOf, isRecord, isString } from "@/utils/validation";

const adapterStatuses = ["healthy", "degraded", "disconnected"] as const;

function isAdapterHealth(value: unknown): value is SystemStatus["adapters"][number] {
  return (
    isRecord(value) &&
    isOneOf(value.status, adapterStatuses) &&
    isString(value.adapter_id) &&
    isString(value.detail) &&
    isString(value.checked_at)
  );
}

function isEventSummary(value: unknown): value is EventSummary {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.event_type) &&
    isString(value.source) &&
    (value.subject_type === undefined ||
      value.subject_type === null ||
      isString(value.subject_type)) &&
    (value.subject_id === undefined || value.subject_id === null || isString(value.subject_id)) &&
    isRecord(value.payload) &&
    (value.correlation_id === undefined ||
      value.correlation_id === null ||
      isString(value.correlation_id)) &&
    isString(value.occurred_at) &&
    isString(value.created_at)
  );
}

function isSystemStatus(value: unknown): value is SystemStatus {
  return (
    isRecord(value) &&
    isString(value.version) &&
    isString(value.environment) &&
    isOneOf(value.database, ["ok", "error"] as const) &&
    Array.isArray(value.adapters) &&
    value.adapters.every(isAdapterHealth) &&
    isNumber(value.device_count) &&
    isNumber(value.online_device_count) &&
    isNumber(value.active_task_count) &&
    Array.isArray(value.recent_error_events) &&
    value.recent_error_events.every(isEventSummary) &&
    isString(value.checked_at)
  );
}

export { isEventSummary };

export function getSystemStatus(): Promise<SystemStatus> {
  return requestJson<{ data: SystemStatus }>(
    "/api/system/status",
    (
      value,
    ): value is {
      data: SystemStatus;
    } => {
      return isRecord(value) && isRecord(value.data) && isSystemStatus(value.data);
    },
  ).then((response) => response.data);
}
