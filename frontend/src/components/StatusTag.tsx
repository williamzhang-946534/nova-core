import { Tag } from "antd";

const colorByStatus = new Map([
  ["ok", "green"],
  ["healthy", "green"],
  ["completed", "green"],
  ["on", "green"],
  ["clear", "green"],
  ["running", "processing"],
  ["pending", "default"],
  ["planning", "processing"],
  ["waiting_confirmation", "warning"],
  ["degraded", "warning"],
  ["unavailable", "warning"],
  ["unknown", "default"],
  ["disconnected", "default"],
  ["failed", "red"],
  ["timed_out", "red"],
  ["cancelled", "default"],
  ["cooldown_skipped", "default"],
  ["condition_not_met", "default"],
  ["risk_rejected", "red"],
  ["confirmation_required", "warning"],
  ["permission_denied", "red"],
]);

export default function StatusTag({ status }: { status: string }) {
  return <Tag color={colorByStatus.get(status) ?? "default"}>{status.replace(/_/g, " ")}</Tag>;
}
