import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Button, Card, Descriptions, Empty, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { ReloadOutlined } from "@ant-design/icons";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import JsonBlock from "@/components/JsonBlock";
import PageLoading from "@/components/PageLoading";
import StatusTag from "@/components/StatusTag";
import { getDevice, getDeviceState } from "@/api/devices";
import type { DeviceCapability } from "@/types/console";
import type { EventSummary } from "@/types/events";
import { formatDateTime, formatDeviceType } from "@/utils/format";

export default function DeviceDetailPage() {
  const { deviceId = "" } = useParams();
  const detailQuery = useQuery({
    queryKey: ["device", deviceId],
    queryFn: () => getDevice(deviceId),
    enabled: deviceId.length > 0,
  });
  const stateQuery = useQuery({
    queryKey: ["device-state", deviceId],
    queryFn: () => getDeviceState(deviceId),
    enabled: deviceId.length > 0,
  });

  const capabilityColumns: ColumnsType<DeviceCapability> = [
    { title: "能力", dataIndex: "capability" },
    { title: "动作", dataIndex: "actions", render: (value: string[]) => value.join(", ") },
    { title: "风险", dataIndex: "risk_level" },
    {
      title: "需要确认",
      dataIndex: "requires_confirmation",
      render: (value: boolean) => (value ? <Tag color="orange">是</Tag> : <Tag>否</Tag>),
    },
  ];

  const eventColumns: ColumnsType<EventSummary> = [
    { title: "事件", dataIndex: "event_type" },
    { title: "来源", dataIndex: "source" },
    { title: "时间", dataIndex: "occurred_at", render: formatDateTime },
  ];

  if (detailQuery.isPending || stateQuery.isPending) {
    return <PageLoading text="正在读取设备详情..." />;
  }

  if (detailQuery.isError) {
    return (
      <ApiErrorAlert
        error={detailQuery.error}
        onRetry={() => void detailQuery.refetch()}
        retrying={detailQuery.isFetching}
      />
    );
  }

  const detail = detailQuery.data;
  const device = detail.device;
  const currentState = stateQuery.data;

  return (
    <section className="page-stack">
      <header className="page-header">
        <div>
          <h1>{device.name}</h1>
          <p>
            {device.area ?? "未分配区域"} · {formatDeviceType(device.device_type)} ·{" "}
            {device.adapter_id}
          </p>
        </div>
        <Button
          icon={<ReloadOutlined />}
          loading={detailQuery.isFetching || stateQuery.isFetching}
          onClick={() => {
            void detailQuery.refetch();
            void stateQuery.refetch();
          }}
        >
          刷新
        </Button>
      </header>

      {stateQuery.isError ? <ApiErrorAlert error={stateQuery.error} /> : null}

      <div className="two-column">
        <Card title="当前状态">
          {currentState ? (
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="状态">
                <StatusTag status={currentState.state} />
              </Descriptions.Item>
              <Descriptions.Item label="观察时间">
                {formatDateTime(currentState.observed_at)}
              </Descriptions.Item>
              <Descriptions.Item label="已验证">
                <Tag color={currentState.verified ? "green" : "orange"}>
                  {currentState.verified ? "通过" : "未通过"}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="来源">
                {currentState.from_cache ? "缓存快照" : "适配器读取"}
              </Descriptions.Item>
            </Descriptions>
          ) : (
            <Empty description="暂无状态数据" />
          )}
        </Card>

        <Card title="注册信息">
          <Descriptions bordered size="small" column={1}>
            <Descriptions.Item label="Arvuno ID">{device.id}</Descriptions.Item>
            <Descriptions.Item label="外部 ID">{device.external_id}</Descriptions.Item>
            <Descriptions.Item label="权限动作">
              {device.permissions.allowed_actions.join(", ") || "-"}
            </Descriptions.Item>
            <Descriptions.Item label="最高风险">
              {device.permissions.max_risk_level}
            </Descriptions.Item>
          </Descriptions>
        </Card>
      </div>

      <div className="two-column">
        <Card title="能力">
          <Table
            rowKey="capability"
            columns={capabilityColumns}
            dataSource={device.capabilities}
            pagination={false}
            size="small"
            locale={{ emptyText: <Empty description="无能力记录" /> }}
          />
        </Card>
        <Card title="最近事件">
          <Table
            rowKey="id"
            columns={eventColumns}
            dataSource={detail.recent_events}
            pagination={false}
            size="small"
            locale={{ emptyText: <Empty description="暂无事件" /> }}
          />
        </Card>
      </div>

      <Card title="状态属性">
        <JsonBlock value={currentState?.attributes ?? detail.latest_state?.attributes ?? null} />
      </Card>
    </section>
  );
}
