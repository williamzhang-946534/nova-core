import { getApiBaseUrl, getApiToken } from "@/utils/api-config";
import { ApiError, requestJson } from "./client";
import type { AgentChatResult } from "@/types/agent";
import {
  isBoolean,
  isNumber,
  isOneOf,
  isRecord,
  isString,
  isStringOrNull,
} from "@/utils/validation";

export const voiceStates = [
  "completed",
  "waiting_confirmation",
  "failed",
  "cancelled",
  "not_instruction",
  "wake_word_not_detected",
] as const;

export type VoiceInteractionState = (typeof voiceStates)[number];

export interface VoiceRecognitionResult {
  id: string;
  media_asset_id: string;
  invocation_id: string;
  result_kind: string;
  result: Record<string, unknown>;
  confidence: number | null;
  model_id: string;
  model_version: string;
}

export interface VoiceInteractionResult {
  interaction_state: VoiceInteractionState;
  transcript: string | null;
  wake_word_detected: boolean | null;
  recognition: VoiceRecognitionResult | null;
  agent_result: AgentChatResult | null;
  task_id: string | null;
  reply: string | null;
  tts_asset_id: string | null;
  media_purged: boolean;
  details: Record<string, unknown>;
}

export interface VoiceState {
  supported_interaction_states: string[];
  microphone_capture_enabled: boolean;
  continuous_capture_enabled: boolean;
  capture_mode: string;
}

export interface VoiceUploadRequest {
  audio: Blob;
  environment_id: string;
  user_id: string;
  capture_consent_id: string;
  processing_consent_id: string;
  space_id?: string;
  tts_consent_id?: string;
  require_wake_word?: boolean;
  duration_ms?: number;
  client_captured_at?: string;
  client_time_source?: string;
  client_time_uncertainty_ms?: number;
}

function isRecognition(value: unknown): value is VoiceRecognitionResult {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.media_asset_id) &&
    isString(value.invocation_id) &&
    isString(value.result_kind) &&
    isRecord(value.result) &&
    (value.confidence === null || isNumber(value.confidence)) &&
    isString(value.model_id) &&
    isString(value.model_version)
  );
}

function isVoiceResult(value: unknown): value is VoiceInteractionResult {
  return (
    isRecord(value) &&
    isOneOf(value.interaction_state, voiceStates) &&
    isStringOrNull(value.transcript) &&
    (value.wake_word_detected === null || isBoolean(value.wake_word_detected)) &&
    (value.recognition === null || isRecognition(value.recognition)) &&
    (value.agent_result === null || isRecord(value.agent_result)) &&
    isStringOrNull(value.task_id) &&
    isStringOrNull(value.reply) &&
    isStringOrNull(value.tts_asset_id) &&
    isBoolean(value.media_purged) &&
    isRecord(value.details)
  );
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  const error = isRecord(payload) && isRecord(payload.error) ? payload.error : {};
  const message = isString(error.message) ? error.message : `语音请求失败：${response.status}`;
  return new ApiError(message, {
    status: response.status,
    code: isString(error.code) ? error.code : undefined,
    correlationId: isString(error.correlation_id) ? error.correlation_id : undefined,
  });
}

export async function processVoice(request: VoiceUploadRequest): Promise<VoiceInteractionResult> {
  const baseUrl = getApiBaseUrl().replace(/\/$/, "");
  const token = getApiToken();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (token.length > 0) {
    headers.Authorization = `Bearer ${token}`;
  }
  const body = new FormData();
  body.set("audio", request.audio, "speech.wav");
  body.set("environment_id", request.environment_id);
  body.set("user_id", request.user_id);
  body.set("capture_consent_id", request.capture_consent_id);
  body.set("processing_consent_id", request.processing_consent_id);
  if (request.space_id) body.set("space_id", request.space_id);
  if (request.tts_consent_id) body.set("tts_consent_id", request.tts_consent_id);
  if (request.require_wake_word !== undefined) {
    body.set("require_wake_word", String(request.require_wake_word));
  }
  if (request.duration_ms !== undefined) body.set("duration_ms", String(request.duration_ms));
  if (request.client_captured_at) body.set("client_captured_at", request.client_captured_at);
  if (request.client_time_source) body.set("client_time_source", request.client_time_source);
  if (request.client_time_uncertainty_ms !== undefined) {
    body.set("client_time_uncertainty_ms", String(request.client_time_uncertainty_ms));
  }

  let response: Response;
  try {
    response = await fetch(`${baseUrl}/api/chat/voice`, {
      method: "POST",
      headers,
      body,
    });
  } catch {
    throw new ApiError("无法连接 Arvuno 后端服务。", { status: 0 });
  }
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    throw await errorFromResponse(response);
  }
  if (!isRecord(payload) || !isVoiceResult(payload.data)) {
    throw new ApiError("后端返回的语音结果格式不符合预期。", { status: response.status });
  }
  return payload.data;
}

export function confirmVoiceTask(request: {
  environment_id: string;
  user_id: string;
  task_id: string;
  confirmation_token: string;
  confirmed: boolean;
  tts_consent_id?: string;
}): Promise<VoiceInteractionResult> {
  return requestJson<{ data: VoiceInteractionResult }>(
    "/api/chat/voice/confirmation",
    (value): value is { data: VoiceInteractionResult } =>
      isRecord(value) && isVoiceResult(value.data),
    { method: "POST", body: request },
  ).then((response) => response.data);
}

export function getVoiceState(): Promise<VoiceState> {
  return requestJson<VoiceState>(
    "/api/chat/voice/state",
    (value): value is VoiceState =>
      isRecord(value) &&
      Array.isArray(value.supported_interaction_states) &&
      value.supported_interaction_states.every(isString) &&
      isBoolean(value.microphone_capture_enabled) &&
      isBoolean(value.continuous_capture_enabled) &&
      isString(value.capture_mode),
  );
}

export async function getTtsAudio(assetId: string): Promise<Blob> {
  const baseUrl = getApiBaseUrl().replace(/\/$/, "");
  const token = getApiToken();
  const headers: Record<string, string> = { Accept: "audio/wav" };
  if (token.length > 0) {
    headers.Authorization = `Bearer ${token}`;
  }
  let response: Response;
  try {
    response = await fetch(
      `${baseUrl}/api/multimodal/media-assets/${encodeURIComponent(assetId)}/content`,
      { headers },
    );
  } catch {
    throw new ApiError("无法连接 Arvuno 后端服务。", { status: 0 });
  }
  if (!response.ok) {
    throw await errorFromResponse(response);
  }
  return response.blob();
}
