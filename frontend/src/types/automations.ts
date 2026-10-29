import type { JsonRecord, PageResponse } from "./common";

export type AutomationEventType = "device_state_changed" | "sensor_updated" | "device_unavailable";

export type ConditionOperator = "eq" | "ne" | "gt" | "gte" | "lt" | "lte" | "contains" | "in";

export type AutomationRiskLevel = "read_only" | "low_risk" | "medium_risk" | "high_risk";

export interface AutomationTrigger {
  event_type: AutomationEventType;
  subject_id: string | null;
}

export interface AutomationCondition {
  field: string;
  operator: ConditionOperator;
  value: unknown;
}

export interface AutomationNotificationAction {
  type: "notification";
  title: string;
  message: string;
  level: "info" | "warning" | "error";
}

export interface AutomationToolAction {
  type: "tool";
  tool_name: string;
  input: JsonRecord;
  title: string;
  risk_level: AutomationRiskLevel;
}

export type AutomationAction = AutomationNotificationAction | AutomationToolAction;

export interface Automation {
  id: string;
  name: string;
  description: string | null;
  enabled: boolean;
  trigger: AutomationTrigger;
  conditions: AutomationCondition[];
  action: AutomationAction;
  cooldown_seconds: number;
  risk_level: AutomationRiskLevel;
  created_at: string;
  updated_at: string;
}

export interface AutomationUpdate {
  name?: string;
  description?: string | null;
  enabled?: boolean;
  cooldown_seconds?: number;
}

export type AutomationRunStatus =
  "running" | "completed" | "failed" | "cooldown_skipped" | "condition_not_met" | "risk_rejected";

export interface AutomationRun {
  id: string;
  automation_id: string;
  event_id: string | null;
  status: AutomationRunStatus;
  matched_context: JsonRecord;
  task_id: string | null;
  notification_id: string | null;
  error: JsonRecord | null;
  started_at: string;
  completed_at: string | null;
}

export type NotificationLevel = "info" | "warning" | "error";
export type NotificationStatus = "sent" | "read";

export interface ConsoleNotification {
  id: string;
  channel: string;
  title: string;
  content: string;
  level: NotificationLevel;
  status: NotificationStatus;
  related_event_id: string | null;
  related_task_id: string | null;
  created_at: string;
  sent_at: string | null;
}

export interface AutomationListQuery {
  enabled?: boolean;
  page?: number;
  page_size?: number;
}

export interface AutomationRunListQuery {
  page?: number;
  page_size?: number;
}

export interface NotificationListQuery {
  level?: NotificationLevel;
  unread_only?: boolean;
  page?: number;
  page_size?: number;
}

export type AutomationListResponse = PageResponse<Automation>;
export type AutomationRunListResponse = PageResponse<AutomationRun>;
export type NotificationListResponse = PageResponse<ConsoleNotification>;
