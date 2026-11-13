import { buildQueryString, requestJson } from "./client";
import {
  isBoolean,
  isNumber,
  isNumberOrNull,
  isRecord,
  isRecordOrNull,
  isString,
  isStringOrNull,
} from "@/utils/validation";
import type {
  Robot,
  RobotCapability,
  RobotCapabilityName,
  RobotConsent,
  RobotConsentGrantInput,
  RobotEvent,
  RobotRuntimeStatus,
  RobotTaskRequest,
} from "@/types/robots";

const robotDataCategories = ["camera", "microphone", "speaker", "motion"] as const;

function isDataCategory(value: unknown): value is RobotConsent["data_category"] {
  return isString(value) && robotDataCategories.includes(value as RobotConsent["data_category"]);
}

function isRobot(value: unknown): value is Robot {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.adapter_id) &&
    isString(value.external_id) &&
    isString(value.name) &&
    isStringOrNull(value.profile) &&
    isBoolean(value.is_enabled) &&
    isString(value.connection_state) &&
    isBoolean(value.is_online) &&
    isString(value.motion_safety_state) &&
    isBoolean(value.emergency_stop) &&
    isBoolean(value.manual_takeover) &&
    isNumberOrNull(value.battery_percent) &&
    isRecord(value.device_states) &&
    isStringOrNull(value.space_id) &&
    isStringOrNull(value.last_seen_at) &&
    isString(value.created_at) &&
    isString(value.updated_at)
  );
}

function isCapability(value: unknown): value is RobotCapability {
  return (
    isRecord(value) &&
    isStringOrNull(value.robot_id) &&
    isString(value.capability) &&
    isBoolean(value.discovered) &&
    isBoolean(value.supported) &&
    isBoolean(value.enabled) &&
    isBoolean(value.approved) &&
    isBoolean(value.consent_granted) &&
    isBoolean(value.executable) &&
    isBoolean(value.runtime_enabled) &&
    isString(value.risk_level) &&
    isBoolean(value.requires_confirmation) &&
    Array.isArray(value.requires_consents) &&
    value.requires_consents.every(isDataCategory)
  );
}

function isConsent(value: unknown): value is RobotConsent {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.robot_id) &&
    isString(value.capability) &&
    isDataCategory(value.data_category) &&
    isStringOrNull(value.space_id) &&
    isString(value.status) &&
    isString(value.granted_at) &&
    isStringOrNull(value.expires_at) &&
    isStringOrNull(value.revoked_at) &&
    isString(value.grant_source) &&
    isString(value.granted_by)
  );
}

function isRuntimeStatus(value: unknown): value is RobotRuntimeStatus {
  return (
    isRecord(value) &&
    isString(value.robot_id) &&
    isString(value.state) &&
    isString(value.connection_state) &&
    isString(value.motion_safety_state) &&
    isBoolean(value.is_fresh) &&
    isStringOrNull(value.last_seen_at) &&
    isString(value.last_evaluated_at) &&
    isNumber(value.heartbeat_timeout_seconds) &&
    isNumber(value.active_task_count) &&
    isStringOrNull(value.error_code)
  );
}

function isEvent(value: unknown): value is RobotEvent {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.robot_id) &&
    isStringOrNull(value.task_request_id) &&
    isString(value.event_type) &&
    isString(value.severity) &&
    isString(value.source) &&
    isRecord(value.payload) &&
    isString(value.occurred_at) &&
    isString(value.received_at) &&
    isBoolean(value.late_arrival) &&
    isStringOrNull(value.correlation_id)
  );
}

function isTaskRequest(value: unknown): value is RobotTaskRequest {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.robot_id) &&
    isString(value.capability) &&
    isString(value.status) &&
    isRecord(value.parameters) &&
    isString(value.requested_by) &&
    isString(value.origin_type) &&
    isStringOrNull(value.task_id) &&
    isStringOrNull(value.task_step_id) &&
    isStringOrNull(value.tool_execution_id) &&
    isStringOrNull(value.idempotency_key) &&
    isBoolean(value.confirmed_by_user) &&
    isBoolean(value.requires_confirmation) &&
    isRecordOrNull(value.result) &&
    isRecordOrNull(value.error) &&
    isNumber(value.timeout_seconds) &&
    isStringOrNull(value.correlation_id) &&
    isString(value.created_at) &&
    isStringOrNull(value.submitted_at) &&
    isStringOrNull(value.completed_at) &&
    isString(value.updated_at)
  );
}

function isEnvelope<T>(
  value: unknown,
  itemGuard: (item: unknown) => item is T,
): value is { data: T } {
  return isRecord(value) && itemGuard(value.data);
}

export function listRobots(enabledOnly = false): Promise<Robot[]> {
  return requestJson<{ data: Robot }[]>(
    `/api/robots${buildQueryString({ enabled_only: enabledOnly || undefined })}`,
    (value): value is { data: Robot }[] =>
      Array.isArray(value) && value.every((item) => isEnvelope(item, isRobot)),
  ).then((value) => value.map((item) => item.data));
}

export function getRobot(robotId: string): Promise<Robot> {
  return requestJson<{ data: Robot }>(
    `/api/robots/${encodeURIComponent(robotId)}`,
    (value): value is { data: Robot } => isEnvelope(value, isRobot),
  ).then((value) => value.data);
}

export function listCapabilities(robotId: string): Promise<RobotCapability[]> {
  return requestJson<{ data: RobotCapability[] }>(
    `/api/robots/${encodeURIComponent(robotId)}/capabilities`,
    (value): value is { data: RobotCapability[] } =>
      isRecord(value) && Array.isArray(value.data) && value.data.every(isCapability),
  ).then((value) => value.data);
}

export function setCapabilityGovernance(
  robotId: string,
  capability: RobotCapabilityName,
  enabled: boolean,
): Promise<RobotCapability[]> {
  return requestJson<{ data: RobotCapability[] }>(
    `/api/robots/${encodeURIComponent(robotId)}/capabilities/${encodeURIComponent(capability)}/governance`,
    (value): value is { data: RobotCapability[] } =>
      isRecord(value) && Array.isArray(value.data) && value.data.every(isCapability),
    { method: "POST", body: { enabled } },
  ).then((value) => value.data);
}

export function listConsents(robotId: string, activeOnly = false): Promise<RobotConsent[]> {
  return requestJson<RobotConsent[]>(
    `/api/robots/${encodeURIComponent(robotId)}/consents${buildQueryString({ active_only: activeOnly || undefined })}`,
    (value): value is RobotConsent[] => Array.isArray(value) && value.every(isConsent),
  );
}

export function grantConsent(
  robotId: string,
  grant: RobotConsentGrantInput,
): Promise<RobotConsent> {
  return requestJson<RobotConsent>(
    `/api/robots/${encodeURIComponent(robotId)}/consents`,
    isConsent,
    { method: "POST", body: grant },
  );
}

export function revokeConsent(robotId: string, consentId: string): Promise<RobotConsent> {
  return requestJson<RobotConsent>(
    `/api/robots/${encodeURIComponent(robotId)}/consents/${encodeURIComponent(consentId)}/revoke`,
    isConsent,
    {
      method: "POST",
      body: { revoked_by: "web-console-user" },
    },
  );
}

export function getRuntimeStatus(robotId: string): Promise<RobotRuntimeStatus> {
  return requestJson<{ data: RobotRuntimeStatus }>(
    `/api/robots/${encodeURIComponent(robotId)}/runtime-state`,
    (value): value is { data: RobotRuntimeStatus } => isEnvelope(value, isRuntimeStatus),
  ).then((value) => value.data);
}

export function listRobotEvents(robotId: string, limit = 100): Promise<RobotEvent[]> {
  return requestJson<RobotEvent[]>(
    `/api/robots/${encodeURIComponent(robotId)}/events${buildQueryString({ limit })}`,
    (value): value is RobotEvent[] => Array.isArray(value) && value.every(isEvent),
  );
}

export function listRobotTaskRequests(robotId: string, limit = 100): Promise<RobotTaskRequest[]> {
  return requestJson<{ data: RobotTaskRequest }[]>(
    `/api/robots/${encodeURIComponent(robotId)}/task-requests${buildQueryString({ limit })}`,
    (value): value is { data: RobotTaskRequest }[] =>
      Array.isArray(value) && value.every((item) => isEnvelope(item, isTaskRequest)),
  ).then((value) => value.map((item) => item.data));
}
