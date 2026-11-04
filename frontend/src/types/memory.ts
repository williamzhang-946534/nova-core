import type { JsonRecord, PageResponse } from "./common";

export type MemoryType = "episodic" | "semantic" | "procedural";
export type MemoryStatus =
  "active" | "candidate" | "corrected" | "superseded" | "expired" | "archived";
export type MemorySourceType =
  | "user"
  | "observation"
  | "event"
  | "task"
  | "conversation"
  | "ai_inference"
  | "procedure_execution"
  | "system";
export type EvidenceType =
  | "observation"
  | "event"
  | "task"
  | "conversation"
  | "procedure_execution"
  | "user_statement"
  | "environment_snapshot";
export type QuestionType =
  | "preference"
  | "semantic_fact"
  | "spatial_fact"
  | "historical_event"
  | "task_record"
  | "procedure"
  | "any";

export interface MemoryEvidence {
  id: string;
  evidence_type: EvidenceType;
  evidence_id: string | null;
  source_type: string;
  source_record_id: string | null;
  trust_level: number;
  snapshot: JsonRecord;
  occurred_at: string | null;
  created_at: string;
  record?: JsonRecord | null;
}

export interface MemoryRevision {
  id: string;
  revision_type: string;
  previous_content: string;
  changed_fields: JsonRecord;
  actor_type: string;
  actor_id: string;
  reason: string | null;
  created_at: string;
}

export interface MemoryItem {
  id: string;
  memory_type: MemoryType;
  title: string;
  content: string;
  summary: string | null;
  keywords: string[];
  importance: number;
  source_type: MemorySourceType;
  source_id: string | null;
  user_confirmed: boolean;
  status: MemoryStatus;
  confidence: number;
  verification_status: "unverified" | "verified" | "rejected";
  owner_id: string;
  access_level: string;
  scope: JsonRecord;
  environment_id: string | null;
  space_id: string | null;
  entity_id: string | null;
  conversation_id: string | null;
  task_id: string | null;
  subject_type: string | null;
  subject_id: string | null;
  predicate: string | null;
  object_value: unknown;
  valid_from: string;
  expires_at: string | null;
  retention_until: string | null;
  last_reviewed_at: string | null;
  correction_count: number;
  created_at: string;
  updated_at: string;
}

export interface PreferenceItem {
  id: string;
  key: string;
  value: JsonRecord;
  category: string;
  description: string | null;
  source: string;
  source_type: string;
  source_record_id: string;
  status: "draft" | "active" | "revoked";
  scope: JsonRecord;
  conversation_id: string | null;
  consent_id: string | null;
  confirmed: boolean;
  confirmed_at: string | null;
  valid_from: string;
  expires_at: string | null;
  retention_until: string | null;
  superseded_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface RetrievalResult {
  question_type: QuestionType;
  query: string;
  memories: MemoryItem[];
  preferences: PreferenceItem[];
  source_references: MemoryEvidence[];
  retrieved_at: string;
}

export interface MemoryCreatePayload {
  memory_type: MemoryType;
  title: string;
  content: string;
  summary?: string | null;
  keywords?: string[];
  importance?: number;
  source_type: MemorySourceType;
  source_id?: string | null;
  user_confirmed?: boolean;
  confidence?: number;
  owner_id?: string;
  access_level?: "owner_only" | "household";
  scope?: JsonRecord;
  environment_id?: string | null;
  space_id?: string | null;
  entity_id?: string | null;
  conversation_id?: string | null;
  task_id?: string | null;
  subject_type?: string | null;
  subject_id?: string | null;
  predicate?: string | null;
  object_value?: unknown;
  valid_from?: string | null;
  expires_at?: string | null;
  retention_until?: string | null;
  evidence?: Array<Omit<MemoryEvidence, "id" | "created_at" | "record">>;
}

export interface MemoryUpdatePayload {
  title?: string;
  content?: string;
  summary?: string | null;
  keywords?: string[];
  importance?: number;
  scope?: JsonRecord;
  space_id?: string | null;
  entity_id?: string | null;
  expires_at?: string | null;
  retention_until?: string | null;
  status?: "active" | "archived";
  previous_content?: string;
  reason?: string;
}

export interface PreferenceCreatePayload {
  key: string;
  value: JsonRecord;
  category?: string;
  description?: string | null;
  source_type?: "user";
  source_record_id: string;
  conversation_id?: string | null;
  consent_statement: string;
  scope?: JsonRecord;
  confirmed?: boolean;
}

export interface PreferenceUpdatePayload {
  value?: JsonRecord;
  category?: string;
  description?: string | null;
  scope?: JsonRecord;
  expires_at?: string | null;
}

export interface ProcedureVersionPayload {
  version: string;
  steps: JsonRecord[];
  input_schema?: JsonRecord;
  output_schema?: JsonRecord;
  risk_level?: "read_only" | "low_risk" | "medium_risk" | "high_risk";
  required_successes?: number;
}

export interface ProcedureValidationPayload {
  version: string;
  task_id?: string | null;
  tool_execution_id?: string | null;
  status: "passed" | "failed";
  result?: JsonRecord;
  validator_type?: string;
}

export interface MemoryListQuery {
  memory_type?: MemoryType;
  status?: MemoryStatus | "current";
  source_type?: MemorySourceType;
  keyword?: string;
  environment_id?: string;
  space_id?: string;
  entity_id?: string;
  include_expired?: boolean;
  page?: number;
  page_size?: number;
}

export interface PreferenceListQuery {
  status?: "draft" | "active" | "revoked";
  category?: string;
  keyword?: string;
  page?: number;
  page_size?: number;
}

export type MemoryListResponse = PageResponse<MemoryItem>;
export type PreferenceListResponse = PageResponse<PreferenceItem>;
export interface MemoryDeleteResponse {
  data: { id: string; deleted: boolean };
}
export interface MemoryCleanupResponse {
  data: { expired: number; deleted: number };
}
