import type { JsonRecord } from "./common";

export type ReasoningSessionStatus = "running" | "completed" | "failed";
export type ReasoningEvidenceClassification =
  "observed" | "derived" | "inferred_candidate" | "verified_cause" | "unknown";
export type ReasoningHypothesisType =
  | "deterministic_rule"
  | "correlation"
  | "ai_candidate"
  | "verified_cause"
  | "data_quality"
  | "unknown";
export type ReasoningHypothesisStatus =
  "unsupported" | "plausible" | "supported" | "conflicted" | "refuted" | "expired" | "superseded";

export interface ReasoningEvidence {
  id: string;
  source_type: string;
  source_record_id: string;
  classification: ReasoningEvidenceClassification;
  statement: string;
  snapshot: JsonRecord;
  scope: JsonRecord;
  source_time?: string | null;
  received_time?: string | null;
  quality_status: string;
  quality_issues: JsonRecord[];
  trust_level: number;
  source_available: boolean;
  created_at: string;
}

export interface ReasoningHypothesis {
  id: string;
  session_id: string;
  environment_id: string;
  statement: string;
  hypothesis_type: ReasoningHypothesisType;
  origin_type: string;
  status: ReasoningHypothesisStatus;
  confidence_level: string;
  causal_claim: boolean;
  explanation: string;
  limitations: string[];
  unknowns: string[];
  rule_id?: string | null;
  rule_version?: string | null;
  superseded_by_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ReasoningSession {
  id: string;
  environment_id: string;
  question: string;
  trigger: string;
  status: ReasoningSessionStatus;
  scope: JsonRecord;
  diagnosis: JsonRecord;
  analyzer_versions: JsonRecord;
  actor_type: string;
  actor_id: string;
  started_at: string;
  completed_at?: string | null;
  created_at: string;
}

export interface ReasoningDiagnoseInput {
  question: string;
  environmentId?: string;
  spaceName?: string;
  entityId?: string;
  attribute?: string;
  lookbackSeconds?: number;
  trigger?: "user" | "system" | "automation";
}

export type GoalStatus =
  "candidate" | "active" | "paused" | "completed" | "failed" | "cancelled" | "expired";
export type PlanStatus =
  | "draft"
  | "validated"
  | "awaiting_confirmation"
  | "approved"
  | "submitted"
  | "superseded"
  | "cancelled"
  | "rejected";

export interface Goal {
  id: string;
  environment_id: string;
  title: string;
  description?: string | null;
  objective: string;
  origin_type: string;
  status: GoalStatus;
  goal_type: string;
  scope: JsonRecord;
  desired_state: JsonRecord;
  constraints: JsonRecord;
  prohibitions: JsonRecord[];
  clarifications: string[];
  unknowns: string[];
  priority: string;
  authorization_scope: JsonRecord;
  reasoning_session_id?: string | null;
  confirmed_by_user: boolean;
  created_at: string;
  updated_at: string;
  closed_at?: string | null;
}

export interface PlanStep {
  id: string;
  plan_id: string;
  step_index: number;
  name: string;
  purpose: string;
  tool_name: string;
  input: JsonRecord;
  risk_level: string;
  requires_confirmation: boolean;
  on_failure: string;
  depends_on: string[];
}

export interface Plan {
  id: string;
  environment_id: string;
  goal_id: string;
  version: number;
  status: PlanStatus;
  planner_type: string;
  run_mode: string;
  strategy: JsonRecord;
  max_risk_level: string;
  validation_errors: JsonRecord[];
  submitted_task_id?: string | null;
  superseded_by_id?: string | null;
  created_at: string;
  updated_at: string;
  closed_at?: string | null;
  steps: PlanStep[];
}

export type ProactiveStatus =
  | "evaluated"
  | "suppressed"
  | "queued"
  | "delivered"
  | "opened"
  | "accepted"
  | "dismissed"
  | "expired";

export interface ProactiveSuggestion {
  id: string;
  environment_id: string;
  reasoning_session_id?: string | null;
  hypothesis_id?: string | null;
  goal_id?: string | null;
  trigger_type: string;
  title: string;
  message: string;
  importance: string;
  autonomy_level: number;
  candidate_action: JsonRecord;
  evidence_refs: JsonRecord[];
  dedupe_key: string;
  status: ProactiveStatus;
  suppression_count: number;
  delivered_at?: string | null;
  opened_at?: string | null;
  accepted_at?: string | null;
  dismissed_at?: string | null;
  user_feedback?: JsonRecord | null;
  quality_score?: number | null;
  created_at: string;
  updated_at: string;
  expires_at?: string | null;
}

export type ActivePerceptionStatus =
  | "proposed"
  | "awaiting_consent"
  | "rejected"
  | "queued"
  | "executed"
  | "fulfilled"
  | "unavailable"
  | "expired";

export interface ActivePerceptionRequest {
  id: string;
  environment_id: string;
  reasoning_session_id: string;
  hypothesis_id?: string | null;
  question: string;
  gap_type: string;
  subject_type: string;
  subject_id: string;
  space_id?: string | null;
  entity_id?: string | null;
  attribute?: string | null;
  needed_time_range: JsonRecord;
  proposed_capability?: string | null;
  proposed_input: JsonRecord;
  privacy_level: string;
  requires_user_consent: boolean;
  authorized_at?: string | null;
  authorization_scope?: JsonRecord | null;
  status: ActivePerceptionStatus;
  fulfilled_by_type?: string | null;
  fulfilled_by_id?: string | null;
  execution_trace?: JsonRecord | null;
  unavailable_reason?: string | null;
  created_at: string;
  updated_at: string;
  expires_at?: string | null;
}
