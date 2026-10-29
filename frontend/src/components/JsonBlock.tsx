import { Typography } from "antd";

import { formatJson } from "@/utils/format";
export default function JsonBlock({ value }: { value: unknown }) {
  return (
    <Typography.Paragraph className="json-block" copyable={{ text: formatJson(value) }}>
      <pre>{formatJson(value)}</pre>
    </Typography.Paragraph>
  );
}
