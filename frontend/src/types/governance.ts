import type { JsonRecord } from "./common";

export interface RetentionPolicy {
  name: string;
  label: string;
  enabled: boolean;
  interval_seconds: number;
  batch_size: number;
  rules: JsonRecord;
}

export interface RetentionRun {
  id: string;
  job_name: string;
  status: string;
  started_at: string;
  finished_at?: string | null;
  affected_count: number;
  error_code?: string | null;
  error_message?: string | null;
  details: JsonRecord;
  next_run_at?: string | null;
}

export interface RetentionStatus {
  single_process_only: boolean;
  jobs: Array<RetentionPolicy & { next_run_at?: string | null; last_run?: RetentionRun | null }>;
}

export interface MultimodalProvider {
  id: string;
  provider_name: string;
  capability: string;
  media_kinds: string[];
  processing_location: string;
  data_sent_policy: JsonRecord;
  model_id: string;
  model_version: string;
  max_bytes: number;
  max_duration_ms?: number | null;
  timeout_ms: number;
  requires_explicit_consent: boolean;
  is_default: boolean;
  priority: number;
  enabled: boolean;
}

export interface MultimodalCapabilities {
  camera_capture_enabled: boolean;
  microphone_capture_enabled: boolean;
  continuous_video_analysis_enabled: boolean;
  cloud_processing_enabled: boolean;
  providers: MultimodalProvider[];
}

export interface MultimodalConsent {
  id: string;
  environment_id: string;
  user_id: string;
  consent_type: string;
  modality: string;
  purpose: string;
  provider_name?: string | null;
  processing_locations: string[];
  space_ids: string[];
  granted_at: string;
  expires_at?: string | null;
  revoked_at?: string | null;
  status: string;
  scope: JsonRecord;
  evidence?: JsonRecord | null;
}

export interface MultimodalDataAccessGrant {
  id: string;
  environment_id: string;
  user_id: string;
  modalities: string[];
  space_ids: string[];
  granted_at: string;
  expires_at?: string | null;
  revoked_at?: string | null;
  status: string;
  scope: JsonRecord;
  evidence?: JsonRecord | null;
}

export interface MultimodalAuditEvent {
  id: string;
  environment_id?: string | null;
  actor_id?: string | null;
  action: string;
  subject_type?: string | null;
  subject_id?: string | null;
  details: JsonRecord;
  occurred_at: string;
}

export interface MultimodalExtraction {
  id: string;
  media_asset_id: string;
  invocation_id: string;
  result_kind: string;
  schema_version: string;
  result: JsonRecord;
  confidence?: number | null;
  confidence_level: string;
  quality_status: string;
  language?: string | null;
  model_id: string;
  model_version: string;
  valid_from: string;
  valid_until?: string | null;
}

export interface MultimodalConsentInput {
  environmentId: string;
  userId: string;
  consentType: string;
  modality: string;
  purpose: string;
  providerName?: string;
  spaceIds?: string[];
  expiresAt?: string;
}

export interface MultimodalDataAccessGrantInput {
  environmentId: string;
  userId: string;
  modalities: string[];
  spaceIds: string[];
  expiresAt?: string;
}
