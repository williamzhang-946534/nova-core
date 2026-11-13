import { buildQueryString, requestJson } from "./client";
import type { PageResponse } from "@/types/common";
import type {
  StateEstimate,
  StateEstimateEvidence,
  StateEstimateQuery,
  StateRebuildResult,
} from "@/types/state-estimates";
import {
  isJsonValue,
  isNumber,
  isNumberOrNull,
  isOneOf,
  isRecord,
  isRecordOrNull,
  isString,
  isStringOrNull,
} from "@/utils/validation";

const statuses = [
  "observed",
  "derived",
  "inferred",
  "unknown",
  "stale",
  "unavailable",
  "conflict",
] as const;

function isStateEstimate(value: unknown): value is StateEstimate {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.target_id) &&
    isString(value.environment_id) &&
    isString(value.target_type) &&
    isStringOrNull(value.entity_id) &&
    isStringOrNull(value.space_id) &&
    isString(value.attribute) &&
    isOneOf(value.status, statuses) &&
    isJsonValue(value.value) &&
    isStringOrNull(value.unit) &&
    isNumberOrNull(value.confidence) &&
    isRecord(value.evidence_summary) &&
    isRecordOrNull(value.conflict_details) &&
    isRecord(value.rule) &&
    isString(value.rule.id) &&
    isString(value.rule.version) &&
    isString(value.input_cutoff_at) &&
    isString(value.effective_from) &&
    isString(value.generated_at) &&
    isStringOrNull(value.valid_until) &&
    isStringOrNull(value.superseded_at) &&
    isString(value.created_at)
  );
}

function isEvidence(value: unknown): value is StateEstimateEvidence {
  return (
    isRecord(value) &&
    isString(value.observation_id) &&
    isString(value.source_id) &&
    isString(value.source_type) &&
    isStringOrNull(value.entity_id) &&
    isStringOrNull(value.space_id) &&
    isString(value.attribute) &&
    isJsonValue(value.normalized_value) &&
    isStringOrNull(value.normalized_unit) &&
    isStringOrNull(value.observed_at) &&
    isStringOrNull(value.observed_at_source) &&
    isString(value.received_at) &&
    isString(value.quality_status) &&
    isString(value.contribution) &&
    isNumberOrNull(value.weight) &&
    isStringOrNull(value.exclusion_reason)
  );
}

function isPage(value: unknown): value is PageResponse<StateEstimate> {
  return (
    isRecord(value) &&
    Array.isArray(value.data) &&
    value.data.every(isStateEstimate) &&
    isNumber(value.page) &&
    isNumber(value.page_size) &&
    isNumber(value.total)
  );
}

export function listStateEstimates(
  query: StateEstimateQuery = {},
): Promise<PageResponse<StateEstimate>> {
  return requestJson<PageResponse<StateEstimate>>(
    `/api/state-estimates${buildQueryString({
      environment_id: query.environmentId,
      target_id: query.targetId,
      entity_id: query.entityId,
      space_id: query.spaceId,
      attribute: query.attribute,
      status: query.status,
      include_history: query.includeHistory,
      page: query.page,
      page_size: query.pageSize,
    })}`,
    isPage,
  );
}

export function getStateEstimateEvidence(estimateId: string): Promise<StateEstimateEvidence[]> {
  return requestJson<{ data: StateEstimateEvidence[] }>(
    `/api/state-estimates/${encodeURIComponent(estimateId)}/evidence`,
    (value): value is { data: StateEstimateEvidence[] } =>
      isRecord(value) && Array.isArray(value.data) && value.data.every(isEvidence),
  ).then((response) => response.data);
}

export function rebuildStateEstimates(): Promise<StateRebuildResult> {
  return requestJson<{ data: StateRebuildResult }>(
    "/api/state-estimates/rebuild",
    (value): value is { data: StateRebuildResult } =>
      isRecord(value) &&
      isRecord(value.data) &&
      isString(value.data.environment_id) &&
      isNumber(value.data.targets) &&
      isNumber(value.data.appended) &&
      isNumber(value.data.unchanged) &&
      isString(value.data.generated_at),
    { method: "POST" },
  ).then((response) => response.data);
}
