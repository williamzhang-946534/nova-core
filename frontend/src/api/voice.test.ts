import { afterEach, expect, test, vi } from "vitest";

import { ApiError, fetchWithTimeout } from "./client";
import { getTtsAudio, processVoice } from "./voice";

vi.mock("@/utils/api-config", () => ({
  getApiBaseUrl: () => "http://127.0.0.1:8000/",
  getApiToken: () => "test-token",
}));

const fetchMock = vi.fn();

vi.stubGlobal("fetch", fetchMock);

afterEach(() => {
  fetchMock.mockReset();
});

test("voice upload reads an error response body only once", async () => {
  const json = vi.fn().mockResolvedValue({
    error: {
      code: "VOICE_FAILED",
      message: "语音处理失败。",
      correlation_id: "correlation-1",
    },
  });
  fetchMock.mockResolvedValue({
    ok: false,
    status: 503,
    json,
  });

  const request = requestVoiceUpload();
  await expect(processVoice(request)).rejects.toMatchObject({
    name: "ApiError",
    message: "语音处理失败。",
    status: 503,
    code: "VOICE_FAILED",
    correlationId: "correlation-1",
  } satisfies Partial<ApiError>);
  expect(json).toHaveBeenCalledTimes(1);
  expect(fetchMock.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
});

test("tts media requests have a timeout and parse errors once", async () => {
  const json = vi.fn().mockResolvedValue({
    error: { code: "MEDIA_NOT_FOUND", message: "媒体不存在。" },
  });
  fetchMock.mockResolvedValue({
    ok: false,
    status: 404,
    json,
  });

  await expect(getTtsAudio("asset-1")).rejects.toMatchObject({
    name: "ApiError",
    message: "媒体不存在。",
    status: 404,
    code: "MEDIA_NOT_FOUND",
  } satisfies Partial<ApiError>);
  expect(json).toHaveBeenCalledTimes(1);
  expect(fetchMock.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
});

test("fetchWithTimeout exposes an abort signal", async () => {
  fetchMock.mockResolvedValue({ ok: true });

  await fetchWithTimeout("http://127.0.0.1:8000/health");

  expect(fetchMock.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
});

test("tts audio responses are returned without reading the body as JSON", async () => {
  const blob = new Blob(["audio"], { type: "audio/wav" });
  fetchMock.mockResolvedValue({
    ok: true,
    blob: () => Promise.resolve(blob),
  });

  await expect(getTtsAudio("asset-1")).resolves.toBe(blob);
  expect(fetchMock.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
});

function requestVoiceUpload() {
  return {
    audio: new Blob(["audio"], { type: "audio/wav" }),
    environment_id: "environment-1",
    user_id: "user-1",
    capture_consent_id: "capture-consent",
    processing_consent_id: "processing-consent",
  };
}
