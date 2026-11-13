import { buildQueryString, requestJson } from "./client";
import type {
  MultimodalAuditEvent,
  MultimodalCapabilities,
  MultimodalConsent,
  MultimodalConsentInput,
  MultimodalDataAccessGrant,
  MultimodalDataAccessGrantInput,
  MultimodalExtraction,
  MultimodalProvider,
  RetentionRun,
  RetentionPolicy,
  RetentionStatus,
} from "@/types/governance";
import {
  isBoolean,
  isNumber,
  isNumberOrNull,
  isRecord,
  isString,
  isStringArray,
  isStringOrNull,
} from "@/utils/validation";

function isPolicy(value: unknown): value is RetentionPolicy {
  return (
    isRecord(value) &&
    isString(value.name) &&
    isString(value.label) &&
    isBoolean(value.enabled) &&
    isNumber(value.interval_seconds) &&
    isNumber(value.batch_size) &&
    isRecord(value.rules)
  );
}

function isRun(value: unknown): value is RetentionRun {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.job_name) &&
    isString(value.status) &&
    isString(value.started_at) &&
    isStringOrNull(value.finished_at) &&
    isNumber(value.affected_count) &&
    isStringOrNull(value.error_code) &&
    isStringOrNull(value.error_message) &&
    isRecord(value.details) &&
    isStringOrNull(value.next_run_at)
  );
}

function isCapabilities(value: unknown): value is MultimodalCapabilities {
  return (
    isRecord(value) &&
    isBoolean(value.camera_capture_enabled) &&
    isBoolean(value.microphone_capture_enabled) &&
    isBoolean(value.continuous_video_analysis_enabled) &&
    isBoolean(value.cloud_processing_enabled) &&
    Array.isArray(value.providers) &&
    value.providers.every(isProvider)
  );
}

function isProvider(value: unknown): value is MultimodalProvider {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.provider_name) &&
    isString(value.capability) &&
    isStringArray(value.media_kinds) &&
    isString(value.processing_location) &&
    isRecord(value.data_sent_policy) &&
    isString(value.model_id) &&
    isString(value.model_version) &&
    isNumber(value.max_bytes) &&
    isNumberOrNull(value.max_duration_ms) &&
    isNumber(value.timeout_ms) &&
    isBoolean(value.requires_explicit_consent) &&
    isBoolean(value.is_default) &&
    isNumber(value.priority) &&
    isBoolean(value.enabled)
  );
}

function isConsent(value: unknown): value is MultimodalConsent {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.environment_id) &&
    isString(value.user_id) &&
    isString(value.consent_type) &&
    isString(value.modality) &&
    isString(value.purpose) &&
    isStringOrNull(value.provider_name) &&
    isStringArray(value.processing_locations) &&
    isStringArray(value.space_ids) &&
    isString(value.granted_at) &&
    isStringOrNull(value.expires_at) &&
    isStringOrNull(value.revoked_at) &&
    isString(value.status) &&
    isRecord(value.scope)
  );
}

function isGrant(value: unknown): value is MultimodalDataAccessGrant {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.environment_id) &&
    isString(value.user_id) &&
    isStringArray(value.modalities) &&
    isStringArray(value.space_ids) &&
    isString(value.granted_at) &&
    isStringOrNull(value.expires_at) &&
    isStringOrNull(value.revoked_at) &&
    isString(value.status) &&
    isRecord(value.scope)
  );
}

function isAuditEvent(value: unknown): value is MultimodalAuditEvent {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isStringOrNull(value.environment_id) &&
    isStringOrNull(value.actor_id) &&
    isString(value.action) &&
    isStringOrNull(value.subject_type) &&
    isStringOrNull(value.subject_id) &&
    isRecord(value.details) &&
    isString(value.occurred_at)
  );
}

function isExtraction(value: unknown): value is MultimodalExtraction {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.media_asset_id) &&
    isString(value.invocation_id) &&
    isString(value.result_kind) &&
    isString(value.schema_version) &&
    isRecord(value.result) &&
    isNumberOrNull(value.confidence) &&
    isString(value.confidence_level) &&
    isString(value.quality_status) &&
    isStringOrNull(value.language) &&
    isString(value.model_id) &&
    isString(value.model_version) &&
    isString(value.valid_from) &&
    isStringOrNull(value.valid_until)
  );
}

export function listRetentionPolicies(): Promise<RetentionPolicy[]> {
  return requestJson<{ data: { policies: RetentionPolicy[] } }>(
    "/api/retention/policies",
    (
      value,
    ): value is {
      data: { policies: RetentionPolicy[] };
    } =>
      isRecord(value) &&
      isRecord(value.data) &&
      Array.isArray(value.data.policies) &&
      value.data.policies.every(isPolicy),
  ).then((response) => response.data.policies);
}

export function getRetentionStatus(): Promise<RetentionStatus> {
  return requestJson<{ data: RetentionStatus }>(
    "/api/retention/status",
    (value): value is { data: RetentionStatus } => {
      return (
        isRecord(value) &&
        isRecord(value.data) &&
        isBoolean(value.data.single_process_only) &&
        Array.isArray(value.data.jobs) &&
        value.data.jobs.every((job) => {
          if (!isRecord(job) || !isPolicy(job)) {
            return false;
          }
          return (
            (job.last_run === null || job.last_run === undefined || isRun(job.last_run)) &&
            isStringOrNull(job.next_run_at)
          );
        })
      );
    },
  ).then((response) => response.data);
}

export function listRetentionFailures(limit = 50): Promise<RetentionRun[]> {
  return requestJson<{ data: { failures: RetentionRun[] } }>(
    `/api/retention/failures${buildQueryString({ limit })}`,
    (value): value is { data: { failures: RetentionRun[] } } =>
      isRecord(value) &&
      isRecord(value.data) &&
      Array.isArray(value.data.failures) &&
      value.data.failures.every(isRun),
  ).then((response) => response.data.failures);
}

export function runRetention(
  jobs: string[],
): Promise<{ executed: string[]; jobs: RetentionRun[] }> {
  return requestJson<{ data: { executed: string[]; jobs: RetentionRun[] } }>(
    "/api/retention/run",
    (value): value is { data: { executed: string[]; jobs: RetentionRun[] } } =>
      isRecord(value) &&
      isRecord(value.data) &&
      isStringArray(value.data.executed) &&
      Array.isArray(value.data.jobs) &&
      value.data.jobs.every(isRun),
    { method: "POST", body: { jobs } },
  ).then((response) => response.data);
}

export function getMultimodalCapabilities(): Promise<MultimodalCapabilities> {
  return requestJson<{ data: MultimodalCapabilities }>(
    "/api/multimodal/capabilities",
    (
      value,
    ): value is {
      data: MultimodalCapabilities;
    } => isRecord(value) && isCapabilities(value.data),
  ).then((response) => response.data);
}

export function listMultimodalProviders(): Promise<MultimodalProvider[]> {
  return requestJson<MultimodalProvider[]>(
    "/api/multimodal/providers",
    (value): value is MultimodalProvider[] => {
      return Array.isArray(value) && value.every(isProvider);
    },
  );
}

export function listMultimodalConsents(environmentId?: string): Promise<MultimodalConsent[]> {
  return requestJson<MultimodalConsent[]>(
    `/api/multimodal/consents${buildQueryString({ environment_id: environmentId })}`,
    (value): value is MultimodalConsent[] => Array.isArray(value) && value.every(isConsent),
  );
}

export function createMultimodalConsent(input: MultimodalConsentInput): Promise<MultimodalConsent> {
  return requestJson<{ data: MultimodalConsent }>(
    "/api/multimodal/consents",
    (value): value is { data: MultimodalConsent } => {
      return isRecord(value) && isConsent(value.data);
    },
    {
      method: "POST",
      body: {
        environment_id: input.environmentId,
        user_id: input.userId,
        consent_type: input.consentType,
        modality: input.modality,
        purpose: input.purpose,
        provider_name: input.providerName,
        processing_locations: ["local"],
        space_ids: input.spaceIds ?? [],
        expires_at: input.expiresAt,
      },
    },
  ).then((response) => response.data);
}

export function revokeMultimodalConsent(id: string): Promise<MultimodalConsent> {
  return requestJson<{ data: MultimodalConsent }>(
    `/api/multimodal/consents/${encodeURIComponent(id)}/revoke`,
    (value): value is { data: MultimodalConsent } => isRecord(value) && isConsent(value.data),
    { method: "POST", body: {} },
  ).then((response) => response.data);
}

export function listMultimodalGrants(environmentId?: string): Promise<MultimodalDataAccessGrant[]> {
  return requestJson<MultimodalDataAccessGrant[]>(
    `/api/multimodal/data-access-grants${buildQueryString({ environment_id: environmentId })}`,
    (value): value is MultimodalDataAccessGrant[] => Array.isArray(value) && value.every(isGrant),
  );
}

export function createMultimodalGrant(
  input: MultimodalDataAccessGrantInput,
): Promise<MultimodalDataAccessGrant> {
  return requestJson<{ data: MultimodalDataAccessGrant }>(
    "/api/multimodal/data-access-grants",
    (
      value,
    ): value is {
      data: MultimodalDataAccessGrant;
    } => isRecord(value) && isGrant(value.data),
    {
      method: "POST",
      body: {
        environment_id: input.environmentId,
        user_id: input.userId,
        modalities: input.modalities,
        space_ids: input.spaceIds,
        expires_at: input.expiresAt,
      },
    },
  ).then((response) => response.data);
}

export function revokeMultimodalGrant(id: string): Promise<MultimodalDataAccessGrant> {
  return requestJson<{ data: MultimodalDataAccessGrant }>(
    `/api/multimodal/data-access-grants/${encodeURIComponent(id)}/revoke`,
    (value): value is { data: MultimodalDataAccessGrant } => isRecord(value) && isGrant(value.data),
    { method: "POST", body: {} },
  ).then((response) => response.data);
}

export function listMultimodalAuditEvents(
  environmentId: string,
  action?: string,
  limit = 100,
): Promise<MultimodalAuditEvent[]> {
  return requestJson<MultimodalAuditEvent[]>(
    `/api/multimodal/audit-events${buildQueryString({ environment_id: environmentId, action, limit })}`,
    (value): value is MultimodalAuditEvent[] => Array.isArray(value) && value.every(isAuditEvent),
  );
}

export function listMultimodalExtractions(): Promise<MultimodalExtraction[]> {
  return requestJson<MultimodalExtraction[]>(
    "/api/multimodal/extraction-results",
    (value): value is MultimodalExtraction[] => {
      return Array.isArray(value) && value.every(isExtraction);
    },
  );
}

export function purgeMultimodalAsset(id: string): Promise<{ id: string; purge_status: string }> {
  return requestJson<{ data: { id: string; purge_status: string } }>(
    `/api/multimodal/media-assets/${encodeURIComponent(id)}/purge`,
    (value): value is { data: { id: string; purge_status: string } } =>
      isRecord(value) &&
      isRecord(value.data) &&
      isString(value.data.id) &&
      isString(value.data.purge_status),
    { method: "POST", body: {} },
  ).then((response) => response.data);
}
