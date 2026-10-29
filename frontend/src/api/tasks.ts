import { buildQueryString, requestJson } from "./client";
import type { TaskDetail, TaskListQuery, TaskListResponse, TaskStatus } from "@/types/tasks";
import { isNumber, isRecord, isRecordOrNull, isString } from "@/utils/validation";

const taskStatuses = [
  "pending",
  "planning",
  "waiting_confirmation",
  "running",
  "completed",
  "failed",
  "cancelled",
] as const satisfies readonly TaskStatus[];

const stepStatuses = [
  "pending",
  "running",
  "waiting_confirmation",
  "completed",
  "failed",
  "timed_out",
  "cancelled",
] as const;

function isTaskStatus(value: unknown): value is TaskStatus {
  return isString(value) && taskStatuses.includes(value as TaskStatus);
}

function isTask(value: unknown): value is TaskListResponse["data"][number] {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.task_type) &&
    isString(value.title) &&
    (value.description === undefined ||
      value.description === null ||
      isString(value.description)) &&
    isTaskStatus(value.status) &&
    isString(value.origin) &&
    (value.conversation_id === undefined ||
      value.conversation_id === null ||
      isString(value.conversation_id)) &&
    isRecord(value.plan) &&
    isRecordOrNull(value.result) &&
    isRecordOrNull(value.error) &&
    (value.correlation_id === undefined ||
      value.correlation_id === null ||
      isString(value.correlation_id)) &&
    isString(value.created_at) &&
    (value.started_at === undefined || value.started_at === null || isString(value.started_at)) &&
    (value.completed_at === undefined ||
      value.completed_at === null ||
      isString(value.completed_at))
  );
}

export function listTasks(query: TaskListQuery = {}): Promise<TaskListResponse> {
  return requestJson(
    `/api/tasks${buildQueryString({ ...query })}`,
    (value): value is TaskListResponse =>
      isRecord(value) &&
      Array.isArray(value.data) &&
      value.data.every(isTask) &&
      isNumber(value.page) &&
      isNumber(value.page_size) &&
      isNumber(value.total),
  );
}

function isStep(value: unknown): value is TaskDetail["steps"][number] {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.task_id) &&
    isNumber(value.step_index) &&
    isString(value.name) &&
    (value.description === undefined ||
      value.description === null ||
      isString(value.description)) &&
    (value.tool_name === undefined || value.tool_name === null || isString(value.tool_name)) &&
    isString(value.status) &&
    stepStatuses.includes(value.status as (typeof stepStatuses)[number]) &&
    isRecordOrNull(value.input) &&
    isRecordOrNull(value.output) &&
    isRecordOrNull(value.error) &&
    (value.started_at === undefined || value.started_at === null || isString(value.started_at)) &&
    (value.completed_at === undefined ||
      value.completed_at === null ||
      isString(value.completed_at))
  );
}

function isExecution(value: unknown): value is TaskDetail["executions"][number] {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.tool_name) &&
    (value.task_id === undefined || value.task_id === null || isString(value.task_id)) &&
    (value.task_step_id === undefined ||
      value.task_step_id === null ||
      isString(value.task_step_id)) &&
    isString(value.status) &&
    isRecord(value.input) &&
    isRecordOrNull(value.output) &&
    isRecordOrNull(value.validation) &&
    isString(value.risk_level) &&
    isString(value.permission_result) &&
    isRecordOrNull(value.error) &&
    (value.correlation_id === undefined ||
      value.correlation_id === null ||
      isString(value.correlation_id)) &&
    isString(value.started_at) &&
    (value.completed_at === null ||
      value.completed_at === undefined ||
      isString(value.completed_at)) &&
    (value.duration_ms === null || value.duration_ms === undefined || isNumber(value.duration_ms))
  );
}

export function getTask(taskId: string): Promise<TaskDetail> {
  return requestJson<{ data: TaskDetail }>(
    `/api/tasks/${encodeURIComponent(taskId)}`,
    (value): value is { data: TaskDetail } =>
      isRecord(value) &&
      isRecord(value.data) &&
      isTask(value.data) &&
      Array.isArray(value.data.steps) &&
      value.data.steps.every(isStep) &&
      Array.isArray(value.data.executions) &&
      value.data.executions.every(isExecution),
  ).then((response) => response.data);
}

export function confirmTask(taskId: string, token: string, confirmed: boolean) {
  return requestJson<{ data: TaskDetail }>(
    `/api/tasks/${encodeURIComponent(taskId)}/confirm`,
    (value): value is { data: TaskDetail } =>
      isRecord(value) && isRecord(value.data) && isTask(value.data),
    {
      method: "POST",
      body: { confirmed, confirmation_token: token },
    },
  ).then((response) => response.data);
}

export function cancelTask(taskId: string, reason = "Cancelled from Arvuno Web Console.") {
  return requestJson<{ data: TaskDetail }>(
    `/api/tasks/${encodeURIComponent(taskId)}/cancel`,
    (value): value is { data: TaskDetail } =>
      isRecord(value) && isRecord(value.data) && isTask(value.data),
    { method: "POST", body: { reason } },
  ).then((response) => response.data);
}
