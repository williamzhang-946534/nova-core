import { buildQueryString, requestJson } from "./client";
import type { PageResponse } from "@/types/common";
import type {
  ActivePerceptionRequest,
  Goal,
  Plan,
  ProactiveSuggestion,
  ReasoningDiagnoseInput,
  ReasoningEvidence,
  ReasoningHypothesis,
  ReasoningSession,
} from "@/types/intelligence";
import {
  isBoolean,
  isJsonValue,
  isNumber,
  isNumberOrNull,
  isOneOf,
  isRecord,
  isRecordOrNull,
  isString,
  isStringArray,
  isStringOrNull,
} from "@/utils/validation";

function isPage<T>(guard: (value: unknown) => value is T) {
  return (value: unknown): value is PageResponse<T> =>
    isRecord(value) &&
    Array.isArray(value.data) &&
    value.data.every(guard) &&
    isNumber(value.page) &&
    isNumber(value.page_size) &&
    isNumber(value.total);
}

const data =
  <T>(guard: (value: unknown) => value is T) =>
  (value: unknown): value is { data: T } =>
    isRecord(value) && guard(value.data);

const unwrap = <T>(promise: Promise<{ data: T }>) => promise.then((response) => response.data);

const reasoningStatuses = ["running", "completed", "failed"] as const;
const reasoningClassifications = [
  "observed",
  "derived",
  "inferred_candidate",
  "verified_cause",
  "unknown",
] as const;
const reasoningHypothesisTypes = [
  "deterministic_rule",
  "correlation",
  "ai_candidate",
  "verified_cause",
  "data_quality",
  "unknown",
] as const;
const reasoningHypothesisStatuses = [
  "unsupported",
  "plausible",
  "supported",
  "conflicted",
  "refuted",
  "expired",
  "superseded",
] as const;

function isReasoningEvidence(value: unknown): value is ReasoningEvidence {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.source_type) &&
    isString(value.source_record_id) &&
    isOneOf(value.classification, reasoningClassifications) &&
    isString(value.statement) &&
    isRecord(value.snapshot) &&
    isRecord(value.scope) &&
    isStringOrNull(value.source_time) &&
    isStringOrNull(value.received_time) &&
    isString(value.quality_status) &&
    Array.isArray(value.quality_issues) &&
    value.quality_issues.every(isRecord) &&
    isNumber(value.trust_level) &&
    isBoolean(value.source_available) &&
    isString(value.created_at)
  );
}

function isReasoningHypothesis(value: unknown): value is ReasoningHypothesis {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.session_id) &&
    isString(value.environment_id) &&
    isString(value.statement) &&
    isOneOf(value.hypothesis_type, reasoningHypothesisTypes) &&
    isString(value.origin_type) &&
    isOneOf(value.status, reasoningHypothesisStatuses) &&
    isString(value.confidence_level) &&
    isBoolean(value.causal_claim) &&
    isString(value.explanation) &&
    isStringArray(value.limitations) &&
    isStringArray(value.unknowns) &&
    isStringOrNull(value.rule_id) &&
    isStringOrNull(value.rule_version) &&
    isStringOrNull(value.superseded_by_id) &&
    isString(value.created_at) &&
    isString(value.updated_at)
  );
}

function isReasoningSession(value: unknown): value is ReasoningSession {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.environment_id) &&
    isString(value.question) &&
    isString(value.trigger) &&
    isOneOf(value.status, reasoningStatuses) &&
    isRecord(value.scope) &&
    isRecord(value.diagnosis) &&
    isRecord(value.analyzer_versions) &&
    isString(value.actor_type) &&
    isString(value.actor_id) &&
    isString(value.started_at) &&
    isStringOrNull(value.completed_at) &&
    isString(value.created_at)
  );
}

export function createReasoningSession(input: ReasoningDiagnoseInput) {
  return unwrap(
    requestJson("/api/reasoning/sessions", data(isReasoningSession), {
      method: "POST",
      body: {
        question: input.question,
        environment_id: input.environmentId,
        space_name: input.spaceName,
        entity_id: input.entityId,
        attribute: input.attribute,
        lookback_seconds: input.lookbackSeconds,
        trigger: input.trigger ?? "user",
      },
    }),
  );
}

export function listReasoningSessions(
  query: {
    environmentId?: string;
    status?: ReasoningSession["status"];
    page?: number;
    pageSize?: number;
  } = {},
) {
  return requestJson(
    `/api/reasoning/sessions${buildQueryString({
      environment_id: query.environmentId,
      status: query.status,
      page: query.page,
      page_size: query.pageSize,
    })}`,
    isPage(isReasoningSession),
  );
}

export function getReasoningSession(id: string) {
  return unwrap(
    requestJson(`/api/reasoning/sessions/${encodeURIComponent(id)}`, data(isReasoningSession)),
  );
}

export function deleteReasoningSession(id: string) {
  return unwrap(
    requestJson(
      `/api/reasoning/sessions/${encodeURIComponent(id)}`,
      data((value): value is { id: string; deleted: boolean } => {
        return isRecord(value) && isString(value.id) && isBoolean(value.deleted);
      }),
      { method: "DELETE" },
    ),
  );
}

export function listReasoningEvidence(sessionId: string, page = 1, pageSize = 50) {
  return requestJson(
    `/api/reasoning/sessions/${encodeURIComponent(sessionId)}/evidence${buildQueryString({
      page,
      page_size: pageSize,
    })}`,
    isPage(isReasoningEvidence),
  );
}

export function listReasoningHypotheses(
  query: {
    sessionId?: string;
    environmentId?: string;
    status?: ReasoningHypothesis["status"];
    hypothesisType?: ReasoningHypothesis["hypothesis_type"];
    page?: number;
    pageSize?: number;
  } = {},
) {
  return requestJson(
    `/api/reasoning/hypotheses${buildQueryString({
      session_id: query.sessionId,
      environment_id: query.environmentId,
      status: query.status,
      hypothesis_type: query.hypothesisType,
      page: query.page,
      page_size: query.pageSize,
    })}`,
    isPage(isReasoningHypothesis),
  );
}

const goalStatuses = [
  "candidate",
  "active",
  "paused",
  "completed",
  "failed",
  "cancelled",
  "expired",
] as const;
const planStatuses = [
  "draft",
  "validated",
  "awaiting_confirmation",
  "approved",
  "submitted",
  "superseded",
  "cancelled",
  "rejected",
] as const;

function isGoal(value: unknown): value is Goal {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.environment_id) &&
    isString(value.title) &&
    isStringOrNull(value.description) &&
    isString(value.objective) &&
    isString(value.origin_type) &&
    isOneOf(value.status, goalStatuses) &&
    isString(value.goal_type) &&
    isRecord(value.scope) &&
    isRecord(value.desired_state) &&
    isRecord(value.constraints) &&
    Array.isArray(value.prohibitions) &&
    value.prohibitions.every(isRecord) &&
    isStringArray(value.clarifications) &&
    isStringArray(value.unknowns) &&
    isString(value.priority) &&
    isRecord(value.authorization_scope) &&
    isStringOrNull(value.reasoning_session_id) &&
    isBoolean(value.confirmed_by_user) &&
    isString(value.created_at) &&
    isString(value.updated_at) &&
    isStringOrNull(value.closed_at)
  );
}

function isPlanStep(value: unknown): value is Plan["steps"][number] {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.plan_id) &&
    isNumber(value.step_index) &&
    isString(value.name) &&
    isString(value.purpose) &&
    isString(value.tool_name) &&
    isRecord(value.input) &&
    isString(value.risk_level) &&
    isBoolean(value.requires_confirmation) &&
    isString(value.on_failure) &&
    isStringArray(value.depends_on)
  );
}

function isPlan(value: unknown): value is Plan {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.environment_id) &&
    isString(value.goal_id) &&
    isNumber(value.version) &&
    isOneOf(value.status, planStatuses) &&
    isString(value.planner_type) &&
    isString(value.run_mode) &&
    isRecord(value.strategy) &&
    isString(value.max_risk_level) &&
    Array.isArray(value.validation_errors) &&
    value.validation_errors.every(isRecord) &&
    isStringOrNull(value.submitted_task_id) &&
    isStringOrNull(value.superseded_by_id) &&
    isString(value.created_at) &&
    isString(value.updated_at) &&
    isStringOrNull(value.closed_at) &&
    Array.isArray(value.steps) &&
    value.steps.every(isPlanStep)
  );
}

export function createGoal(input: {
  objective: string;
  description?: string;
  priority?: string;
  reasoningSessionId?: string;
}) {
  return unwrap(
    requestJson("/api/planning/goals", data(isGoal), {
      method: "POST",
      body: {
        objective: input.objective,
        description: input.description,
        priority: input.priority ?? "normal",
        reasoning_session_id: input.reasoningSessionId,
      },
    }),
  );
}

export function listGoals(
  query: {
    environmentId?: string;
    status?: Goal["status"];
    page?: number;
    pageSize?: number;
  } = {},
) {
  return requestJson(
    `/api/planning/goals${buildQueryString({
      environment_id: query.environmentId,
      status: query.status,
      page: query.page,
      page_size: query.pageSize,
    })}`,
    isPage(isGoal),
  );
}

export function confirmGoal(id: string) {
  return unwrap(
    requestJson(`/api/planning/goals/${encodeURIComponent(id)}/confirm`, data(isGoal), {
      method: "POST",
      body: {},
    }),
  );
}

export function closeGoal(
  id: string,
  status: "completed" | "failed" | "cancelled" | "expired",
  reason: string,
) {
  return unwrap(
    requestJson(`/api/planning/goals/${encodeURIComponent(id)}/close`, data(isGoal), {
      method: "POST",
      body: { status, reason },
    }),
  );
}

export function createPlan(goalId: string, useAiCandidate = false) {
  return unwrap(
    requestJson(`/api/planning/goals/${encodeURIComponent(goalId)}/plans`, data(isPlan), {
      method: "POST",
      body: { mode: "plan", use_ai_candidate: useAiCandidate },
    }),
  );
}

export function listPlans(
  query: {
    goalId?: string;
    status?: Plan["status"];
    page?: number;
    pageSize?: number;
  } = {},
) {
  return requestJson(
    `/api/planning/plans${buildQueryString({
      goal_id: query.goalId,
      status: query.status,
      page: query.page,
      page_size: query.pageSize,
    })}`,
    isPage(isPlan),
  );
}

export function decidePlan(id: string, action: "approve" | "reject", reason?: string) {
  return unwrap(
    requestJson(`/api/planning/plans/${encodeURIComponent(id)}/${action}`, data(isPlan), {
      method: "POST",
      body: { reason },
    }),
  );
}

export function submitPlan(id: string) {
  return unwrap(
    requestJson(`/api/planning/plans/${encodeURIComponent(id)}/submit`, data(isPlan), {
      method: "POST",
    }),
  );
}

export function replanPlan(
  id: string,
  triggerType: "tool_failed" | "verification_failed" | "timeout",
  reason: string,
) {
  return unwrap(
    requestJson(`/api/planning/plans/${encodeURIComponent(id)}/replan`, data(isPlan), {
      method: "POST",
      body: { trigger_type: triggerType, reason },
    }),
  );
}

const proactiveStatuses = [
  "evaluated",
  "suppressed",
  "queued",
  "delivered",
  "opened",
  "accepted",
  "dismissed",
  "expired",
] as const;

function isProactiveSuggestion(value: unknown): value is ProactiveSuggestion {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.environment_id) &&
    isStringOrNull(value.reasoning_session_id) &&
    isStringOrNull(value.hypothesis_id) &&
    isStringOrNull(value.goal_id) &&
    isString(value.trigger_type) &&
    isString(value.title) &&
    isString(value.message) &&
    isString(value.importance) &&
    isNumber(value.autonomy_level) &&
    isRecord(value.candidate_action) &&
    Array.isArray(value.evidence_refs) &&
    value.evidence_refs.every(isRecord) &&
    isString(value.dedupe_key) &&
    isOneOf(value.status, proactiveStatuses) &&
    isNumber(value.suppression_count) &&
    isStringOrNull(value.delivered_at) &&
    isStringOrNull(value.opened_at) &&
    isStringOrNull(value.accepted_at) &&
    isStringOrNull(value.dismissed_at) &&
    isRecordOrNull(value.user_feedback) &&
    isNumberOrNull(value.quality_score) &&
    isString(value.created_at) &&
    isString(value.updated_at) &&
    isStringOrNull(value.expires_at)
  );
}

export function listProactiveSuggestions(
  query: {
    environmentId?: string;
    status?: ProactiveSuggestion["status"];
    triggerType?: string;
    importance?: string;
    page?: number;
    pageSize?: number;
  } = {},
) {
  return requestJson(
    `/api/proactive/suggestions${buildQueryString({
      environment_id: query.environmentId,
      status: query.status,
      trigger_type: query.triggerType,
      importance: query.importance,
      page: query.page,
      page_size: query.pageSize,
    })}`,
    isPage(isProactiveSuggestion),
  );
}

export function openProactiveSuggestion(id: string) {
  return unwrap(
    requestJson(
      `/api/proactive/suggestions/${encodeURIComponent(id)}/open`,
      data(isProactiveSuggestion),
      {
        method: "POST",
      },
    ),
  );
}

export function acceptProactiveSuggestion(id: string) {
  return unwrap(
    requestJson(
      `/api/proactive/suggestions/${encodeURIComponent(id)}/accept`,
      data(isProactiveSuggestion),
      {
        method: "POST",
        body: {},
      },
    ),
  );
}

export function dismissProactiveSuggestion(
  id: string,
  suppressFuture = false,
  suppressionHours = 24,
) {
  return unwrap(
    requestJson(
      `/api/proactive/suggestions/${encodeURIComponent(id)}/dismiss`,
      data(isProactiveSuggestion),
      {
        method: "POST",
        body: { suppress_future: suppressFuture, suppression_hours: suppressionHours },
      },
    ),
  );
}

export function feedbackProactiveSuggestion(
  id: string,
  useful: boolean,
  correct: boolean,
  comment?: string,
) {
  return unwrap(
    requestJson(
      `/api/proactive/suggestions/${encodeURIComponent(id)}/feedback`,
      data(isProactiveSuggestion),
      {
        method: "POST",
        body: { useful, correct, comment, desired_action: "keep" },
      },
    ),
  );
}

const perceptionStatuses = [
  "proposed",
  "awaiting_consent",
  "rejected",
  "queued",
  "executed",
  "fulfilled",
  "unavailable",
  "expired",
] as const;

function isActivePerceptionRequest(value: unknown): value is ActivePerceptionRequest {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.environment_id) &&
    isString(value.reasoning_session_id) &&
    isStringOrNull(value.hypothesis_id) &&
    isString(value.question) &&
    isString(value.gap_type) &&
    isString(value.subject_type) &&
    isString(value.subject_id) &&
    isStringOrNull(value.space_id) &&
    isStringOrNull(value.entity_id) &&
    isStringOrNull(value.attribute) &&
    isRecord(value.needed_time_range) &&
    isStringOrNull(value.proposed_capability) &&
    isRecord(value.proposed_input) &&
    isString(value.privacy_level) &&
    isBoolean(value.requires_user_consent) &&
    isStringOrNull(value.authorized_at) &&
    isRecordOrNull(value.authorization_scope) &&
    isOneOf(value.status, perceptionStatuses) &&
    isStringOrNull(value.fulfilled_by_type) &&
    isStringOrNull(value.fulfilled_by_id) &&
    isRecordOrNull(value.execution_trace) &&
    isStringOrNull(value.unavailable_reason) &&
    isString(value.created_at) &&
    isString(value.updated_at) &&
    isStringOrNull(value.expires_at)
  );
}

export function evaluateActivePerception(input: {
  question: string;
  environmentId?: string;
  reasoningSessionId?: string;
  hypothesisId?: string;
  spaceId?: string;
  entityId?: string;
  attribute: string;
}) {
  return unwrap(
    requestJson("/api/active-perception/requests/evaluate", data(isActivePerceptionRequest), {
      method: "POST",
      body: {
        question: input.question,
        environment_id: input.environmentId,
        reasoning_session_id: input.reasoningSessionId,
        hypothesis_id: input.hypothesisId,
        space_id: input.spaceId,
        entity_id: input.entityId,
        attribute: input.attribute,
      },
    }),
  );
}

export function listActivePerceptionRequests(
  query: {
    environmentId?: string;
    status?: ActivePerceptionRequest["status"];
    gapType?: string;
    privacyLevel?: string;
    page?: number;
    pageSize?: number;
  } = {},
) {
  return requestJson(
    `/api/active-perception/requests${buildQueryString({
      environment_id: query.environmentId,
      status: query.status,
      gap_type: query.gapType,
      privacy_level: query.privacyLevel,
      page: query.page,
      page_size: query.pageSize,
    })}`,
    isPage(isActivePerceptionRequest),
  );
}

export function authorizeActivePerception(id: string, authorizationSeconds = 3600) {
  return unwrap(
    requestJson(
      `/api/active-perception/requests/${encodeURIComponent(id)}/authorize`,
      data(isActivePerceptionRequest),
      {
        method: "POST",
        body: { authorization_seconds: authorizationSeconds },
      },
    ),
  );
}

export function rejectActivePerception(id: string, reason?: string) {
  return unwrap(
    requestJson(
      `/api/active-perception/requests/${encodeURIComponent(id)}/reject`,
      data(isActivePerceptionRequest),
      {
        method: "POST",
        body: { reason },
      },
    ),
  );
}

export function executeActivePerception(id: string) {
  return unwrap(
    requestJson(
      `/api/active-perception/requests/${encodeURIComponent(id)}/execute`,
      data(isActivePerceptionRequest),
      {
        method: "POST",
      },
    ),
  );
}

export function expireActivePerceptionRequests() {
  return unwrap(
    requestJson(
      "/api/active-perception/requests/expire",
      data((value): value is { id: string; deleted: boolean; expired_count: number } => {
        return (
          isRecord(value) &&
          isString(value.id) &&
          isBoolean(value.deleted) &&
          isNumber(value.expired_count)
        );
      }),
      { method: "POST" },
    ),
  );
}

export { isJsonValue };
