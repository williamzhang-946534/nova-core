import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Button, Card, Descriptions, Empty, Table, Tabs, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { ReloadOutlined } from "@ant-design/icons";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import JsonBlock from "@/components/JsonBlock";
import PageLoading from "@/components/PageLoading";
import StatusTag from "@/components/StatusTag";
import { getTask } from "@/api/tasks";
import { listEvents } from "@/api/events";
import type { TaskStep, ToolExecution } from "@/types/tasks";
import type { EventSummary } from "@/types/events";
import { formatDateTime } from "@/utils/format";

export default function TaskDetailPage() {
  const { taskId = "" } = useParams();
  const taskQuery = useQuery({
    queryKey: ["task", taskId],
    queryFn: () => getTask(taskId),
    enabled: taskId.length > 0,
  });
  const eventsQuery = useQuery({
    queryKey: ["task-events", taskQuery.data?.correlation_id],
    queryFn: () =>
      listEvents({
        correlation_id: taskQuery.data?.correlation_id ?? "",
        page_size: 50,
      }),
    enabled:
      taskQuery.data?.correlation_id !== null && taskQuery.data?.correlation_id !== undefined,
  });

  const stepColumns: ColumnsType<TaskStep> = [
    { title: "#", dataIndex: "step_index", width: 50 },
    {
      title: "步骤",
      dataIndex: "name",
      render: (value: string, step) => (
        <div>
          <strong>{value}</strong>
          <div className="secondary-text">{step.tool_name ?? "未绑定工具"}</div>
        </div>
      ),
    },
    { title: "状态", dataIndex: "status", render: (value: string) => <StatusTag status={value} /> },
    { title: "开始", dataIndex: "started_at", render: formatDateTime },
    { title: "完成", dataIndex: "completed_at", render: formatDateTime },
  ];

  const executionColumns: ColumnsType<ToolExecution> = [
    { title: "工具", dataIndex: "tool_name" },
    { title: "状态", dataIndex: "status", render: (value: string) => <StatusTag status={value} /> },
    { title: "风险", dataIndex: "risk_level", render: (value: string) => <Tag>{value}</Tag> },
    { title: "权限", dataIndex: "permission_result" },
    {
      title: "耗时",
      dataIndex: "duration_ms",
      render: (value: number | null) => (value === null ? "-" : `${value} ms`),
    },
    { title: "完成时间", dataIndex: "completed_at", render: formatDateTime },
  ];

  const eventColumns: ColumnsType<EventSummary> = [
    { title: "时间", dataIndex: "occurred_at", render: formatDateTime },
    { title: "事件", dataIndex: "event_type" },
    { title: "来源", dataIndex: "source" },
  ];

  if (taskQuery.isPending) {
    return <PageLoading text="正在读取任务详情..." />;
  }

  if (taskQuery.isError) {
    return (
      <ApiErrorAlert
        error={taskQuery.error}
        onRetry={() => void taskQuery.refetch()}
        retrying={taskQuery.isFetching}
      />
    );
  }

  const task = taskQuery.data;

  return (
    <section className="page-stack">
      <header className="page-header">
        <div>
          <h1>{task.title}</h1>
          <p>
            {task.task_type} · {task.id}
          </p>
        </div>
        <Button
          icon={<ReloadOutlined />}
          loading={taskQuery.isFetching}
          onClick={() => void taskQuery.refetch()}
        >
          刷新
        </Button>
      </header>

      <Card title="任务信息">
        <Descriptions bordered size="small" column={{ xs: 1, md: 2 }}>
          <Descriptions.Item label="状态">
            <StatusTag status={task.status} />
          </Descriptions.Item>
          <Descriptions.Item label="来源">{task.origin}</Descriptions.Item>
          <Descriptions.Item label="创建时间">{formatDateTime(task.created_at)}</Descriptions.Item>
          <Descriptions.Item label="开始时间">{formatDateTime(task.started_at)}</Descriptions.Item>
          <Descriptions.Item label="完成时间">
            {formatDateTime(task.completed_at)}
          </Descriptions.Item>
          <Descriptions.Item label="Correlation ID">
            <span className="mono-text">{task.correlation_id ?? "-"}</span>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {task.error ? (
        <Card title="错误">
          <JsonBlock value={task.error} />
        </Card>
      ) : null}

      <Card>
        <Tabs
          items={[
            {
              key: "steps",
              label: `步骤（${task.steps.length}）`,
              children: (
                <Table
                  rowKey="id"
                  columns={stepColumns}
                  dataSource={task.steps}
                  pagination={false}
                  size="small"
                  expandable={{
                    expandedRowRender: (step) => (
                      <div className="expanded-json">
                        <JsonBlock value={step.input} />
                        <JsonBlock value={step.output} />
                        {step.error ? <JsonBlock value={step.error} /> : null}
                      </div>
                    ),
                  }}
                  locale={{ emptyText: <Empty description="暂无步骤" /> }}
                />
              ),
            },
            {
              key: "executions",
              label: `工具调用（${task.executions.length}）`,
              children: (
                <Table
                  rowKey="id"
                  columns={executionColumns}
                  dataSource={task.executions}
                  pagination={false}
                  size="small"
                  expandable={{
                    expandedRowRender: (execution) => (
                      <div className="expanded-json">
                        <JsonBlock value={execution.input} />
                        <JsonBlock value={execution.output} />
                        <JsonBlock value={execution.validation} />
                        {execution.error ? <JsonBlock value={execution.error} /> : null}
                      </div>
                    ),
                  }}
                  locale={{ emptyText: <Empty description="暂无工具调用" /> }}
                />
              ),
            },
            {
              key: "events",
              label: "关联事件",
              children: eventsQuery.isError ? (
                <ApiErrorAlert error={eventsQuery.error} />
              ) : (
                <Table
                  rowKey="id"
                  columns={eventColumns}
                  dataSource={eventsQuery.data?.data ?? []}
                  loading={eventsQuery.isFetching}
                  pagination={false}
                  size="small"
                  locale={{ emptyText: <Empty description="暂无关联事件" /> }}
                />
              ),
            },
            {
              key: "plan",
              label: "计划与结果",
              children: (
                <div className="expanded-json">
                  <JsonBlock value={task.plan} />
                  <JsonBlock value={task.result} />
                </div>
              ),
            },
          ]}
        />
      </Card>
    </section>
  );
}
