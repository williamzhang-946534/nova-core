export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function formatJson(value: unknown): string {
  if (value === null || value === undefined) {
    return "-";
  }
  return JSON.stringify(value, null, 2);
}

export function formatDeviceType(value: string): string {
  return value.replace(/^sensor_/, "").replace(/_/g, " ");
}
