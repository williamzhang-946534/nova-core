export type HealthStatus = "ok";

export interface HealthResponse {
  status: HealthStatus;
  version: string;
  environment: string;
  checked_at: string;
}

export function isHealthResponse(value: unknown): value is HealthResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const candidate = value as Record<string, unknown>;
  return (
    candidate.status === "ok" &&
    typeof candidate.version === "string" &&
    typeof candidate.environment === "string" &&
    typeof candidate.checked_at === "string"
  );
}
