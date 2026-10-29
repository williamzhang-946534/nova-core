import { Alert, Button } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { ApiError } from "@/api/client";

interface ApiErrorAlertProps {
  error: unknown;
  onRetry?: () => void;
  retrying?: boolean;
}

export default function ApiErrorAlert({ error, onRetry, retrying }: ApiErrorAlertProps) {
  const status = error instanceof ApiError ? error.status : undefined;
  const message =
    status === 401
      ? "Arvuno API 未授权。请先在系统设置中配置有效的访问令牌。"
      : status === 0
        ? "无法连接 Arvuno 后端服务。请确认后端进程已启动。"
        : error instanceof Error
          ? error.message
          : "请求 Arvuno API 失败。";

  return (
    <Alert
      type="error"
      showIcon
      message={status === 401 ? "未配置访问凭据" : "请求失败"}
      description={message}
      action={
        onRetry ? (
          <Button icon={<ReloadOutlined />} loading={retrying} onClick={onRetry}>
            重试
          </Button>
        ) : undefined
      }
    />
  );
}
