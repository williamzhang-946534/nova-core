export type JsonValue = string | number | boolean | null | JsonRecord | JsonValue[];

export interface JsonRecord {
  [key: string]: JsonValue;
}

export interface PageResponse<T> {
  data: T[];
  page: number;
  page_size: number;
  total: number;
}
