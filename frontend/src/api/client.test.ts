import { afterEach, expect, test, vi } from "vitest";

import { ApiError, DEFAULT_REQUEST_TIMEOUT_MS, requestJson } from "./client";

vi.mock("@/utils/api-config", () => ({
  getApiBaseUrl: () => "http://127.0.0.1:8000/",
  getApiToken: () => "test-token",
}));

const fetchMock = vi.fn();

vi.stubGlobal("fetch", fetchMock);

afterEach(() => {
  fetchMock.mockReset();
  vi.useRealTimers();
});

test("requestJson aborts a request after the default timeout", async () => {
  vi.useFakeTimers();
  fetchMock.mockImplementation(
    (_input: string, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          const error = new Error("The request was aborted.");
          error.name = "AbortError";
          reject(error);
        });
      }),
  );

  const request = requestJson("/health", (_value: unknown): _value is unknown => true);
  const rejection = expect(request).rejects.toMatchObject({
    name: "ApiError",
    message: "Arvuno 后端服务请求超时。",
    status: 0,
  } satisfies Partial<ApiError>);
  await vi.advanceTimersByTimeAsync(DEFAULT_REQUEST_TIMEOUT_MS - 1);
  fetchMock.mock.calls.forEach(([, init]) => {
    expect((init as RequestInit).signal).toBeInstanceOf(AbortSignal);
  });
  await vi.advanceTimersByTimeAsync(1);

  await rejection;
});
