import { requestJson } from "./client";
import type { AgentChatResult } from "@/types/agent";
import { isRecord, isString } from "@/utils/validation";

export interface ChatRequest {
  message: string;
  client_request_id: string;
}

export function sendChat(request: ChatRequest): Promise<AgentChatResult> {
  return requestJson<{ data: AgentChatResult }>(
    "/api/chat",
    (
      value,
    ): value is {
      data: AgentChatResult;
    } => {
      if (!isRecord(value) || !isRecord(value.data)) {
        return false;
      }
      const result = value.data;
      return (
        isString(result.status) &&
        ["completed", "waiting_confirmation", "failed", "cancelled"].includes(result.status) &&
        isString(result.reply) &&
        (result.intent === undefined || result.intent === null || isString(result.intent)) &&
        (result.task_id === undefined || result.task_id === null || isString(result.task_id)) &&
        isString(result.correlation_id) &&
        (result.client_request_id === undefined ||
          result.client_request_id === null ||
          isString(result.client_request_id)) &&
        (result.confirmation_token === undefined ||
          result.confirmation_token === null ||
          isString(result.confirmation_token)) &&
        (result.provider_log_id === undefined ||
          result.provider_log_id === null ||
          isString(result.provider_log_id)) &&
        (result.confirmation === undefined ||
          result.confirmation === null ||
          (isRecord(result.confirmation) &&
            isString(result.confirmation.tool_name) &&
            isString(result.confirmation.risk_level) &&
            isRecord(result.confirmation.input))) &&
        (result.error === undefined ||
          result.error === null ||
          (isRecord(result.error) && isString(result.error.code) && isString(result.error.message)))
      );
    },
    { method: "POST", body: request },
  ).then((response) => response.data);
}
