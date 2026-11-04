import { buildQueryString, requestJson } from "./client";
import type { PageResponse } from "@/types/common";
import type { ObservationItem, ObservationQualityStatus } from "@/types/observations";
import {
  isJsonValue,
  isNumber,
  isOneOf,
  isRecord,
  isString,
  isStringOrNull,
} from "@/utils/validation";

const qualityStatuses = ["pending", "valid", "warning", "invalid"] as const;

function isObservation(value: unknown): value is ObservationItem {
  return (
    isRecord(value) &&
    isString(value.observation_id) &&
    isString(value.source_id) &&
    isString(value.source_type) &&
    isStringOrNull(value.entity_id) &&
    isStringOrNull(value.subject_type) &&
    isStringOrNull(value.subject_id) &&
    isStringOrNull(value.space_id) &&
    isString(value.attribute) &&
    isJsonValue(value.raw_value) &&
    isStringOrNull(value.raw_unit) &&
    isJsonValue(value.normalized_value) &&
    isStringOrNull(value.normalized_unit) &&
    isString(value.value_type) &&
    isStringOrNull(value.observed_at) &&
    isStringOrNull(value.observed_at_source) &&
    (value.observed_at_uncertainty_ms === null || isNumber(value.observed_at_uncertainty_ms)) &&
    isString(value.received_at) &&
    isStringOrNull(value.processed_at) &&
    isOneOf(value.quality_status, qualityStatuses) &&
    Array.isArray(value.quality_issues) &&
    isStringOrNull(value.valid_from) &&
    isStringOrNull(value.valid_until) &&
    isStringOrNull(value.freshness_policy) &&
    isStringOrNull(value.freshness_evaluated_at) &&
    isStringOrNull(value.correlation_id) &&
    isStringOrNull(value.external_id) &&
    isString(value.dedupe_key) &&
    isString(value.payload_hash) &&
    isStringOrNull(value.normalization_rule_version) &&
    isString(value.retention_class) &&
    isStringOrNull(value.retention_until) &&
    isStringOrNull(value.created_at)
  );
}

export interface ObservationQuery {
  spaceId?: string;
  includeDescendants?: boolean;
  attribute?: string;
  qualityStatus?: ObservationQualityStatus;
  page?: number;
  pageSize?: number;
}

export function listObservations(
  query: ObservationQuery = {},
): Promise<PageResponse<ObservationItem>> {
  return requestJson<PageResponse<ObservationItem>>(
    `/api/observations${buildQueryString({
      space_id: query.spaceId,
      include_descendants: query.includeDescendants,
      attribute: query.attribute,
      quality_status: query.qualityStatus,
      page: query.page,
      page_size: query.pageSize,
    })}`,
    (value): value is PageResponse<ObservationItem> =>
      isRecord(value) &&
      Array.isArray(value.data) &&
      value.data.every(isObservation) &&
      isNumber(value.page) &&
      isNumber(value.page_size) &&
      isNumber(value.total),
  );
}
