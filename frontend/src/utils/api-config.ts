const tokenStorageKey = "arvuno.api-token";
const baseUrlStorageKey = "arvuno.api-base-url";
const defaultBaseUrl = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

export function getApiToken(): string {
  return globalThis.localStorage?.getItem(tokenStorageKey) ?? "";
}

export function setApiToken(token: string): void {
  if (token.trim().length === 0) {
    globalThis.localStorage?.removeItem(tokenStorageKey);
  } else {
    globalThis.localStorage?.setItem(tokenStorageKey, token.trim());
  }
}

export function getApiBaseUrl(): string {
  return globalThis.localStorage?.getItem(baseUrlStorageKey) ?? defaultBaseUrl;
}

export function setApiBaseUrl(url: string): void {
  const normalized = url.trim().replace(/\/$/, "");
  if (normalized.length === 0 || normalized === defaultBaseUrl.replace(/\/$/, "")) {
    globalThis.localStorage?.removeItem(baseUrlStorageKey);
  } else {
    globalThis.localStorage?.setItem(baseUrlStorageKey, normalized);
  }
}

export function hasStoredApiToken(): boolean {
  return getApiToken().length > 0;
}
