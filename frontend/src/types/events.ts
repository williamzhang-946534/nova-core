import type { PageResponse } from "./common";
import type { EventSummary } from "./console";

export type { EventSummary };
export type EventListResponse = PageResponse<EventSummary>;

export interface EventListQuery {
  event_type?: string;
  source?: string;
  subject_type?: string;
  subject_id?: string;
  correlation_id?: string;
  start_time?: string;
  end_time?: string;
  order?: "asc" | "desc";
  page?: number;
  page_size?: number;
}
