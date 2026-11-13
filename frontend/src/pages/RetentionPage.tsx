import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Descriptions, Space, Table, Tag, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import { PlayCircleOutlined, ReloadOutlined, WarningOutlined } from "@ant-design/icons";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import PageLoading from "@/components/PageLoading";
import { getRetentionStatus, listRetentionFailures, runRetention } from "@/api/governance";
import type { RetentionRun } from "@/types/governance";
import { formatDateTime, formatJson } from "@/utils/format";

export default function RetentionPage() {
  const queryClient = useQueryClient();
  const statusQuery = useQuery({ queryKey: ["retention-status"], queryFn: getRetentionStatus });
  const failuresQuery = useQuery({
    queryKey: ["retention-failures"],
    queryFn: () => listRetentionFailures(50),
  });
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["retention-status"] });
    void queryClient.invalidateQueries({ queryKey: ["retention-failures"] });
  };
  const run = useMutation({
    mutationFn: runRetention,
    onSuccess: () => {
      invalidate();
      void message.success("保留策略已执行");
    },
  });

  const jobs = statusQuery.data?.jobs ?? [];
  const runColumns: ColumnsType<RetentionRun> = [
    { title: "任务", dataIndex: "job_name", width: 180 },
    {
      title: "结果",
      dataIndex: "status",
      width: 110,
      render: (value: string) => (
        <Tag color={value === "succeeded" ? "green" : value === "failed" ? "red" : "blue"}>
          {value}
        </Tag>
      ),
    },
    { title: "清理数量", dataIndex: "affected_count", width: 110 },
    { title: "开始", dataIndex: "started_at", render: formatDateTime, width: 165 },
    { title: "结束", dataIndex: "finished_at", render: formatDateTime, width: 165 },
    { title: "下次执行", dataIndex: "next_run_at", render: formatDateTime, width: 165 },
    { title: "错误代码", dataIndex: "error_code", render: (value?: string | null) => value ?? "-" },
    { title: "详情", dataIndex: "details", render: formatJson },
  ];

  if (statusQuery.isPending) {
    return <PageLoading text="正在读取保留策略..." />;
  }

  return (
    <section className="page-stack">
      <header className="page-header">
        <div>
          <h1>数据保留</h1>
          <p>查看各业务数据的保留规则、执行状态和失败记录。</p>
        </div>
        <Space>
          <Button
            icon={<PlayCircleOutlined />}
            loading={run.isPending}
            onClick={() =>
              run.mutate(
                (statusQuery.data?.jobs ?? []).filter((job) => job.enabled).map((job) => job.name),
              )
            }
          >
            执行启用任务
          </Button>
          <Button
            icon={<ReloadOutlined />}
            loading={statusQuery.isFetching || failuresQuery.isFetching}
            onClick={() => invalidate()}
          >
            刷新
          </Button>
        </Space>
      </header>

      {statusQuery.isError ? <ApiErrorAlert error={statusQuery.error} /> : null}
      {failuresQuery.isError ? <ApiErrorAlert error={failuresQuery.error} /> : null}
      {run.isError ? <ApiErrorAlert error={run.error} /> : null}
      {statusQuery.data?.single_process_only ? (
        <Alert
          type="info"
          showIcon
          message="单进程调度约束"
          description="当前 Retention Scheduler 仅保证进程内不并发执行同一任务；多进程部署需要外部协调。"
        />
      ) : null}

      <Card title={`保留策略（${jobs.length}）`}>
        <Table
          rowKey="name"
          dataSource={jobs}
          loading={statusQuery.isFetching}
          pagination={false}
          scroll={{ x: 1250 }}
          columns={[
            { title: "任务", dataIndex: "label" },
            { title: "名称", dataIndex: "name", width: 210 },
            {
              title: "启用",
              dataIndex: "enabled",
              width: 90,
              render: (value: boolean) => (
                <Tag color={value ? "green" : "default"}>{value ? "启用" : "停用"}</Tag>
              ),
            },
            {
              title: "间隔",
              dataIndex: "interval_seconds",
              width: 120,
              render: (value: number) => `${Math.round(value / 60)} 分钟`,
            },
            { title: "批次", dataIndex: "batch_size", width: 90 },
            {
              title: "上次执行",
              key: "last_run",
              width: 220,
              render: (_, job) =>
                job.last_run
                  ? `${job.last_run.status} · ${job.last_run.affected_count} 条 · ${formatDateTime(job.last_run.started_at)}`
                  : "-",
            },
            { title: "下次执行", dataIndex: "next_run_at", render: formatDateTime, width: 165 },
            {
              title: "规则",
              dataIndex: "rules",
              render: formatJson,
            },
            {
              title: "操作",
              key: "actions",
              fixed: "right",
              width: 120,
              render: (_, job) => (
                <Button
                  size="small"
                  disabled={!job.enabled}
                  loading={
                    run.isPending && run.variables?.length === 1 && run.variables[0] === job.name
                  }
                  onClick={() => run.mutate([job.name])}
                >
                  执行
                </Button>
              ),
            },
          ]}
        />
      </Card>

      <Card title="上次执行结果">
        <Descriptions
          size="small"
          bordered
          column={2}
          items={jobs.map((job) => ({
            key: job.name,
            label: job.label,
            children: job.last_run
              ? `${job.last_run.status} · 清理 ${job.last_run.affected_count} 条`
              : "尚未执行",
          }))}
        />
      </Card>

      <Card title={`失败记录（${failuresQuery.data?.length ?? 0}）`}>
        <Table
          rowKey="id"
          dataSource={failuresQuery.data ?? []}
          loading={failuresQuery.isFetching}
          scroll={{ x: 1250 }}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          columns={runColumns}
          expandable={{
            expandedRowRender: (record) => (
              <Descriptions
                size="small"
                column={1}
                bordered
                items={[
                  { key: "message", label: "错误信息", children: record.error_message ?? "-" },
                  {
                    key: "details",
                    label: "详情",
                    children: <pre>{formatJson(record.details)}</pre>,
                  },
                ]}
              />
            ),
          }}
          locale={{
            emptyText: (
              <Space>
                <WarningOutlined />
                暂无失败记录
              </Space>
            ),
          }}
        />
      </Card>
    </section>
  );
}
