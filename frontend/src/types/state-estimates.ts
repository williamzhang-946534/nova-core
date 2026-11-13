import type { JsonRecord } from "./common";

export type StateEstimationStatus =
  "observed" | "derived" | "inferred" | "unknown" | "stale" | "unavailable" | "conflict";

export interface StateEstimate {
  id: string;
  target_id: string;
  environment_id: string;
  target_type: string;
  entity_id?: string | null;
  space_id?: string | null;
  attribute: string;
  status: StateEstimationStatus;
  value?: unknown;
  unit?: string | null;
  confidence?: number | null;
  evidence_summary: JsonRecord;
  conflict_details?: JsonRecord | null;
  rule: { id: string; version: string };
  input_cutoff_at: string;
  effective_from: string;
  generated_at: string;
  valid_until?: string | null;
  superseded_at?: string | null;
  created_at: string;
}

export interface StateEstimateEvidence {
  observation_id: string;
  source_id: string;
  source_type: string;
  entity_id?: string | null;
  space_id?: string | null;
  attribute: string;
  normalized_value?: unknown;
  normalized_unit?: string | null;
  observed_at?: string | null;
  observed_at_source?: string | null;
  received_at: string;
  quality_status: string;
  contribution: string;
  weight?: number | null;
  exclusion_reason?: string | null;
}

export interface StateRebuildResult {
  environment_id: string;
  targets: number;
  appended: number;
  unchanged: number;
  generated_at: string;
}

export interface StateEstimateQuery {
  environmentId?: string;
  targetId?: string;
  entityId?: string;
  spaceId?: string;
  attribute?: string;
  status?: StateEstimationStatus;
  includeHistory?: boolean;
  page?: number;
  pageSize?: number;
}
