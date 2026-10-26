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
  if (typeof payload !== "object" || payload === null) {
    return {};
  }

  const error = (payload as Record<string, unknown>).error;
  if (typeof error !== "object" || error === null) {
    return {};
  }

  const candidate = error as Record<string, unknown>;
  return {
    code: candidate.code,
    message: candidate.message,
    correlationId: candidate.correlation_id,
  };
}

function errorMessage(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim().length > 0 ? value : fallback;
}

export async function requestJson<T>(
  path: string,
  validate: (value: unknown) => value is T,
): Promise<T> {
  const baseUrl = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
  let response: Response;

  try {
    response = await fetch(`${baseUrl.replace(/\/$/, "")}${path}`, {
      headers: {
        Accept: "application/json",
      },
    });
  } catch {
    throw new ApiError("无法连接后端服务。", { status: 0 });
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
