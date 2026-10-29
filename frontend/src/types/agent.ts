import type { JsonRecord } from "./common";

export interface AgentConfirmation {
  tool_name: string;
  risk_level: string;
  input: JsonRecord;
}

export interface AgentChatResult {
  status: "completed" | "waiting_confirmation" | "failed" | "cancelled";
  reply: string;
  intent?: string | null;
  task_id?: string | null;
  provider_log_id?: string | null;
  correlation_id: string;
  client_request_id?: string | null;
  confirmation_token?: string | null;
  confirmation?: AgentConfirmation | null;
  error?: {
    code: string;
    message: string;
    details?: JsonRecord;
  } | null;
}
