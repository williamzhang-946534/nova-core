import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Descriptions, Empty, List, Space, Statistic, Tag } from "antd";
import { ReloadOutlined } from "@ant-design/icons";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import PageLoading from "@/components/PageLoading";
import StatusTag from "@/components/StatusTag";
import { getSystemStatus } from "@/api/system";
import { getEnvironment } from "@/api/environment";
import { formatDateTime, formatJson } from "@/utils/format";

export default function SystemOverviewPage() {
  const statusQuery = useQuery({ queryKey: ["system-status"], queryFn: getSystemStatus });
  const environmentQuery = useQuery({ queryKey: ["environment"], queryFn: getEnvironment });

  if (statusQuery.isPending) {
    return <PageLoading text="正在读取系统状态..." />;
  }

  if (statusQuery.isError) {
    return (
      <ApiErrorAlert
        error={statusQuery.error}
        onRetry={() => void statusQuery.refetch()}
        retrying={statusQuery.isFetching}
      />
    );
  }

  const status = statusQuery.data;
  const environment = environmentQuery.data;

  return (
    <section className="page-stack">
      <header className="page-header">
        <div>
          <h1>系统概览</h1>
          <p>Arvuno Core 运行状态、适配器与当前环境摘要。</p>
        </div>
        <Button
          icon={<ReloadOutlined />}
          loading={statusQuery.isFetching || environmentQuery.isFetching}
          onClick={() => {
            void statusQuery.refetch();
            void environmentQuery.refetch();
          }}
        >
          刷新
        </Button>
      </header>

      {status.database === "error" ? (
        <Alert
          type="error"
          showIcon
          message="数据库不可用"
          description="请检查 SQLite 数据库配置和后端日志。"
        />
      ) : null}
      {environmentQuery.isError ? <ApiErrorAlert error={environmentQuery.error} /> : null}

      <div className="metric-grid">
        <Card>
          <Statistic title="后端版本" value={status.version} />
          <p className="metric-note">{status.environment}</p>
        </Card>
        <Card>
          <Statistic title="设备投影" value={status.device_count} suffix="台" />
          <p className="metric-note">{status.online_device_count} 台在线</p>
        </Card>
        <Card>
          <Statistic title="活动任务" value={status.active_task_count} suffix="个" />
          <p className="metric-note">{environment?.active_task_count ?? "-"} 个环境上下文记录</p>
        </Card>
        <Card>
          <Statistic
            title="环境设备"
            value={environment ? environment.online_device_count : "-"}
            suffix="在线"
          />
          <p className="metric-note">
            更新于 {formatDateTime(environment?.environment.updated_at)}
          </p>
        </Card>
      </div>

      <div className="two-column">
        <Card title="适配器状态">
          <List
            dataSource={status.adapters}
            renderItem={(adapter) => (
              <List.Item>
                <List.Item.Meta
                  title={
                    <Space>
                      <span>{adapter.adapter_id}</span>
                      <StatusTag status={adapter.status} />
                    </Space>
                  }
                  description={adapter.detail || "状态正常"}
                />
                <span className="table-time">{formatDateTime(adapter.checked_at)}</span>
              </List.Item>
            )}
          />
        </Card>
        <Card title="最近任务失败">
          {status.recent_error_events.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无失败任务" />
          ) : (
            <List
              dataSource={status.recent_error_events}
              renderItem={(event) => (
                <List.Item>
                  <List.Item.Meta
                    title={event.subject_id ?? event.event_type}
                    description={formatJson(event.payload["error"] ?? event.event_type)}
                  />
                  <span className="table-time">{formatDateTime(event.occurred_at)}</span>
                </List.Item>
              )}
            />
          )}
        </Card>
      </div>

      <Card title="运行检查">
        <Descriptions bordered size="small" column={{ xs: 1, md: 2 }}>
          <Descriptions.Item label="数据库">
            <StatusTag status={status.database} />
          </Descriptions.Item>
          <Descriptions.Item label="检查时间">
            {formatDateTime(status.checked_at)}
          </Descriptions.Item>
          <Descriptions.Item label="环境名称">
            {environment?.environment.environment_name ?? <Tag>暂无上下文</Tag>}
          </Descriptions.Item>
          <Descriptions.Item label="异常设备">
            {environment?.unavailable_device_ids.length ?? 0}
          </Descriptions.Item>
        </Descriptions>
      </Card>
    </section>
  );
}
