import { buildQueryString, requestJson } from "./client";
import {
  type Automation,
  type AutomationAction,
  type AutomationEventType,
  type AutomationListQuery,
  type AutomationListResponse,
  type AutomationRun,
  type AutomationRunListQuery,
  type AutomationRunListResponse,
  type AutomationRunStatus,
  type AutomationTrigger,
  type AutomationUpdate,
  type ConsoleNotification,
  type NotificationLevel,
  type NotificationListQuery,
  type NotificationListResponse,
  type NotificationStatus,
} from "@/types/automations";
import {
  isBoolean,
  isNumber,
  isOneOf,
  isRecord,
  isRecordOrNull,
  isString,
  isStringOrNull,
} from "@/utils/validation";

const automationEventTypes = [
  "device_state_changed",
  "sensor_updated",
  "device_unavailable",
] as const satisfies readonly AutomationEventType[];

const conditionOperators = ["eq", "ne", "gt", "gte", "lt", "lte", "contains", "in"] as const;

const runStatuses = [
  "running",
  "completed",
  "failed",
  "cooldown_skipped",
  "condition_not_met",
  "risk_rejected",
] as const satisfies readonly AutomationRunStatus[];

const notificationLevels = [
  "info",
  "warning",
  "error",
] as const satisfies readonly NotificationLevel[];
const notificationStatuses = ["sent", "read"] as const satisfies readonly NotificationStatus[];

function isPageResponse<T>(
  value: unknown,
  itemGuard: (item: unknown) => item is T,
): value is { data: T[]; page: number; page_size: number; total: number } {
  return (
    isRecord(value) &&
    Array.isArray(value.data) &&
    value.data.every(itemGuard) &&
    isNumber(value.page) &&
    isNumber(value.page_size) &&
    isNumber(value.total)
  );
}

function isTrigger(value: unknown): value is AutomationTrigger {
  return (
    isRecord(value) &&
    isOneOf(value.event_type, automationEventTypes) &&
    isStringOrNull(value.subject_id)
  );
}

function isAction(value: unknown): value is AutomationAction {
  if (!isRecord(value) || !isString(value.type)) {
    return false;
  }
  if (value.type === "notification") {
    return (
      isString(value.title) && isString(value.message) && isOneOf(value.level, notificationLevels)
    );
  }
  if (value.type === "tool") {
    return (
      isString(value.tool_name) &&
      isRecord(value.input) &&
      isString(value.title) &&
      isOneOf(value.risk_level, ["read_only", "low_risk", "medium_risk", "high_risk"] as const)
    );
  }
  return false;
}

function isAutomation(value: unknown): value is Automation {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.name) &&
    isStringOrNull(value.description) &&
    isBoolean(value.enabled) &&
    isTrigger(value.trigger) &&
    Array.isArray(value.conditions) &&
    value.conditions.every(
      (condition) =>
        isRecord(condition) &&
        isString(condition.field) &&
        isOneOf(condition.operator, conditionOperators),
    ) &&
    isAction(value.action) &&
    isNumber(value.cooldown_seconds) &&
    isString(value.risk_level) &&
    isString(value.created_at) &&
    isString(value.updated_at)
  );
}

function isAutomationRun(value: unknown): value is AutomationRun {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.automation_id) &&
    isStringOrNull(value.event_id) &&
    isOneOf(value.status, runStatuses) &&
    isRecord(value.matched_context) &&
    isStringOrNull(value.task_id) &&
    isStringOrNull(value.notification_id) &&
    isRecordOrNull(value.error) &&
    isString(value.started_at) &&
    isStringOrNull(value.completed_at)
  );
}

function isNotification(value: unknown): value is ConsoleNotification {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.channel) &&
    isString(value.title) &&
    isString(value.content) &&
    isOneOf(value.level, notificationLevels) &&
    isOneOf(value.status, notificationStatuses) &&
    isStringOrNull(value.related_event_id) &&
    isStringOrNull(value.related_task_id) &&
    isString(value.created_at) &&
    isStringOrNull(value.sent_at)
  );
}

export function listAutomations(query: AutomationListQuery = {}) {
  return requestJson<AutomationListResponse>(
    `/api/automations${buildQueryString({ ...query })}`,
    (value): value is AutomationListResponse => isPageResponse<Automation>(value, isAutomation),
  );
}

export function getAutomation(automationId: string) {
  return requestJson<{ data: Automation }>(
    `/api/automations/${encodeURIComponent(automationId)}`,
    (value): value is { data: Automation } =>
      isRecord(value) && isRecord(value.data) && isAutomation(value.data),
  ).then((response) => response.data);
}

export function updateAutomation(automationId: string, changes: AutomationUpdate) {
  return requestJson<{ data: Automation }>(
    `/api/automations/${encodeURIComponent(automationId)}`,
    (value): value is { data: Automation } =>
      isRecord(value) && isRecord(value.data) && isAutomation(value.data),
    {
      method: "PATCH",
      body: changes,
    },
  ).then((response) => response.data);
}

export function setAutomationEnabled(automationId: string, enabled: boolean) {
  return requestJson<{ data: Automation }>(
    `/api/automations/${encodeURIComponent(automationId)}/${enabled ? "enable" : "disable"}`,
    (value): value is { data: Automation } =>
      isRecord(value) && isRecord(value.data) && isAutomation(value.data),
    { method: "POST" },
  ).then((response) => response.data);
}

export function listAutomationRuns(automationId: string, query: AutomationRunListQuery = {}) {
  return requestJson<AutomationRunListResponse>(
    `/api/automations/${encodeURIComponent(automationId)}/runs${buildQueryString({
      ...query,
    })}`,
    (value): value is AutomationRunListResponse =>
      isPageResponse<AutomationRun>(value, isAutomationRun),
  );
}

export function listNotifications(query: NotificationListQuery = {}) {
  return requestJson<NotificationListResponse>(
    `/api/notifications${buildQueryString({ ...query })}`,
    (value): value is NotificationListResponse =>
      isPageResponse<ConsoleNotification>(value, isNotification),
  );
}

export function markNotificationRead(notificationId: string) {
  return requestJson<{ data: ConsoleNotification }>(
    `/api/notifications/${encodeURIComponent(notificationId)}/read`,
    (value): value is { data: ConsoleNotification } =>
      isRecord(value) && isRecord(value.data) && isNotification(value.data),
    { method: "POST" },
  ).then((response) => response.data);
}
