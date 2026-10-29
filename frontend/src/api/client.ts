import { getApiBaseUrl, getApiToken } from "@/utils/api-config";

export interface ApiErrorBody {
  code?: unknown;
  message?: unknown;
  correlationId?: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | undefined;
  readonly correlationId: string | undefined;

  constructor(message: string, options: { status: number; code?: string; correlationId?: string }) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code;
    this.correlationId = options.correlationId;
  }
}

function readErrorField(payload: unknown): ApiErrorBody {
  if (!isRecordPayload(payload)) {
    return {};
  }
  const error = payload.error;
  if (!isRecordPayload(error)) {
    return {};
  }
  return {
    code: error.code,
    message: error.message,
    correlationId: error.correlation_id,
  };
}

function isRecordPayload(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function errorMessage(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim().length > 0 ? value : fallback;
}

export interface RequestJsonOptions {
  method?: "GET" | "POST" | "PATCH";
  body?: unknown;
}

export async function requestJson<T>(
  path: string,
  validate: (value: unknown) => value is T,
  options: RequestJsonOptions = {},
): Promise<T> {
  const baseUrl = getApiBaseUrl().replace(/\/$/, "");
  const token = getApiToken();
  const headers: Record<string, string> = {
    Accept: "application/json",
  };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (token.length > 0) {
    headers.Authorization = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch {
    throw new ApiError("无法连接 Arvuno 后端服务。", { status: 0 });
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const error = readErrorField(payload);
    throw new ApiError(errorMessage(error.message, `后端请求失败：${response.status}`), {
      status: response.status,
      code: typeof error.code === "string" ? error.code : undefined,
      correlationId: typeof error.correlationId === "string" ? error.correlationId : undefined,
    });
  }

  if (!validate(payload)) {
    throw new ApiError("后端返回的数据格式不符合预期。", { status: response.status });
  }
  return payload;
}

export function buildQueryString(
  parameters: Record<string, string | number | boolean | undefined>,
) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(parameters)) {
    if (value !== undefined && `${value}`.length > 0) {
      query.set(key, `${value}`);
    }
  }
  const encoded = query.toString();
  return encoded.length > 0 ? `?${encoded}` : "";
}
