import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Button, Card, Drawer, Descriptions, Empty, Input, Space, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { ReloadOutlined } from "@ant-design/icons";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import JsonBlock from "@/components/JsonBlock";
import PageLoading from "@/components/PageLoading";
import { getEvent, listEvents } from "@/api/events";
import { getSettings } from "@/api/settings";
import type { EventSummary } from "@/types/events";
import { formatDateTime } from "@/utils/format";

export default function EventsPage() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [eventType, setEventType] = useState("");
  const [subjectId, setSubjectId] = useState("");
  const [correlationId, setCorrelationId] = useState("");
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);

  const settingsQuery = useQuery({ queryKey: ["settings"], queryFn: getSettings });
  const eventsQuery = useQuery({
    queryKey: ["events", { page, pageSize, eventType, subjectId, correlationId }],
    queryFn: () =>
      listEvents({
        page,
        page_size: pageSize,
        event_type: eventType || undefined,
        subject_id: subjectId || undefined,
        correlation_id: correlationId || undefined,
      }),
    placeholderData: keepPreviousData,
    refetchInterval: settingsQuery.data
      ? settingsQuery.data.web_console.event_poll_interval_seconds * 1000
      : false,
  });
  const selectedQuery = useQuery({
    queryKey: ["event", selectedEventId],
    queryFn: () => getEvent(selectedEventId ?? ""),
    enabled: selectedEventId !== null,
  });

  const columns: ColumnsType<EventSummary> = [
    { title: "时间", dataIndex: "occurred_at", render: formatDateTime, width: 190 },
    { title: "事件", dataIndex: "event_type", render: (value: string) => <Tag>{value}</Tag> },
    { title: "来源", dataIndex: "source" },
    { title: "对象", dataIndex: "subject_id", render: (value: string | null) => value ?? "-" },
    {
      title: "Correlation ID",
      dataIndex: "correlation_id",
      render: (value: string | null) => <span className="mono-text">{value ?? "-"}</span>,
    },
  ];

  if (eventsQuery.isPending) {
    return <PageLoading text="正在读取事件时间线..." />;
  }

  return (
    <section className="page-stack">
      <header className="page-header">
        <div>
          <h1>事件时间线</h1>
          <p>
            Arvuno 自身持久化的领域事件。
            {settingsQuery.data
              ? `每 ${settingsQuery.data.web_console.event_poll_interval_seconds} 秒自动刷新。`
              : ""}
          </p>
        </div>
        <Button
          icon={<ReloadOutlined />}
          loading={eventsQuery.isFetching}
          onClick={() => void eventsQuery.refetch()}
        >
          刷新
        </Button>
      </header>

      {eventsQuery.isError ? (
        <ApiErrorAlert
          error={eventsQuery.error}
          onRetry={() => void eventsQuery.refetch()}
          retrying={eventsQuery.isFetching}
        />
      ) : null}
      {settingsQuery.isError ? <ApiErrorAlert error={settingsQuery.error} /> : null}

      <Card>
        <Space className="filter-bar" wrap>
          <Input
            allowClear
            placeholder="事件类型"
            value={eventType}
            onChange={(event) => {
              setPage(1);
              setEventType(event.target.value);
            }}
          />
          <Input
            allowClear
            placeholder="对象 ID"
            value={subjectId}
            onChange={(event) => {
              setPage(1);
              setSubjectId(event.target.value);
            }}
          />
          <Input
            allowClear
            placeholder="Correlation ID"
            value={correlationId}
            onChange={(event) => {
              setPage(1);
              setCorrelationId(event.target.value);
            }}
          />
        </Space>
      </Card>

      <Card title={`事件（${eventsQuery.data?.total ?? 0}）`}>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={eventsQuery.data?.data ?? []}
          loading={eventsQuery.isFetching}
          size="small"
          onRow={(event) => ({
            onClick: () => setSelectedEventId(event.id),
            className: "clickable-row",
          })}
          pagination={{
            current: page,
            pageSize,
            total: eventsQuery.data?.total ?? 0,
            showSizeChanger: true,
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPage);
              setPageSize(nextPageSize);
            },
          }}
          locale={{ emptyText: <Empty description="暂无事件" /> }}
        />
      </Card>

      <Drawer
        title="事件详情"
        width={520}
        open={selectedEventId !== null}
        onClose={() => setSelectedEventId(null)}
      >
        {selectedQuery.isPending ? (
          <PageLoading text="正在读取事件..." />
        ) : selectedQuery.isError ? (
          <ApiErrorAlert error={selectedQuery.error} />
        ) : selectedQuery.data ? (
          <div className="page-stack">
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="ID">
                <span className="mono-text">{selectedQuery.data.id}</span>
              </Descriptions.Item>
              <Descriptions.Item label="事件类型">
                {selectedQuery.data.event_type}
              </Descriptions.Item>
              <Descriptions.Item label="来源">{selectedQuery.data.source}</Descriptions.Item>
              <Descriptions.Item label="对象">
                {selectedQuery.data.subject_id ?? "-"}
              </Descriptions.Item>
              <Descriptions.Item label="发生时间">
                {formatDateTime(selectedQuery.data.occurred_at)}
              </Descriptions.Item>
              <Descriptions.Item label="Correlation ID">
                <span className="mono-text">{selectedQuery.data.correlation_id ?? "-"}</span>
              </Descriptions.Item>
            </Descriptions>
            <JsonBlock value={selectedQuery.data.payload} />
          </div>
        ) : null}
      </Drawer>
    </section>
  );
}
