import { requestJson } from "./client";
import { isHealthResponse, type HealthResponse } from "@/types/health";

export function getHealth(): Promise<HealthResponse> {
  return requestJson("/health", isHealthResponse);
}
