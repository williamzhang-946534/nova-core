import { buildQueryString, requestJson } from "./client";
import type { EnvironmentSnapshot, EnvironmentSummaryData } from "@/types/console";
import type { PageResponse } from "@/types/common";
import { isEventSummary } from "./system";
import { isNumber, isRecord, isString, isStringArray } from "@/utils/validation";

function isEnvironment(value: unknown): value is EnvironmentSummaryData["environment"] {
  return (
    isRecord(value) &&
    (value.environment_id === undefined ||
      value.environment_id === null ||
      isString(value.environment_id)) &&
    isString(value.environment_name) &&
    isRecord(value.devices) &&
    isRecord(value.sensors) &&
    isString(value.updated_at)
  );
}

function isAreaSummary(value: unknown): value is EnvironmentSummaryData["areas"][string] {
  return (
    isRecord(value) &&
    isNumber(value.device_count) &&
    isNumber(value.online_device_count) &&
    isStringArray(value.unavailable_device_ids)
  );
}

export function getEnvironment(): Promise<EnvironmentSummaryData> {
  return requestJson<{ data: EnvironmentSummaryData }>(
    "/api/environment",
    (value): value is { data: EnvironmentSummaryData } => {
      return (
        isRecord(value) &&
        isRecord(value.data) &&
        isEnvironment(value.data.environment) &&
        isRecord(value.data.areas) &&
        Object.values(value.data.areas).every(isAreaSummary) &&
        isNumber(value.data.online_device_count) &&
        isStringArray(value.data.unavailable_device_ids) &&
        isNumber(value.data.active_task_count) &&
        Array.isArray(value.data.recent_events) &&
        value.data.recent_events.every(isEventSummary)
      );
    },
  ).then((response) => response.data);
}

function isSnapshot(value: unknown): value is EnvironmentSnapshot {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.environment_id) &&
    isRecord(value.context) &&
    isStringArray(value.active_task_ids) &&
    isNumber(value.anomaly_count) &&
    isString(value.created_at)
  );
}

export function listEnvironmentSnapshots(
  page = 1,
  pageSize = 10,
): Promise<PageResponse<EnvironmentSnapshot>> {
  return requestJson<PageResponse<EnvironmentSnapshot>>(
    `/api/environment/snapshots${buildQueryString({ page, page_size: pageSize })}`,
    (value): value is PageResponse<EnvironmentSnapshot> =>
      isRecord(value) &&
      Array.isArray(value.data) &&
      value.data.every(isSnapshot) &&
      isNumber(value.page) &&
      isNumber(value.page_size) &&
      isNumber(value.total),
  );
}
