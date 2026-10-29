import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Descriptions, Empty, InputNumber, Space, Table, Tabs, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { ArrowLeftOutlined, ReloadOutlined, SaveOutlined } from "@ant-design/icons";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import JsonBlock from "@/components/JsonBlock";
import PageLoading from "@/components/PageLoading";
import StatusTag from "@/components/StatusTag";
import { getAutomation, listAutomationRuns, updateAutomation } from "@/api/automations";
import type { AutomationCondition, AutomationRun } from "@/types/automations";
import { formatDateTime } from "@/utils/format";

export default function AutomationDetailPage() {
  const { automationId = "" } = useParams();
  const queryClient = useQueryClient();
  const automationQuery = useQuery({
    queryKey: ["automation", automationId],
    queryFn: () => getAutomation(automationId),
    enabled: automationId.length > 0,
  });
  const runsQuery = useQuery({
    queryKey: ["automation-runs", automationId],
    queryFn: () => listAutomationRuns(automationId, { page_size: 50 }),
    enabled: automationId.length > 0,
  });
  const [cooldownSeconds, setCooldownSeconds] = useState<number | null>(null);
  const cooldownValue = cooldownSeconds ?? automationQuery.data?.cooldown_seconds ?? 0;
  const cooldownMutation = useMutation({
    mutationFn: () => updateAutomation(automationId, { cooldown_seconds: cooldownValue }),
    onSuccess: (automation) => {
      setCooldownSeconds(null);
      void queryClient.invalidateQueries({ queryKey: ["automation", automation.id] });
      void queryClient.invalidateQueries({ queryKey: ["automations"] });
    },
  });

  const conditionColumns: ColumnsType<AutomationCondition> = [
    { title: "字段", dataIndex: "field" },
    { title: "运算符", dataIndex: "operator", render: (value: string) => <Tag>{value}</Tag> },
    {
      title: "值",
      dataIndex: "value",
      render: (value: unknown) => <JsonBlock value={{ value }} />,
    },
  ];
  const runColumns: ColumnsType<AutomationRun> = [
    {
      title: "状态",
      dataIndex: "status",
      render: (value: AutomationRun["status"]) => <StatusTag status={value} />,
    },
    { title: "开始时间", dataIndex: "started_at", render: formatDateTime },
    { title: "完成时间", dataIndex: "completed_at", render: formatDateTime },
    {
      title: "任务",
      dataIndex: "task_id",
      render: (value: string | null) => (value ? <Link to={`/tasks/${value}`}>{value}</Link> : "-"),
    },
  ];

  if (automationQuery.isPending) {
    return <PageLoading text="正在读取自动化规则..." />;
  }
  if (automationQuery.isError) {
    return (
      <ApiErrorAlert
        error={automationQuery.error}
        onRetry={() => void automationQuery.refetch()}
        retrying={automationQuery.isFetching}
      />
    );
  }

  const automation = automationQuery.data;

  return (
    <section className="page-stack">
      <header className="page-header">
        <div>
          <h1>{automation.name}</h1>
          <p>{automation.id}</p>
        </div>
        <Space>
          <Link to="/automations">
            <Button icon={<ArrowLeftOutlined />}>返回</Button>
          </Link>
          <Button
            icon={<ReloadOutlined />}
            loading={automationQuery.isFetching || runsQuery.isFetching}
            onClick={() => {
              void automationQuery.refetch();
              void runsQuery.refetch();
            }}
          >
            刷新
          </Button>
        </Space>
      </header>

      {runsQuery.isError ? <ApiErrorAlert error={runsQuery.error} /> : null}
      {cooldownMutation.isError ? <ApiErrorAlert error={cooldownMutation.error} /> : null}

      <Card title="规则信息">
        <Descriptions bordered size="small" column={{ xs: 1, md: 2 }}>
          <Descriptions.Item label="状态">
            <StatusTag status={automation.enabled ? "healthy" : "unavailable"} />
          </Descriptions.Item>
          <Descriptions.Item label="触发事件">{automation.trigger.event_type}</Descriptions.Item>
          <Descriptions.Item label="对象 ID">
            <span className="mono-text">{automation.trigger.subject_id ?? "-"}</span>
          </Descriptions.Item>
          <Descriptions.Item label="风险等级">
            <Tag>{automation.risk_level}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {formatDateTime(automation.created_at)}
          </Descriptions.Item>
          <Descriptions.Item label="更新时间">
            {formatDateTime(automation.updated_at)}
          </Descriptions.Item>
          <Descriptions.Item label="冷却时间">
            <Space>
              <InputNumber
                min={0}
                max={86400}
                value={cooldownValue}
                onChange={setCooldownSeconds}
              />
              <Button
                icon={<SaveOutlined />}
                disabled={
                  cooldownSeconds === null || cooldownSeconds === automation.cooldown_seconds
                }
                loading={cooldownMutation.isPending}
                onClick={() => cooldownMutation.mutate()}
              >
                保存
              </Button>
            </Space>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card>
        <Tabs
          items={[
            {
              key: "conditions",
              label: `条件（${automation.conditions.length}）`,
              children: (
                <Table
                  rowKey={(condition) => `${condition.field}-${condition.operator}`}
                  columns={conditionColumns}
                  dataSource={automation.conditions}
                  pagination={false}
                  size="small"
                  locale={{ emptyText: <Empty description="无附加条件" /> }}
                />
              ),
            },
            {
              key: "runs",
              label: `执行历史（${runsQuery.data?.total ?? 0}）`,
              children: runsQuery.isError ? (
                <ApiErrorAlert error={runsQuery.error} />
              ) : (
                <Table
                  rowKey="id"
                  columns={runColumns}
                  dataSource={runsQuery.data?.data ?? []}
                  loading={runsQuery.isFetching}
                  pagination={false}
                  size="small"
                  expandable={{
                    expandedRowRender: (run) => (
                      <div className="expanded-json">
                        <JsonBlock value={run.matched_context} />
                        {run.error ? <JsonBlock value={run.error} /> : null}
                      </div>
                    ),
                  }}
                  locale={{ emptyText: <Empty description="暂无执行记录" /> }}
                />
              ),
            },
            {
              key: "action",
              label: "动作",
              children: (
                <JsonBlock value={automation.action as unknown as Record<string, unknown>} />
              ),
            },
          ]}
        />
      </Card>
    </section>
  );
}
