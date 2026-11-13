export const robotCapabilityNames = [
  "navigate_to",
  "observe",
  "inspect",
  "speak",
  "listen",
  "return_to_dock",
  "charge",
  "report_status",
  "look_at",
  "observe_scene",
  "request_safe_stop",
  "enter_idle_pose",
] as const;

export type RobotCapabilityName = (typeof robotCapabilityNames)[number];

export type RobotDataCategory = "camera" | "microphone" | "speaker" | "motion";

export interface RobotDeviceStates {
  camera: string;
  microphone: string;
  speaker: string;
}

export interface Robot {
  id: string;
  adapter_id: string;
  external_id: string;
  name: string;
  profile: string | null;
  hardware_version: string | null;
  firmware_version: string | null;
  edge_runtime_version: string | null;
  is_enabled: boolean;
  connection_state: string;
  is_online: boolean;
  motion_safety_state: string;
  emergency_stop: boolean;
  manual_takeover: boolean;
  battery_percent: number | null;
  low_battery_percent: number;
  device_states: RobotDeviceStates;
  space_id: string | null;
  last_seen_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface RobotCapability {
  robot_id: string | null;
  capability: RobotCapabilityName;
  schema_version: string;
  verification_status: string;
  discovered: boolean;
  supported: boolean;
  enabled: boolean;
  approved: boolean;
  consent_granted: boolean;
  executable: boolean;
  runtime_enabled: boolean;
  risk_level: string;
  requires_confirmation: boolean;
  requires_consents: RobotDataCategory[];
}

export interface RobotConsent {
  id: string;
  robot_id: string;
  capability: RobotCapabilityName;
  data_category: RobotDataCategory;
  space_id: string | null;
  status: "granted" | "revoked" | "expired";
  granted_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  grant_source: string;
  granted_by: string;
}

export interface RobotConsentGrantInput {
  capability: RobotCapabilityName;
  data_category: RobotDataCategory;
  space_id?: string;
  expires_at?: string;
  grant_source: string;
  granted_by: string;
}

export interface RobotRuntimeStatus {
  robot_id: string;
  state:
    "online" | "offline" | "stale" | "busy" | "idle" | "error" | "emergency_stopped" | "unknown";
  connection_state: string;
  motion_safety_state: string;
  is_fresh: boolean;
  last_seen_at: string | null;
  last_evaluated_at: string;
  heartbeat_timeout_seconds: number;
  active_task_count: number;
  error_code: string | null;
}

export interface RobotEvent {
  id: string;
  robot_id: string;
  task_request_id: string | null;
  event_type: string;
  severity: "info" | "warning" | "critical";
  source: string;
  payload: Record<string, unknown>;
  occurred_at: string;
  received_at: string;
  late_arrival: boolean;
  correlation_id: string | null;
}

export interface RobotTaskRequest {
  id: string;
  robot_id: string;
  capability: RobotCapabilityName;
  status: string;
  parameters: Record<string, unknown>;
  requested_by: string;
  origin_type: string;
  task_id: string | null;
  task_step_id: string | null;
  tool_execution_id: string | null;
  idempotency_key: string | null;
  confirmed_by_user: boolean;
  requires_confirmation: boolean;
  result: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
  timeout_seconds: number;
  correlation_id: string | null;
  created_at: string;
  submitted_at: string | null;
  completed_at: string | null;
  updated_at: string;
}
