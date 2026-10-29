import type { JsonRecord, PageResponse } from "./common";

export type TaskStatus =
  | "pending"
  | "planning"
  | "waiting_confirmation"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type TaskStepStatus =
  | "pending"
  | "running"
  | "waiting_confirmation"
  | "completed"
  | "failed"
  | "timed_out"
  | "cancelled";

export interface TaskError {
  code: string;
  message: string;
  details?: JsonRecord;
}

export interface Task {
  id: string;
  task_type: string;
  title: string;
  description?: string | null;
  status: TaskStatus;
  origin: string;
  conversation_id?: string | null;
  plan: JsonRecord;
  result?: JsonRecord | null;
  error?: TaskError | null;
  correlation_id?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface TaskStep {
  id: string;
  task_id: string;
  step_index: number;
  name: string;
  description?: string | null;
  tool_name?: string | null;
  status: TaskStepStatus;
  input?: JsonRecord | null;
  output?: JsonRecord | null;
  error?: TaskError | null;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface ToolExecution {
  id: string;
  tool_name: string;
  task_id?: string | null;
  task_step_id?: string | null;
  status: string;
  input: JsonRecord;
  output?: JsonRecord | null;
  validation?: JsonRecord | null;
  risk_level: string;
  permission_result: string;
  error?: TaskError | null;
  correlation_id?: string | null;
  started_at: string;
  completed_at?: string | null;
  duration_ms?: number | null;
}

export interface TaskDetail extends Task {
  steps: TaskStep[];
  executions: ToolExecution[];
}

export interface TaskListQuery {
  status?: TaskStatus;
  task_type?: string;
  conversation_id?: string;
  start_time?: string;
  end_time?: string;
  page?: number;
  page_size?: number;
}

export type TaskListResponse = PageResponse<Task>;
