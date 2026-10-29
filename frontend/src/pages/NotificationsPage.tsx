import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Checkbox, Empty, Select, Space, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { CheckOutlined, ReloadOutlined } from "@ant-design/icons";
import { Link } from "react-router-dom";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import PageLoading from "@/components/PageLoading";
import StatusTag from "@/components/StatusTag";
import { listNotifications, markNotificationRead } from "@/api/automations";
import type { ConsoleNotification, NotificationLevel } from "@/types/automations";
import { formatDateTime } from "@/utils/format";

export default function NotificationsPage() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [level, setLevel] = useState<NotificationLevel | undefined>();
  const [unreadOnly, setUnreadOnly] = useState(false);

  const notificationsQuery = useQuery({
    queryKey: ["notifications", { page, pageSize, level, unreadOnly }],
    queryFn: () =>
      listNotifications({
        page,
        page_size: pageSize,
        level,
        unread_only: unreadOnly,
      }),
    placeholderData: keepPreviousData,
  });
  const readMutation = useMutation({
    mutationFn: markNotificationRead,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });

  const columns: ColumnsType<ConsoleNotification> = [
    {
      title: "通知",
      dataIndex: "title",
      render: (value: string, notification) => (
        <div>
          <strong>{value}</strong>
          <div className="secondary-text">{notification.content}</div>
        </div>
      ),
    },
    {
      title: "级别",
      dataIndex: "level",
      render: (value: NotificationLevel) => (
        <Tag color={value === "error" ? "red" : value === "warning" ? "orange" : "blue"}>
          {value}
        </Tag>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      render: (value: ConsoleNotification["status"]) => (
        <StatusTag status={value === "read" ? "completed" : "pending"} />
      ),
    },
    {
      title: "关联任务",
      dataIndex: "related_task_id",
      render: (value: string | null) => (value ? <Link to={`/tasks/${value}`}>{value}</Link> : "-"),
    },
    { title: "时间", dataIndex: "created_at", render: formatDateTime },
    {
      title: "操作",
      key: "actions",
      render: (_, notification) =>
        notification.status === "sent" ? (
          <Button
            size="small"
            icon={<CheckOutlined />}
            loading={readMutation.isPending && readMutation.variables === notification.id}
            onClick={() => readMutation.mutate(notification.id)}
          >
            标为已读
          </Button>
        ) : (
          "-"
        ),
    },
  ];

  if (notificationsQuery.isPending) {
    return <PageLoading text="正在读取站内通知..." />;
  }

  return (
    <section className="page-stack">
      <header className="page-header">
        <div>
          <h1>站内通知</h1>
          <p>任务失败和 Arvuno 上下文规则产生的提醒记录。</p>
        </div>
        <Button
          icon={<ReloadOutlined />}
          loading={notificationsQuery.isFetching}
          onClick={() => void notificationsQuery.refetch()}
        >
          刷新
        </Button>
      </header>

      {notificationsQuery.isError ? (
        <ApiErrorAlert
          error={notificationsQuery.error}
          onRetry={() => void notificationsQuery.refetch()}
          retrying={notificationsQuery.isFetching}
        />
      ) : null}
      {readMutation.isError ? <ApiErrorAlert error={readMutation.error} /> : null}

      <Card>
        <Space className="filter-bar" wrap>
          <Select
            allowClear
            placeholder="通知级别"
            value={level}
            onChange={(value) => {
              setPage(1);
              setLevel(value);
            }}
            options={[
              { value: "info", label: "信息" },
              { value: "warning", label: "警告" },
              { value: "error", label: "错误" },
            ]}
            className="fixed-select"
          />
          <Checkbox
            checked={unreadOnly}
            onChange={(event) => {
              setPage(1);
              setUnreadOnly(event.target.checked);
            }}
          >
            仅未读
          </Checkbox>
        </Space>
      </Card>

      <Card title={`通知（${notificationsQuery.data?.total ?? 0}）`}>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={notificationsQuery.data?.data ?? []}
          loading={notificationsQuery.isFetching}
          size="small"
          pagination={{
            current: page,
            pageSize,
            total: notificationsQuery.data?.total ?? 0,
            showSizeChanger: true,
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPage);
              setPageSize(nextPageSize);
            },
          }}
          locale={{ emptyText: <Empty description="暂无站内通知" /> }}
        />
      </Card>
    </section>
  );
}
