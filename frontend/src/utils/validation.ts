import type { JsonRecord } from "@/types/common";

export function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isJsonValue(value: unknown): value is unknown {
  return (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean" ||
    (Array.isArray(value) && value.every(isJsonValue)) ||
    (isRecord(value) && Object.values(value).every(isJsonValue))
  );
}

export function isString(value: unknown): value is string {
  return typeof value === "string";
}

export function isOptionalString(value: unknown): value is string | undefined {
  return value === undefined || isString(value);
}

export function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function isBoolean(value: unknown): value is boolean {
  return typeof value === "boolean";
}

export function isNumberOrNull(value: unknown): value is number | null {
  return value === null || isNumber(value);
}

export function isStringOrNull(value: unknown): value is string | null {
  return value === null || isString(value);
}

export function isRecordOrNull(value: unknown): value is JsonRecord | null {
  return value === null || isRecord(value);
}

export function isOneOf<T extends readonly [string, ...string[]]>(
  value: unknown,
  values: T,
): value is T[number] {
  return isString(value) && values.includes(value);
}

export function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isString);
}

export function hasFields(value: unknown, keys: string[]): value is JsonRecord {
  return isRecord(value) && keys.every((key) => key in value);
}
