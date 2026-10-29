import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Descriptions, Spin, Tag, Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";

import { getHealth } from "@/api/health";

export default function SystemStatusPage() {
  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: getHealth,
  });

  if (healthQuery.isPending) {
    return (
      <section className="status-panel" aria-live="polite">
        <Spin tip="正在检查系统状态...">
          <div className="loading-surface" />
        </Spin>
      </section>
    );
  }

  if (healthQuery.isError) {
    return (
      <section className="status-panel" aria-live="polite">
        <Alert
          type="error"
          showIcon
          message="后端状态检查失败"
          description={healthQuery.error.message}
          action={
            <Button icon={<ReloadOutlined />} onClick={() => void healthQuery.refetch()}>
              重试
            </Button>
          }
        />
      </section>
    );
  }

  const health = healthQuery.data;

  return (
    <section className="status-panel" aria-live="polite">
      <Card
        title="系统状态"
        extra={
          <Button
            icon={<ReloadOutlined />}
            loading={healthQuery.isFetching}
            onClick={() => void healthQuery.refetch()}
          >
            刷新
          </Button>
        }
      >
        <Descriptions bordered size="small" column={{ xs: 1, sm: 1, md: 2 }}>
          <Descriptions.Item label="服务状态">
            <Tag color="green">正常</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="运行环境">
            <Tag>{health.environment}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="后端版本">{health.version}</Descriptions.Item>
          <Descriptions.Item label="检查时间">
            {new Date(health.checked_at).toLocaleString()}
          </Descriptions.Item>
        </Descriptions>
        <Typography.Text className="status-note" type="secondary">
          健康检查仅确认 Arvuno 后端进程可用。
        </Typography.Text>
      </Card>
    </section>
  );
}
