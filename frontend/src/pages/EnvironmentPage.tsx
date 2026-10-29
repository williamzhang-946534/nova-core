import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Button, Card, Descriptions, Empty, Space, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { ReloadOutlined } from "@ant-design/icons";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import PageLoading from "@/components/PageLoading";
import StatusTag from "@/components/StatusTag";
import { getEnvironment, listEnvironmentSnapshots } from "@/api/environment";
import type { DeviceContextState, EnvironmentSnapshot, SensorContextState } from "@/types/console";
import { formatDateTime, formatDeviceType } from "@/utils/format";

interface AreaRow {
  name: string;
  device_count: number;
  online_device_count: number;
  unavailable_device_ids: string[];
}

export default function EnvironmentPage() {
  const [page, setPage] = useState(1);
  const environmentQuery = useQuery({ queryKey: ["environment"], queryFn: getEnvironment });
  const snapshotsQuery = useQuery({
    queryKey: ["environment-snapshots", page],
    queryFn: () => listEnvironmentSnapshots(page, 10),
    placeholderData: keepPreviousData,
  });

  const deviceColumns: ColumnsType<DeviceContextState> = [
    { title: "设备", dataIndex: "name" },
    { title: "区域", dataIndex: "area", render: (value: string | null) => value ?? "-" },
    {
      title: "类型",
      dataIndex: "device_type",
      render: (value: string) => <Tag>{formatDeviceType(value)}</Tag>,
    },
    { title: "状态", dataIndex: "state", render: (value: string) => <StatusTag status={value} /> },
    { title: "更新时间", dataIndex: "updated_at", render: formatDateTime },
  ];

  const sensorColumns: ColumnsType<SensorContextState> = [
    { title: "传感器", dataIndex: "device_id" },
    { title: "类型", dataIndex: "sensor_type" },
    {
      title: "当前值",
      dataIndex: "value",
      render: (value: string | number | boolean, record) =>
        `${value}${record.unit ? ` ${record.unit}` : ""}`,
    },
    { title: "更新时间", dataIndex: "updated_at", render: formatDateTime },
  ];

  const areaColumns: ColumnsType<AreaRow> = [
    { title: "区域", dataIndex: "name" },
    { title: "设备数", dataIndex: "device_count" },
    { title: "在线数", dataIndex: "online_device_count" },
    {
      title: "异常设备",
      dataIndex: "unavailable_device_ids",
      render: (value: string[]) => value.join(", ") || "-",
    },
  ];

  const snapshotColumns: ColumnsType<EnvironmentSnapshot> = [
    { title: "快照时间", dataIndex: "created_at", render: formatDateTime },
    { title: "异常数", dataIndex: "anomaly_count" },
    { title: "活动任务", dataIndex: "active_task_ids", render: (value: string[]) => value.length },
  ];

  if (environmentQuery.isPending) {
    return <PageLoading text="正在读取环境上下文..." />;
  }

  if (environmentQuery.isError) {
    return (
      <ApiErrorAlert
        error={environmentQuery.error}
        onRetry={() => void environmentQuery.refetch()}
        retrying={environmentQuery.isFetching}
      />
    );
  }

  const environment = environmentQuery.data;
  const devices = Object.values(environment.environment.devices);
  const sensors = Object.values(environment.environment.sensors);
  const areas: AreaRow[] = Object.entries(environment.areas).map(([name, summary]) => ({
    name,
    ...summary,
  }));

  return (
    <section className="page-stack">
      <header className="page-header">
        <div>
          <h1>环境状态</h1>
          <p>Arvuno 当前聚合的环境上下文、区域摘要和传感器观测值。</p>
        </div>
        <Button
          icon={<ReloadOutlined />}
          loading={environmentQuery.isFetching || snapshotsQuery.isFetching}
          onClick={() => {
            void environmentQuery.refetch();
            void snapshotsQuery.refetch();
          }}
        >
          刷新
        </Button>
      </header>

      {snapshotsQuery.isError ? <ApiErrorAlert error={snapshotsQuery.error} /> : null}

      <Card title={environment.environment.environment_name}>
        <Descriptions bordered size="small" column={{ xs: 1, md: 3 }}>
          <Descriptions.Item label="上下文更新">
            {formatDateTime(environment.environment.updated_at)}
          </Descriptions.Item>
          <Descriptions.Item label="在线设备">{environment.online_device_count}</Descriptions.Item>
          <Descriptions.Item label="异常设备">
            <Space size={[4, 4]} wrap>
              {environment.unavailable_device_ids.length === 0 ? (
                <Tag color="green">无</Tag>
              ) : (
                environment.unavailable_device_ids.map((id) => (
                  <Tag key={id} color="orange">
                    {id}
                  </Tag>
                ))
              )}
            </Space>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <div className="two-column">
        <Card title={`设备上下文（${devices.length}）`}>
          <Table
            rowKey="device_id"
            columns={deviceColumns}
            dataSource={devices}
            pagination={false}
            size="small"
            locale={{ emptyText: <Empty description="暂无设备事件写入上下文" /> }}
          />
        </Card>
        <Card title={`传感器（${sensors.length}）`}>
          <Table
            rowKey="device_id"
            columns={sensorColumns}
            dataSource={sensors}
            pagination={false}
            size="small"
            locale={{ emptyText: <Empty description="暂无传感器观测值" /> }}
          />
        </Card>
      </div>

      <div className="two-column">
        <Card title="区域摘要">
          <Table
            rowKey="name"
            columns={areaColumns}
            dataSource={areas}
            pagination={false}
            size="small"
            locale={{ emptyText: <Empty description="暂无区域数据" /> }}
          />
        </Card>
        <Card title="环境快照">
          <Table
            rowKey="id"
            columns={snapshotColumns}
            dataSource={snapshotsQuery.data?.data ?? []}
            loading={snapshotsQuery.isFetching}
            size="small"
            pagination={{
              current: page,
              pageSize: 10,
              total: snapshotsQuery.data?.total ?? 0,
              onChange: setPage,
            }}
            locale={{ emptyText: <Empty description="暂无快照" /> }}
          />
        </Card>
      </div>
    </section>
  );
}
