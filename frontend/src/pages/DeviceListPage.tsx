import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Button, Card, Empty, Input, Select, Space, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { ReloadOutlined, SearchOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import PageLoading from "@/components/PageLoading";
import StatusTag from "@/components/StatusTag";
import { listDevices } from "@/api/devices";
import type { Device } from "@/types/console";
import { formatDeviceType } from "@/utils/format";

export default function DeviceListPage() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [area, setArea] = useState("");
  const [deviceType, setDeviceType] = useState("");
  const [online, setOnline] = useState<string | undefined>();
  const [keyword, setKeyword] = useState("");

  const devicesQuery = useQuery({
    queryKey: ["devices", { page, pageSize, area, deviceType, online, keyword }],
    queryFn: () =>
      listDevices({
        page,
        page_size: pageSize,
        area: area || undefined,
        device_type: deviceType || undefined,
        online: online === undefined ? undefined : online === "true",
        keyword: keyword || undefined,
      }),
    placeholderData: keepPreviousData,
  });

  const columns: ColumnsType<Device> = [
    {
      title: "设备",
      dataIndex: "name",
      render: (_, device) => (
        <div>
          <strong>{device.name}</strong>
          <div className="secondary-text">{device.external_id}</div>
        </div>
      ),
    },
    { title: "区域", dataIndex: "area", render: (value: string | null) => value ?? "-" },
    {
      title: "类型",
      dataIndex: "device_type",
      render: (value: string) => <Tag>{formatDeviceType(value)}</Tag>,
    },
    {
      title: "适配器",
      dataIndex: "adapter_id",
      render: (value: string) => <Tag>{value}</Tag>,
    },
    {
      title: "状态",
      dataIndex: "is_online",
      render: (value: boolean) => <StatusTag status={value ? "healthy" : "unavailable"} />,
    },
    {
      title: "风险",
      dataIndex: "risk_level",
      render: (value: string) => (
        <Tag color={value === "low_risk" ? "green" : "orange"}>{value}</Tag>
      ),
    },
  ];

  if (devicesQuery.isPending) {
    return <PageLoading text="正在读取设备投影..." />;
  }

  return (
    <section className="page-stack">
      <header className="page-header">
        <div>
          <h1>设备</h1>
          <p>Arvuno 允许接入的轻量设备投影，不展示 Home Assistant 完整设备库。</p>
        </div>
        <Button
          icon={<ReloadOutlined />}
          loading={devicesQuery.isFetching}
          onClick={() => void devicesQuery.refetch()}
        >
          刷新
        </Button>
      </header>

      {devicesQuery.isError ? (
        <ApiErrorAlert
          error={devicesQuery.error}
          onRetry={() => void devicesQuery.refetch()}
          retrying={devicesQuery.isFetching}
        />
      ) : null}

      <Card>
        <Space className="filter-bar" wrap>
          <Input
            allowClear
            placeholder="名称或别名"
            prefix={<SearchOutlined />}
            value={keyword}
            onChange={(event) => {
              setPage(1);
              setKeyword(event.target.value);
            }}
          />
          <Input
            allowClear
            placeholder="区域"
            value={area}
            onChange={(event) => {
              setPage(1);
              setArea(event.target.value);
            }}
          />
          <Select
            allowClear
            placeholder="类型"
            value={deviceType || undefined}
            onChange={(value) => {
              setPage(1);
              setDeviceType(value ?? "");
            }}
            options={[
              "light",
              "switch",
              "sensor_temperature",
              "sensor_humidity",
              "sensor_motion",
              "sensor_contact",
              "climate",
              "media_player",
            ].map((value) => ({ value, label: formatDeviceType(value) }))}
            className="fixed-select"
          />
          <Select
            allowClear
            placeholder="在线状态"
            value={online}
            onChange={(value) => {
              setPage(1);
              setOnline(value);
            }}
            options={[
              { value: "true", label: "在线" },
              { value: "false", label: "离线" },
            ]}
            className="fixed-select"
          />
        </Space>
      </Card>

      <Card title={`设备列表（${devicesQuery.data?.total ?? 0}）`}>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={devicesQuery.data?.data ?? []}
          loading={devicesQuery.isFetching}
          locale={{ emptyText: <Empty description="没有符合条件的设备" /> }}
          onRow={(device) => ({
            onClick: () => navigate(`/devices/${device.id}`),
            className: "clickable-row",
          })}
          pagination={{
            current: page,
            pageSize,
            total: devicesQuery.data?.total ?? 0,
            showSizeChanger: true,
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPage);
              setPageSize(nextPageSize);
            },
          }}
        />
      </Card>
    </section>
  );
}
