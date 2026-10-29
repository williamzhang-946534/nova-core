import type { JsonRecord, PageResponse } from "./common";

export interface DevicePermission {
  allowed_actions: string[];
  max_risk_level: string;
  requires_confirmation: boolean;
}

export interface DeviceCapability {
  capability: string;
  actions: string[];
  parameters: JsonRecord;
  risk_level: string;
  requires_confirmation: boolean;
}

export interface Device {
  id: string;
  adapter_id: string;
  external_id: string;
  name: string;
  device_type: string;
  area?: string;
  capabilities: DeviceCapability[];
  risk_level: string;
  is_online: boolean;
  is_enabled: boolean;
  metadata: JsonRecord;
  aliases: string[];
  permissions: DevicePermission;
}

export interface DeviceStateSnapshot {
  device_id: string;
  external_id: string;
  state: string;
  attributes: JsonRecord;
  raw_state?: string | null;
  observed_at: string;
}

export interface DeviceDetail {
  device: Device;
  latest_state?: DeviceStateSnapshot | null;
  recent_events: EventSummary[];
}

export interface DeviceCurrentState {
  device_id: string;
  external_id: string;
  state: string;
  attributes: JsonRecord;
  raw_state?: string | null;
  observed_at: string;
  verified: boolean;
  from_cache: boolean;
}

export interface AdapterHealth {
  status: "healthy" | "degraded" | "disconnected";
  adapter_id: string;
  detail: string;
  checked_at: string;
}

export interface EventSummary {
  id: string;
  event_type: string;
  source: string;
  subject_type?: string | null;
  subject_id?: string | null;
  payload: JsonRecord;
  correlation_id?: string | null;
  occurred_at: string;
  created_at: string;
}

export interface SystemStatus {
  version: string;
  environment: string;
  database: "ok" | "error";
  adapters: AdapterHealth[];
  device_count: number;
  online_device_count: number;
  active_task_count: number;
  recent_error_events: EventSummary[];
  checked_at: string;
}

export interface DeviceContextState {
  device_id: string;
  name: string;
  device_type: string;
  area?: string | null;
  state: string;
  attributes: JsonRecord;
  updated_at: string;
}

export interface SensorContextState {
  device_id: string;
  sensor_type: string;
  value: string | number | boolean;
  unit?: string | null;
  updated_at: string;
}

export interface EnvironmentContext {
  environment_id?: string | null;
  environment_name: string;
  devices: Record<string, DeviceContextState>;
  sensors: Record<string, SensorContextState>;
  updated_at: string;
}

export interface EnvironmentAreaSummary {
  device_count: number;
  online_device_count: number;
  unavailable_device_ids: string[];
}

export interface EnvironmentSummaryData {
  environment: EnvironmentContext;
  areas: Record<string, EnvironmentAreaSummary>;
  online_device_count: number;
  unavailable_device_ids: string[];
  active_task_count: number;
  recent_events: EventSummary[];
}

export interface EnvironmentSnapshot {
  id: string;
  environment_id: string;
  context: JsonRecord;
  active_task_ids: string[];
  anomaly_count: number;
  created_at: string;
}

export interface WebConsoleSettings {
  event_poll_interval_seconds: number;
}

export interface RuntimeSettings {
  app_name: string;
  environment: string;
  ai_provider: "mock" | "openai_compatible";
  home_assistant_configured: boolean;
  home_assistant_write_enabled: boolean;
  home_assistant_entity_limit: number;
  device_poll_interval_seconds: number;
  event_retention_days: number;
  diagnostic_event_retention_days: number;
  default_environment_name: string;
}

export interface SystemSettings {
  runtime: RuntimeSettings;
  web_console: WebConsoleSettings;
}

export interface DeviceListQuery {
  area?: string;
  device_type?: string;
  online?: boolean;
  keyword?: string;
  page?: number;
  page_size?: number;
}

export type DeviceListResponse = PageResponse<Device>;
