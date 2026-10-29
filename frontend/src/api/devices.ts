import { buildQueryString, requestJson } from "./client";
import type {
  Device,
  DeviceCurrentState,
  DeviceDetail,
  DeviceListQuery,
  DeviceListResponse,
  DeviceStateSnapshot,
} from "@/types/console";
import type { PageResponse } from "@/types/common";
import { isEventSummary } from "./system";
import { isBoolean, isNumber, isRecord, isString, isStringArray } from "@/utils/validation";

function isPermission(value: unknown): value is Device["permissions"] {
  return (
    isRecord(value) &&
    isStringArray(value.allowed_actions) &&
    isString(value.max_risk_level) &&
    isBoolean(value.requires_confirmation)
  );
}

function isCapability(value: unknown): value is Device["capabilities"][number] {
  return (
    isRecord(value) &&
    isString(value.capability) &&
    isStringArray(value.actions) &&
    isRecord(value.parameters) &&
    isString(value.risk_level) &&
    isBoolean(value.requires_confirmation)
  );
}

export function isDevice(value: unknown): value is Device {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.adapter_id) &&
    isString(value.external_id) &&
    isString(value.name) &&
    isString(value.device_type) &&
    (value.area === undefined || value.area === null || isString(value.area)) &&
    Array.isArray(value.capabilities) &&
    value.capabilities.every(isCapability) &&
    isString(value.risk_level) &&
    isBoolean(value.is_online) &&
    isBoolean(value.is_enabled) &&
    isRecord(value.metadata) &&
    isStringArray(value.aliases) &&
    isPermission(value.permissions)
  );
}

function isPage<T>(
  value: unknown,
  itemGuard: (item: unknown) => item is T,
): value is PageResponse<T> {
  return (
    isRecord(value) &&
    Array.isArray(value.data) &&
    value.data.every(itemGuard) &&
    isNumber(value.page) &&
    isNumber(value.page_size) &&
    isNumber(value.total)
  );
}

export function listDevices(query: DeviceListQuery = {}): Promise<DeviceListResponse> {
  return requestJson(
    `/api/devices${buildQueryString({ ...query })}`,
    (value): value is DeviceListResponse => isPage(value, isDevice),
  );
}

function isStateSnapshot(value: unknown): value is DeviceStateSnapshot {
  return (
    isRecord(value) &&
    isString(value.device_id) &&
    isString(value.external_id) &&
    isString(value.state) &&
    isRecord(value.attributes) &&
    (value.raw_state === undefined || value.raw_state === null || isString(value.raw_state)) &&
    isString(value.observed_at)
  );
}

export function getDevice(deviceId: string): Promise<DeviceDetail> {
  return requestJson<{ data: DeviceDetail }>(
    `/api/devices/${encodeURIComponent(deviceId)}`,
    (value): value is { data: DeviceDetail } =>
      isRecord(value) &&
      isRecord(value.data) &&
      isRecord(value.data.device) &&
      isDevice(value.data.device) &&
      (value.data.latest_state === undefined ||
        value.data.latest_state === null ||
        isStateSnapshot(value.data.latest_state)) &&
      Array.isArray(value.data.recent_events) &&
      value.data.recent_events.every(isEventSummary),
  ).then((response) => response.data);
}

export function getDeviceState(deviceId: string): Promise<DeviceCurrentState> {
  return requestJson<{ data: DeviceCurrentState }>(
    `/api/devices/${encodeURIComponent(deviceId)}/state`,
    (value): value is { data: DeviceCurrentState } =>
      isRecord(value) &&
      isRecord(value.data) &&
      isString(value.data.device_id) &&
      isString(value.data.external_id) &&
      isString(value.data.state) &&
      isRecord(value.data.attributes) &&
      (value.data.raw_state === undefined ||
        value.data.raw_state === null ||
        isString(value.data.raw_state)) &&
      isString(value.data.observed_at) &&
      isBoolean(value.data.verified) &&
      isBoolean(value.data.from_cache),
  ).then((response) => response.data);
}
