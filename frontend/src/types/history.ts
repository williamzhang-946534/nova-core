import type { JsonRecord } from "./common";

export type HistoryRecordType = "observation" | "event" | "task" | "snapshot";

export interface HistoryRecord {
  record_type: HistoryRecordType;
  record_id: string;
  collected_at?: string | null;
  received_at?: string | null;
  processed_at?: string | null;
  occurred_at?: string | null;
  local_time?: string | null;
  source?: string | null;
  entity_id?: string | null;
  space_id?: string | null;
  subject_type?: string | null;
  subject_id?: string | null;
  attribute?: string | null;
  value?: unknown;
  unit?: string | null;
  quality_status?: string | null;
  correlation_id?: string | null;
  data: JsonRecord;
}

export interface HistoryTimeRange {
  start_time: string;
  end_time: string;
  local_start_time: string;
  local_end_time: string;
}

export interface TimeSemantics {
  storage_timezone: string;
  local_timezone: string;
  query_time_basis: string;
  collected_time_available: number;
  received_time_available: number;
  processed_time_available: number;
  late_arrival_threshold_seconds: number;
  clock_skew_tolerance_seconds: number;
  late_observations: string[];
  future_clock_skew_observations: string[];
  observations_without_collected_time: string[];
}

export interface TimeGap {
  start_time: string;
  end_time: string;
  duration_seconds: number;
  reason: string;
}

export interface HistoryQueryResult {
  range: HistoryTimeRange;
  time_semantics: TimeSemantics;
  records: HistoryRecord[];
  counts: JsonRecord;
  missing_ranges: TimeGap[];
  warnings: string[];
  generated_at: string;
}

export interface TrendStatistics {
  group_key: string;
  label: string;
  attribute: string;
  observation_count: number;
  valid_count: number;
  numeric_count: number;
  minimum?: number | null;
  maximum?: number | null;
  average?: number | null;
  first_value?: number | null;
  last_value?: number | null;
  change?: number | null;
  change_per_hour?: number | null;
  first_at?: string | null;
  last_at?: string | null;
  unit?: string | null;
}

export interface TrendQueryResult {
  range: HistoryTimeRange;
  time_semantics: TimeSemantics;
  attribute: string;
  group_by: "space" | "entity";
  include_descendants: boolean;
  statistics: TrendStatistics[];
  missing_ranges: TimeGap[];
  warnings: string[];
  generated_at: string;
}

export interface EnvironmentSnapshot {
  id: string;
  environment_id: string;
  context: JsonRecord;
  active_task_ids: string[];
  anomaly_count: number;
  context_version: number;
  state_generated_at?: string | null;
  created_at: string;
  local_created_at: string;
}

export interface SnapshotLookupResult {
  requested_at: string;
  snapshot?: EnvironmentSnapshot | null;
  local_requested_at: string;
  selection: "at_or_before" | "nearest";
  distance_seconds?: number | null;
  state_as_of?: string | null;
  warning?: string | null;
}

export interface SnapshotDiffEntry {
  path: string;
  before?: unknown;
  after?: unknown;
  change_type: "added" | "removed" | "changed";
  recoverability: string;
  recoverable_by_device: boolean;
  physical_rollback_possible: boolean;
  explanation: string;
}

export interface SnapshotDiffResult {
  baseline: EnvironmentSnapshot;
  target: EnvironmentSnapshot;
  changes: SnapshotDiffEntry[];
  unchanged_count: number;
  device_recoverable_paths: string[];
  physical_change_paths: string[];
  missing_data_paths: string[];
  reality_git: JsonRecord;
  generated_at: string;
}

export interface CorrelatedHistory {
  record: HistoryRecord;
  events: HistoryRecord[];
  tasks: HistoryRecord[];
  observations: HistoryRecord[];
  snapshots: EnvironmentSnapshot[];
  relation_basis: JsonRecord;
  warnings: string[];
}

export interface NaturalHistoryAnswer {
  query: string;
  interpretation: {
    question_type: string;
    confidence: number;
    explanation: string;
    action?: string | null;
    action_resolved: boolean;
    space_id?: string | null;
    entity_id?: string | null;
    attribute?: string | null;
  };
  range: HistoryTimeRange;
  time_semantics: TimeSemantics;
  answer: string;
  based_on_record_count: number;
  records: HistoryRecord[];
  statistics: TrendStatistics[];
  snapshots: EnvironmentSnapshot[];
  missing_ranges: TimeGap[];
  warnings: string[];
  generated_at: string;
}

export interface HistoryQuery {
  startTime: string;
  endTime: string;
  timezone?: string;
  spaceId?: string;
  entityId?: string;
  includeDescendants?: boolean;
  attribute?: string;
  qualityStatus?: string;
  expectedIntervalSeconds?: number;
  limit?: number;
}

export interface TrendQuery extends HistoryQuery {
  attribute: string;
  groupBy: "space" | "entity";
}
