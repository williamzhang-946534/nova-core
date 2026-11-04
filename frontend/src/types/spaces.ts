import type { JsonRecord, JsonValue } from "./common";

export type SpaceType = "home" | "floor" | "room" | "zone";
export type SpaceStatus = "active" | "inactive" | "archived";
export type AssignmentType =
  "fixed_installation" | "current_placement" | "observed_presence" | "user_asserted";

export interface Space {
  id: string;
  parent_id: string | null;
  space_type: SpaceType;
  name: string;
  normalized_name: string;
  slug: string;
  path: string;
  sort_order: number;
  external_space_id: string | null;
  external_source: string | null;
  status: SpaceStatus;
  geometry: JsonRecord | null;
  metadata: JsonRecord;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface SpaceTreeNode extends Space {
  children: SpaceTreeNode[];
}

export interface AssignedDevice {
  device_id: string;
  entity_id: string;
  adapter_id: string;
  external_id: string;
  name: string;
  device_type: string;
  is_online: boolean;
  is_enabled: boolean;
  assignment_id: string;
  assignment_type: AssignmentType;
  valid_from: string;
  valid_until: string | null;
  confidence: number | null;
  source_type: string;
  source_id: string | null;
  reason: string | null;
}

export interface AssignmentHistoryItem {
  id: string;
  entity_id: string;
  device_id: string | null;
  space_id: string;
  space_name: string;
  space_path: string;
  assignment_type: AssignmentType;
  valid_from: string;
  valid_until: string | null;
  confidence: number | null;
  source_type: string;
  source_id: string | null;
  source_observation_id: string | null;
  reason: string | null;
  created_at: string;
  updated_at: string;
}

export type StateEstimationStatus =
  "observed" | "derived" | "inferred" | "unknown" | "stale" | "unavailable" | "conflict";

export type EnvironmentCoverageStatus = "covered" | "partial" | "blind" | "lost";

export interface RuleInfo {
  id: string;
  version: string;
}

export interface StateEstimate {
  id: string;
  target_id: string;
  environment_id: string;
  target_type: string;
  entity_id: string | null;
  space_id: string | null;
  attribute: string;
  status: StateEstimationStatus;
  value: JsonValue;
  unit: string | null;
  confidence: number | null;
  evidence_summary: JsonRecord;
  conflict_details: JsonRecord | null;
  rule: RuleInfo;
  input_cutoff_at: string;
  effective_from: string;
  generated_at: string;
  valid_until: string | null;
  superseded_at: string | null;
  created_at: string;
}

export interface StateEstimateEvidence {
  observation_id: string;
  source_id: string;
  source_type: string;
  entity_id: string | null;
  space_id: string | null;
  attribute: string;
  normalized_value: JsonValue;
  normalized_unit: string | null;
  observed_at: string | null;
  observed_at_source: string | null;
  received_at: string;
  quality_status: string;
  contribution: string;
  weight: number | null;
  exclusion_reason: string | null;
}

export interface QueriedSpaceSummary {
  space_id: string;
  parent_id: string | null;
  space_type: string;
  name: string;
  path: string[];
  status: string;
  state_ids: string[];
}

export interface QueriedEntitySummary {
  entity_id: string;
  name: string;
  entity_type: string;
  device_id: string | null;
  space_id: string | null;
  state_ids: string[];
}

export interface StateCoverage {
  space_id: string;
  attribute: string;
  coverage: EnvironmentCoverageStatus;
  state_status: StateEstimationStatus | null;
  source_count: number;
  explanation: string;
}

export interface QuerySourceSummary {
  source_id: string;
  source_type: string | null;
  observation_count: number;
  entity_ids: string[];
  observation_ids: string[];
}

export interface QueryExplanation {
  status: StateEstimationStatus;
  space_id: string | null;
  entity_id: string | null;
  attribute: string;
  message: string;
  details: JsonRecord;
}

export interface EnvironmentOverview {
  service_available: boolean;
  environment_id: string | null;
  environment_name: string | null;
  root_space_id: string | null;
  selected_space: QueriedSpaceSummary | null;
  spaces: QueriedSpaceSummary[];
  entities: QueriedEntitySummary[];
  states: StateEstimate[];
  coverage: StateCoverage[];
  sources: QuerySourceSummary[];
  explanations: QueryExplanation[];
  evidence: StateEstimateEvidence[];
  attributes: string[];
  include_descendants: boolean;
  generated_at: string;
}

export interface SpaceCreateRequest {
  parent_id: string;
  name: string;
  space_type: Exclude<SpaceType, "home">;
  sort_order?: number;
  metadata?: JsonRecord;
}

export interface SpaceUpdateRequest {
  name?: string;
  sort_order?: number;
  status?: SpaceStatus;
}

export interface DeviceAssignmentRequest {
  space_id: string;
  assignment_type: AssignmentType;
  confidence?: number;
  reason?: string;
}
