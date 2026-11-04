import type { JsonRecord, JsonValue } from "./common";

export type ObservationQualityStatus = "pending" | "valid" | "warning" | "invalid";

export interface ObservationItem {
  observation_id: string;
  source_id: string;
  source_type: string;
  entity_id: string | null;
  subject_type: string | null;
  subject_id: string | null;
  space_id: string | null;
  attribute: string;
  raw_value: JsonValue;
  raw_unit: string | null;
  normalized_value: JsonValue;
  normalized_unit: string | null;
  value_type: string;
  observed_at: string | null;
  observed_at_source: string | null;
  observed_at_uncertainty_ms: number | null;
  received_at: string;
  processed_at: string | null;
  quality_status: ObservationQualityStatus;
  quality_issues: JsonRecord[];
  valid_from: string | null;
  valid_until: string | null;
  freshness_policy: string | null;
  freshness_evaluated_at: string | null;
  correlation_id: string | null;
  external_id: string | null;
  dedupe_key: string;
  payload_hash: string;
  normalization_rule_version: string | null;
  retention_class: string;
  retention_until: string | null;
  created_at: string | null;
}
