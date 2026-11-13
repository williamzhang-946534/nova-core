import { buildQueryString, requestJson } from "./client";
import type {
  CorrelatedHistory,
  HistoryQuery,
  HistoryQueryResult,
  HistoryRecord,
  HistoryRecordType,
  NaturalHistoryAnswer,
  SnapshotDiffResult,
  SnapshotLookupResult,
  TrendQuery,
  TrendQueryResult,
} from "@/types/history";
import {
  isJsonValue,
  isNumber,
  isNumberOrNull,
  isOneOf,
  isRecord,
  isString,
} from "@/utils/validation";

const recordTypes = ["observation", "event", "task", "snapshot"] as const;

function isHistoryRecord(value: unknown): value is HistoryRecord {
  return (
    isRecord(value) &&
    isOneOf(value.record_type, recordTypes) &&
    isString(value.record_id) &&
    (value.collected_at === null || isString(value.collected_at)) &&
    (value.received_at === null || isString(value.received_at)) &&
    (value.processed_at === null || isString(value.processed_at)) &&
    (value.occurred_at === null || isString(value.occurred_at)) &&
    (value.local_time === null || isString(value.local_time)) &&
    (value.source === null || isString(value.source)) &&
    (value.entity_id === null || isString(value.entity_id)) &&
    (value.space_id === null || isString(value.space_id)) &&
    (value.subject_type === null || isString(value.subject_type)) &&
    (value.subject_id === null || isString(value.subject_id)) &&
    (value.attribute === null || isString(value.attribute)) &&
    isJsonValue(value.value) &&
    (value.unit === null || isString(value.unit)) &&
    (value.quality_status === null || isString(value.quality_status)) &&
    (value.correlation_id === null || isString(value.correlation_id)) &&
    isRecord(value.data)
  );
}

function isHistoryCore(value: unknown): value is Omit<HistoryQueryResult, "counts"> {
  return (
    isRecord(value) &&
    isRecord(value.range) &&
    isString(value.range.start_time) &&
    isString(value.range.end_time) &&
    isString(value.range.local_start_time) &&
    isString(value.range.local_end_time) &&
    isRecord(value.time_semantics) &&
    isString(value.time_semantics.storage_timezone) &&
    isString(value.time_semantics.local_timezone) &&
    isString(value.time_semantics.query_time_basis) &&
    Array.isArray(value.records) &&
    value.records.every(isHistoryRecord) &&
    Array.isArray(value.missing_ranges) &&
    value.missing_ranges.every(
      (gap) =>
        isRecord(gap) &&
        isString(gap.start_time) &&
        isString(gap.end_time) &&
        isNumber(gap.duration_seconds) &&
        isString(gap.reason),
    ) &&
    Array.isArray(value.warnings) &&
    value.warnings.every(isString) &&
    isString(value.generated_at)
  );
}

function isHistoryResult(value: unknown): value is HistoryQueryResult {
  if (!isHistoryCore(value)) {
    return false;
  }
  const result = value as HistoryQueryResult;
  return isRecord(result.counts);
}

function isTrendResult(value: unknown): value is TrendQueryResult {
  if (!isHistoryCore(value)) {
    return false;
  }
  const result = value as unknown as TrendQueryResult;
  return (
    isString(result.attribute) &&
    isOneOf(result.group_by, ["space", "entity"] as const) &&
    Array.isArray(result.statistics) &&
    result.statistics.every(
      (item) =>
        isRecord(item) &&
        isString(item.group_key) &&
        isString(item.label) &&
        isString(item.attribute) &&
        isNumber(item.observation_count) &&
        isNumber(item.valid_count) &&
        isNumber(item.numeric_count),
    )
  );
}

function isSnapshot(value: unknown): boolean {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.environment_id) &&
    isRecord(value.context) &&
    Array.isArray(value.active_task_ids) &&
    value.active_task_ids.every(isString) &&
    isNumber(value.anomaly_count) &&
    isNumber(value.context_version) &&
    isString(value.created_at) &&
    isString(value.local_created_at)
  );
}

export function getHistoryRange(query: HistoryQuery): Promise<HistoryQueryResult> {
  return requestJson<{ data: HistoryQueryResult }>(
    `/api/history/time-range${buildQueryString({
      start_time: query.startTime,
      end_time: query.endTime,
      timezone: query.timezone,
      entity_id: query.entityId,
      space_id: query.spaceId,
      include_descendants: query.includeDescendants,
      attribute: query.attribute,
      quality_status: query.qualityStatus,
      expected_interval_seconds: query.expectedIntervalSeconds,
      limit: query.limit,
    })}`,
    (value): value is { data: HistoryQueryResult } =>
      isRecord(value) && isRecord(value.data) && isHistoryResult(value.data),
  ).then((response) => response.data);
}

export function getHistoryTrends(query: TrendQuery): Promise<TrendQueryResult> {
  return requestJson<{ data: TrendQueryResult }>(
    `/api/history/trends${buildQueryString({
      start_time: query.startTime,
      end_time: query.endTime,
      attribute: query.attribute,
      timezone: query.timezone,
      group_by: query.groupBy,
      space_id: query.spaceId,
      entity_id: query.entityId,
      include_descendants: query.includeDescendants,
      limit: query.limit,
    })}`,
    (value): value is { data: TrendQueryResult } =>
      isRecord(value) && isRecord(value.data) && isTrendResult(value.data),
  ).then((response) => response.data);
}

export function getSnapshotAt(
  atTime: string,
  environmentId?: string,
  nearest = true,
): Promise<SnapshotLookupResult> {
  return requestJson<{ data: SnapshotLookupResult }>(
    `/api/history/environment/snapshot${buildQueryString({
      at_time: atTime,
      environment_id: environmentId,
      nearest,
    })}`,
    (value): value is { data: SnapshotLookupResult } =>
      isRecord(value) &&
      isRecord(value.data) &&
      isString(value.data.requested_at) &&
      isOneOf(value.data.selection, ["at_or_before", "nearest"] as const) &&
      (value.data.snapshot === null || isSnapshot(value.data.snapshot)) &&
      isNumberOrNull(value.data.distance_seconds) &&
      isString(value.data.local_requested_at),
  ).then((response) => response.data);
}

export function diffSnapshots(baselineId: string, targetId: string): Promise<SnapshotDiffResult> {
  return requestJson<{ data: SnapshotDiffResult }>(
    "/api/history/environment/snapshots/diff",
    (value): value is { data: SnapshotDiffResult } =>
      isRecord(value) &&
      isRecord(value.data) &&
      isSnapshot(value.data.baseline) &&
      isSnapshot(value.data.target) &&
      Array.isArray(value.data.changes) &&
      value.data.changes.every(
        (change) =>
          isRecord(change) &&
          isString(change.path) &&
          isOneOf(change.change_type, ["added", "removed", "changed"] as const) &&
          isString(change.recoverability) &&
          isString(change.explanation),
      ) &&
      isNumber(value.data.unchanged_count) &&
      isString(value.data.generated_at),
    { method: "POST", body: { baseline_id: baselineId, target_id: targetId } },
  ).then((response) => response.data);
}

export function getCorrelatedHistory(
  recordType: Exclude<HistoryRecordType, "snapshot">,
  recordId: string,
): Promise<CorrelatedHistory> {
  return requestJson<{ data: CorrelatedHistory }>(
    `/api/history/correlations/${recordType}/${encodeURIComponent(recordId)}`,
    (value): value is { data: CorrelatedHistory } =>
      isRecord(value) &&
      isRecord(value.data) &&
      isHistoryRecord(value.data.record) &&
      Array.isArray(value.data.events) &&
      value.data.events.every(isHistoryRecord) &&
      Array.isArray(value.data.tasks) &&
      value.data.tasks.every(isHistoryRecord) &&
      Array.isArray(value.data.observations) &&
      value.data.observations.every(isHistoryRecord) &&
      Array.isArray(value.data.snapshots) &&
      value.data.snapshots.every(isSnapshot) &&
      isRecord(value.data.relation_basis) &&
      Array.isArray(value.data.warnings) &&
      value.data.warnings.every(isString),
  ).then((response) => response.data);
}

export function askHistory(query: string): Promise<NaturalHistoryAnswer> {
  return requestJson<{ data: NaturalHistoryAnswer }>(
    "/api/history/ask",
    (value): value is { data: NaturalHistoryAnswer } =>
      isRecord(value) &&
      isRecord(value.data) &&
      isString(value.data.query) &&
      isRecord(value.data.interpretation) &&
      isString(value.data.interpretation.question_type) &&
      isNumber(value.data.interpretation.confidence) &&
      isString(value.data.interpretation.explanation) &&
      isString(value.data.answer) &&
      isNumber(value.data.based_on_record_count) &&
      isHistoryCore(value.data),
    { method: "POST", body: { query } },
  ).then((response) => response.data);
}
