import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Empty, Input, Popconfirm, Select, Space, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { ReloadOutlined } from "@ant-design/icons";
import { Link, useNavigate } from "react-router-dom";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import PageLoading from "@/components/PageLoading";
import StatusTag from "@/components/StatusTag";
import { cancelTask, listTasks } from "@/api/tasks";
import type { Task, TaskStatus } from "@/types/tasks";
import { formatDateTime } from "@/utils/format";

const activeStatuses: TaskStatus[] = ["pending", "planning", "waiting_confirmation", "running"];

export default function TaskListPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [status, setStatus] = useState<TaskStatus | undefined>();
  const [keyword, setKeyword] = useState("");

  const tasksQuery = useQuery({
    queryKey: ["tasks", { page, pageSize, status, keyword }],
    queryFn: () =>
      listTasks({
        page,
        page_size: pageSize,
        status,
      }),
    placeholderData: keepPreviousData,
  });

  const cancelMutation = useMutation({
    mutationFn: (taskId: string) => cancelTask(taskId),
    onSuccess: (task) => {
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
      void queryClient.invalidateQueries({ queryKey: ["task", task.id] });
    },
  });

  const columns: ColumnsType<Task> = [
    {
      title: "任务",
      dataIndex: "title",
      render: (value: string, task) => (
        <div>
          <Link to={`/tasks/${task.id}`}>{value}</Link>
          <div className="secondary-text">{task.task_type}</div>
        </div>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      render: (value: TaskStatus) => <StatusTag status={value} />,
    },
    { title: "来源", dataIndex: "origin", render: (value: string) => <Tag>{value}</Tag> },
    { title: "创建时间", dataIndex: "created_at", render: formatDateTime },
    {
      title: "Correlation ID",
      dataIndex: "correlation_id",
      render: (value: string | null) => <span className="mono-text">{value ?? "-"}</span>,
    },
    {
      title: "操作",
      key: "actions",
      render: (_, task) =>
        activeStatuses.includes(task.status) ? (
          <Popconfirm
            title="取消这个任务？"
            onConfirm={() => cancelMutation.mutate(task.id)}
            okButtonProps={{ danger: true }}
          >
            <Button
              size="small"
              danger
              loading={cancelMutation.isPending && cancelMutation.variables === task.id}
            >
              取消
            </Button>
          </Popconfirm>
        ) : (
          "-"
        ),
    },
  ];

  if (tasksQuery.isPending) {
    return <PageLoading text="正在读取任务历史..." />;
  }

  return (
    <section className="page-stack">
      <header className="page-header">
        <div>
          <h1>任务记录</h1>
          <p>自然语言或显式 API 创建的任务、状态和关联追踪 ID。</p>
        </div>
        <Button
          icon={<ReloadOutlined />}
          loading={tasksQuery.isFetching}
          onClick={() => void tasksQuery.refetch()}
        >
          刷新
        </Button>
      </header>

      {tasksQuery.isError ? (
        <ApiErrorAlert
          error={tasksQuery.error}
          onRetry={() => void tasksQuery.refetch()}
          retrying={tasksQuery.isFetching}
        />
      ) : null}
      {cancelMutation.isError ? <ApiErrorAlert error={cancelMutation.error} /> : null}

      <Card>
        <Space className="filter-bar" wrap>
          <Select
            allowClear
            placeholder="任务状态"
            value={status}
            onChange={(value) => {
              setPage(1);
              setStatus(value);
            }}
            options={(
              [
                "pending",
                "planning",
                "waiting_confirmation",
                "running",
                "completed",
                "failed",
                "cancelled",
              ] as TaskStatus[]
            ).map((value) => ({ value, label: value.replace(/_/g, " ") }))}
            className="fixed-select"
          />
          <Input
            allowClear
            placeholder="按任务类型过滤（按回车）"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            onPressEnter={() => setPage(1)}
          />
        </Space>
      </Card>

      <Card title={`任务（${tasksQuery.data?.total ?? 0}）`}>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={tasksQuery.data?.data ?? []}
          loading={tasksQuery.isFetching}
          size="small"
          onRow={(task) => ({
            onClick: () => navigate(`/tasks/${task.id}`),
            className: "clickable-row",
          })}
          pagination={{
            current: page,
            pageSize,
            total: tasksQuery.data?.total ?? 0,
            showSizeChanger: true,
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPage);
              setPageSize(nextPageSize);
            },
          }}
          locale={{ emptyText: <Empty description="暂无任务记录" /> }}
        />
      </Card>
    </section>
  );
}
