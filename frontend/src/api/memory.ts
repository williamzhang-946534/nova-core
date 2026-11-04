import { buildQueryString, requestJson } from "./client";
import type {
  EvidenceType,
  MemoryCleanupResponse,
  MemoryCreatePayload,
  MemoryDeleteResponse,
  MemoryEvidence,
  MemoryItem,
  MemoryListQuery,
  MemoryListResponse,
  MemoryRevision,
  MemorySourceType,
  MemoryStatus,
  MemoryType,
  MemoryUpdatePayload,
  PreferenceCreatePayload,
  PreferenceItem,
  PreferenceListQuery,
  PreferenceListResponse,
  PreferenceUpdatePayload,
  ProcedureValidationPayload,
  ProcedureVersionPayload,
  QuestionType,
  RetrievalResult,
} from "@/types/memory";
import type { JsonRecord } from "@/types/common";
import {
  isBoolean,
  isNumber,
  isOneOf,
  isRecord,
  isString,
  isStringArray,
  isStringOrNull,
} from "@/utils/validation";

const memoryTypes = ["episodic", "semantic", "procedural"] as const satisfies readonly MemoryType[];
const memoryStatuses = [
  "active",
  "candidate",
  "corrected",
  "superseded",
  "expired",
  "archived",
] as const satisfies readonly MemoryStatus[];
const memorySourceTypes = [
  "user",
  "observation",
  "event",
  "task",
  "conversation",
  "ai_inference",
  "procedure_execution",
  "system",
] as const satisfies readonly MemorySourceType[];
const evidenceTypes = [
  "observation",
  "event",
  "task",
  "conversation",
  "procedure_execution",
  "user_statement",
  "environment_snapshot",
] as const satisfies readonly EvidenceType[];

function isPageResponse<T>(
  value: unknown,
  itemGuard: (item: unknown) => item is T,
): value is { data: T[]; page: number; page_size: number; total: number } {
  return (
    isRecord(value) &&
    Array.isArray(value.data) &&
    value.data.every(itemGuard) &&
    isNumber(value.page) &&
    isNumber(value.page_size) &&
    isNumber(value.total)
  );
}

function isEvidence(value: unknown): value is MemoryEvidence {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isOneOf(value.evidence_type, evidenceTypes) &&
    isStringOrNull(value.evidence_id) &&
    isString(value.source_type) &&
    isStringOrNull(value.source_record_id) &&
    isNumber(value.trust_level) &&
    isRecord(value.snapshot) &&
    isStringOrNull(value.occurred_at) &&
    isString(value.created_at)
  );
}

function isMemory(value: unknown): value is MemoryItem {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isOneOf(value.memory_type, memoryTypes) &&
    isString(value.title) &&
    isString(value.content) &&
    isStringOrNull(value.summary) &&
    isStringArray(value.keywords) &&
    isNumber(value.importance) &&
    isOneOf(value.source_type, memorySourceTypes) &&
    isStringOrNull(value.source_id) &&
    isBoolean(value.user_confirmed) &&
    isOneOf(value.status, memoryStatuses) &&
    isNumber(value.confidence) &&
    isOneOf(value.verification_status, ["unverified", "verified", "rejected"] as const) &&
    isString(value.owner_id) &&
    isString(value.access_level) &&
    isRecord(value.scope) &&
    isStringOrNull(value.environment_id) &&
    isStringOrNull(value.space_id) &&
    isStringOrNull(value.entity_id) &&
    isStringOrNull(value.conversation_id) &&
    isStringOrNull(value.task_id) &&
    isStringOrNull(value.subject_type) &&
    isStringOrNull(value.subject_id) &&
    isStringOrNull(value.predicate) &&
    isString(value.valid_from) &&
    isStringOrNull(value.expires_at) &&
    isStringOrNull(value.retention_until) &&
    isStringOrNull(value.last_reviewed_at) &&
    isNumber(value.correction_count) &&
    isString(value.created_at) &&
    isString(value.updated_at)
  );
}

function isPreference(value: unknown): value is PreferenceItem {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.key) &&
    isRecord(value.value) &&
    isString(value.category) &&
    isStringOrNull(value.description) &&
    isString(value.source) &&
    isString(value.source_type) &&
    isString(value.source_record_id) &&
    isOneOf(value.status, ["draft", "active", "revoked"] as const) &&
    isRecord(value.scope) &&
    isStringOrNull(value.conversation_id) &&
    isStringOrNull(value.consent_id) &&
    isBoolean(value.confirmed) &&
    isStringOrNull(value.confirmed_at) &&
    isString(value.valid_from) &&
    isStringOrNull(value.expires_at) &&
    isStringOrNull(value.retention_until) &&
    isStringOrNull(value.superseded_at) &&
    isString(value.created_at) &&
    isString(value.updated_at)
  );
}

function isRevision(value: unknown): value is MemoryRevision {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.revision_type) &&
    isString(value.previous_content) &&
    isRecord(value.changed_fields) &&
    isString(value.actor_type) &&
    isString(value.actor_id) &&
    isStringOrNull(value.reason) &&
    isString(value.created_at)
  );
}

function isHistoryReference(
  value: unknown,
): value is { evidence: import("@/types/memory").MemoryEvidence; record: JsonRecord | null } {
  return (
    isRecord(value) &&
    isEvidence(value.evidence) &&
    (value.record === null || isRecord(value.record))
  );
}

function isRetrieval(value: unknown): value is RetrievalResult {
  return (
    isRecord(value) &&
    isOneOf(value.question_type, [
      "preference",
      "semantic_fact",
      "spatial_fact",
      "historical_event",
      "task_record",
      "procedure",
      "any",
    ] as const satisfies readonly QuestionType[]) &&
    isString(value.query) &&
    Array.isArray(value.memories) &&
    value.memories.every(isMemory) &&
    Array.isArray(value.preferences) &&
    value.preferences.every(isPreference) &&
    Array.isArray(value.source_references) &&
    value.source_references.every(isEvidence) &&
    isString(value.retrieved_at)
  );
}

function dataGuard<T>(
  itemGuard: (item: unknown) => item is T,
): (value: unknown) => value is { data: T } {
  return (value): value is { data: T } => isRecord(value) && itemGuard(value.data);
}

export function listMemories(query: MemoryListQuery = {}): Promise<MemoryListResponse> {
  return requestJson<MemoryListResponse>(
    `/api/memories${buildQueryString({ ...query })}`,
    (value): value is MemoryListResponse => isPageResponse(value, isMemory),
  );
}

export function createMemory(payload: MemoryCreatePayload): Promise<MemoryItem> {
  return requestJson<{ data: MemoryItem }>("/api/memories", dataGuard(isMemory), {
    method: "POST",
    body: payload,
  }).then((response) => response.data);
}

export function getMemory(memoryId: string): Promise<MemoryItem> {
  return requestJson<{ data: MemoryItem }>(
    `/api/memories/${encodeURIComponent(memoryId)}`,
    dataGuard(isMemory),
  ).then((response) => response.data);
}

export function updateMemory(memoryId: string, changes: MemoryUpdatePayload): Promise<MemoryItem> {
  return requestJson<{ data: MemoryItem }>(
    `/api/memories/${encodeURIComponent(memoryId)}`,
    dataGuard(isMemory),
    { method: "PATCH", body: changes },
  ).then((response) => response.data);
}

export function correctMemory(
  memoryId: string,
  content: string,
  reason?: string,
): Promise<MemoryItem> {
  return requestJson<{ data: MemoryItem }>(
    `/api/memories/${encodeURIComponent(memoryId)}/correct`,
    dataGuard(isMemory),
    { method: "POST", body: { content, reason } },
  ).then((response) => response.data);
}

export function confirmMemory(memoryId: string): Promise<MemoryItem> {
  return requestJson<{ data: MemoryItem }>(
    `/api/memories/${encodeURIComponent(memoryId)}/confirm`,
    dataGuard(isMemory),
    { method: "POST" },
  ).then((response) => response.data);
}

export function deleteMemory(memoryId: string): Promise<MemoryDeleteResponse["data"]> {
  return requestJson<MemoryDeleteResponse>(
    `/api/memories/${encodeURIComponent(memoryId)}`,
    (value): value is MemoryDeleteResponse =>
      isRecord(value) &&
      isRecord(value.data) &&
      isString(value.data.id) &&
      isBoolean(value.data.deleted),
    { method: "DELETE" },
  ).then((response) => response.data);
}

export function cleanupMemories(): Promise<MemoryCleanupResponse["data"]> {
  return requestJson<MemoryCleanupResponse>(
    "/api/memories/cleanup",
    (value): value is MemoryCleanupResponse =>
      isRecord(value) &&
      isRecord(value.data) &&
      isNumber(value.data.expired) &&
      isNumber(value.data.deleted),
    { method: "POST" },
  ).then((response) => response.data);
}

export function memoryRevisions(memoryId: string): Promise<MemoryRevision[]> {
  return requestJson<{ data: MemoryRevision[] }>(
    `/api/memories/${encodeURIComponent(memoryId)}/revisions`,
    (value): value is { data: MemoryRevision[] } =>
      isRecord(value) && Array.isArray(value.data) && value.data.every(isRevision),
  ).then((response) => response.data);
}

export function memoryHistory(memoryId: string) {
  return requestJson<{ data: Array<{ evidence: MemoryEvidence; record: JsonRecord | null }> }>(
    `/api/memories/${encodeURIComponent(memoryId)}/history`,
    (value): value is { data: Array<{ evidence: MemoryEvidence; record: JsonRecord | null }> } =>
      isRecord(value) && Array.isArray(value.data) && value.data.every(isHistoryReference),
  ).then((response) => response.data);
}

export function createProcedureVersion(memoryId: string, payload: ProcedureVersionPayload) {
  return requestJson<{ data: JsonRecord }>(
    `/api/memories/${encodeURIComponent(memoryId)}/procedure-versions`,
    (value): value is { data: JsonRecord } => isRecord(value) && isRecord(value.data),
    { method: "POST", body: payload },
  ).then((response) => response.data);
}

export function validateProcedure(memoryId: string, payload: ProcedureValidationPayload) {
  return requestJson<{ data: JsonRecord }>(
    `/api/memories/${encodeURIComponent(memoryId)}/procedure-validations`,
    (value): value is { data: JsonRecord } => isRecord(value) && isRecord(value.data),
    { method: "POST", body: payload },
  ).then((response) => response.data);
}

export function listPreferences(query: PreferenceListQuery = {}): Promise<PreferenceListResponse> {
  return requestJson<PreferenceListResponse>(
    `/api/memory-preferences${buildQueryString({ ...query })}`,
    (value): value is PreferenceListResponse => isPageResponse(value, isPreference),
  );
}

export function createPreference(payload: PreferenceCreatePayload): Promise<PreferenceItem> {
  return requestJson<{ data: PreferenceItem }>("/api/memory-preferences", dataGuard(isPreference), {
    method: "POST",
    body: payload,
  }).then((response) => response.data);
}

export function getPreference(preferenceId: string): Promise<PreferenceItem> {
  return requestJson<{ data: PreferenceItem }>(
    `/api/memory-preferences/${encodeURIComponent(preferenceId)}`,
    dataGuard(isPreference),
  ).then((response) => response.data);
}

export function updatePreference(
  preferenceId: string,
  changes: PreferenceUpdatePayload,
): Promise<PreferenceItem> {
  return requestJson<{ data: PreferenceItem }>(
    `/api/memory-preferences/${encodeURIComponent(preferenceId)}`,
    dataGuard(isPreference),
    { method: "PATCH", body: changes },
  ).then((response) => response.data);
}

export function confirmPreference(preferenceId: string): Promise<PreferenceItem> {
  return requestJson<{ data: PreferenceItem }>(
    `/api/memory-preferences/${encodeURIComponent(preferenceId)}/confirm`,
    dataGuard(isPreference),
    { method: "POST" },
  ).then((response) => response.data);
}

export function deletePreference(preferenceId: string): Promise<MemoryDeleteResponse["data"]> {
  return requestJson<MemoryDeleteResponse>(
    `/api/memory-preferences/${encodeURIComponent(preferenceId)}`,
    (value): value is MemoryDeleteResponse =>
      isRecord(value) &&
      isRecord(value.data) &&
      isString(value.data.id) &&
      isBoolean(value.data.deleted),
    { method: "DELETE" },
  ).then((response) => response.data);
}

export function retrieveMemory(query: {
  question_type: QuestionType;
  query?: string;
}): Promise<RetrievalResult> {
  return requestJson<{ data: RetrievalResult }>(
    "/api/memory-retrieval",
    (value): value is { data: RetrievalResult } => isRecord(value) && isRetrieval(value.data),
    { method: "POST", body: query },
  ).then((response) => response.data);
}
