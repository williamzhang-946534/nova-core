import { buildQueryString, requestJson } from "./client";
import type { EventListQuery, EventListResponse } from "@/types/events";
import { isEventSummary } from "./system";
import { isNumber, isRecord } from "@/utils/validation";

export function listEvents(query: EventListQuery = {}): Promise<EventListResponse> {
  return requestJson(
    `/api/events${buildQueryString({ ...query })}`,
    (value): value is EventListResponse =>
      isRecord(value) &&
      Array.isArray(value.data) &&
      value.data.every(isEventSummary) &&
      isNumber(value.page) &&
      isNumber(value.page_size) &&
      isNumber(value.total),
  );
}

export function getEvent(eventId: string) {
  return requestJson<{ data: EventListResponse["data"][number] }>(
    `/api/events/${encodeURIComponent(eventId)}`,
    (value): value is { data: EventListResponse["data"][number] } =>
      isRecord(value) && isRecord(value.data) && isEventSummary(value.data),
  ).then((response) => response.data);
}
