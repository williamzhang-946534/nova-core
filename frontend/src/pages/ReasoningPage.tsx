import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Table,
  Tag,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { DeleteOutlined, ExperimentOutlined, ReloadOutlined } from "@ant-design/icons";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import PageLoading from "@/components/PageLoading";
import {
  createReasoningSession,
  deleteReasoningSession,
  getReasoningSession,
  listReasoningEvidence,
  listReasoningHypotheses,
  listReasoningSessions,
} from "@/api/intelligence";
import type { ReasoningSession } from "@/types/intelligence";
import { formatDateTime, formatJson } from "@/utils/format";

const statusColors: Record<string, string> = {
  running: "blue",
  completed: "green",
  failed: "red",
};

export default function ReasoningPage() {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<ReasoningSession["status"] | undefined>();
  const [environmentId, setEnvironmentId] = useState<string | undefined>();
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);

  const sessionsQuery = useQuery({
    queryKey: ["reasoning-sessions", { status, environmentId }],
    queryFn: () => listReasoningSessions({ status, environmentId, pageSize: 50 }),
    placeholderData: keepPreviousData,
  });
  const sessionId = selectedSessionId ?? sessionsQuery.data?.data[0]?.id ?? null;
  const sessionQuery = useQuery({
    queryKey: ["reasoning-session", sessionId],
    queryFn: () => getReasoningSession(sessionId ?? ""),
    enabled: sessionId !== null,
  });
  const evidenceQuery = useQuery({
    queryKey: ["reasoning-evidence", sessionId],
    queryFn: () => listReasoningEvidence(sessionId ?? ""),
    enabled: sessionId !== null,
  });
  const hypothesesQuery = useQuery({
    queryKey: ["reasoning-hypotheses", sessionId],
    queryFn: () => listReasoningHypotheses({ sessionId: sessionId ?? "" }),
    enabled: sessionId !== null,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["reasoning-sessions"] });
    void queryClient.invalidateQueries({ queryKey: ["reasoning-session", sessionId] });
    void queryClient.invalidateQueries({ queryKey: ["reasoning-evidence", sessionId] });
    void queryClient.invalidateQueries({ queryKey: ["reasoning-hypotheses", sessionId] });
  };
  const diagnose = useMutation({
    mutationFn: createReasoningSession,
    onSuccess: (session) => {
      setSelectedSessionId(session.id);
      invalidate();
      sessionForm.resetFields();
    },
  });
  const remove = useMutation({
    mutationFn: deleteReasoningSession,
    onSuccess: () => {
      setSelectedSessionId(null);
      invalidate();
    },
  });
  const [sessionForm] = Form.useForm();

  const columns: ColumnsType<ReasoningSession> = [
    { title: "问题", dataIndex: "question", render: (value: string) => <strong>{value}</strong> },
    {
      title: "状态",
      dataIndex: "status",
      width: 115,
      render: (value: ReasoningSession["status"]) => <Tag color={statusColors[value]}>{value}</Tag>,
    },
    { title: "触发", dataIndex: "trigger", width: 95 },
    { title: "环境", dataIndex: "environment_id", width: 130 },
    { title: "开始", dataIndex: "started_at", render: formatDateTime, width: 165 },
    {
      title: "操作",
      key: "actions",
      fixed: "right",
      render: (_, session) => (
        <Space>
          <Button size="small" onClick={() => setSelectedSessionId(session.id)}>
            详情
          </Button>
          <Button
            size="small"
            danger
            icon={<DeleteOutlined />}
            loading={remove.isPending && remove.variables === session.id}
            onClick={() => remove.mutate(session.id)}
          />
        </Space>
      ),
    },
  ];

  if (sessionsQuery.isPending) {
    return <PageLoading text="正在读取推理会话..." />;
  }

  return (
    <section className="page-stack">
      <header className="page-header">
        <div>
          <h1>智能推理</h1>
          <p>发起受限诊断，检查证据、假设和确定性/AI 候选结论。</p>
        </div>
        <Button
          icon={<ReloadOutlined />}
          loading={sessionsQuery.isFetching}
          onClick={() => void sessionsQuery.refetch()}
        >
          刷新
        </Button>
      </header>

      {sessionsQuery.isError ? <ApiErrorAlert error={sessionsQuery.error} /> : null}
      {diagnose.isError ? <ApiErrorAlert error={diagnose.error} /> : null}
      {remove.isError ? <ApiErrorAlert error={remove.error} /> : null}

      <Card title="发起诊断">
        <Form
          form={sessionForm}
          layout="vertical"
          onFinish={(values) =>
            diagnose.mutate({
              question: values.question,
              environmentId: values.environmentId || undefined,
              spaceName: values.spaceName || undefined,
              entityId: values.entityId || undefined,
              attribute: values.attribute || undefined,
              lookbackSeconds: values.lookbackSeconds,
            })
          }
        >
          <Space wrap size={12} align="end">
            <Form.Item
              name="question"
              label="诊断问题"
              rules={[{ required: true, message: "请输入问题" }]}
              style={{ minWidth: 320 }}
            >
              <Input.TextArea rows={2} placeholder="为什么客厅温度持续偏高？" />
            </Form.Item>
            <Form.Item name="environmentId" label="环境 ID">
              <Input allowClear />
            </Form.Item>
            <Form.Item name="spaceName" label="空间名称">
              <Input allowClear />
            </Form.Item>
            <Form.Item name="entityId" label="实体 ID">
              <Input allowClear />
            </Form.Item>
            <Form.Item name="attribute" label="属性">
              <Input allowClear />
            </Form.Item>
            <Form.Item name="lookbackSeconds" label="回溯秒数" initialValue={86400}>
              <InputNumber min={60} max={31622400} />
            </Form.Item>
            <Form.Item>
              <Button
                type="primary"
                htmlType="submit"
                icon={<ExperimentOutlined />}
                loading={diagnose.isPending}
              >
                诊断
              </Button>
            </Form.Item>
          </Space>
        </Form>
        {diagnose.isSuccess ? (
          <Alert type="success" message="诊断完成" description={diagnose.data.id} />
        ) : null}
      </Card>

      <Card title={`推理会话（${sessionsQuery.data?.total ?? 0}）`}>
        <Space className="filter-bar" wrap style={{ marginBottom: 16 }}>
          <Select
            allowClear
            placeholder="状态"
            value={status}
            onChange={setStatus}
            className="fixed-select"
            options={Object.keys(statusColors).map((value) => ({ value, label: value }))}
          />
          <Input.Search
            allowClear
            placeholder="环境 ID"
            value={environmentId}
            onChange={(event) => setEnvironmentId(event.target.value || undefined)}
            onSearch={setEnvironmentId}
            style={{ width: 240 }}
          />
        </Space>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={sessionsQuery.data?.data ?? []}
          loading={sessionsQuery.isFetching}
          scroll={{ x: 1050 }}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          locale={{ emptyText: <Empty description="暂无推理会话" /> }}
        />
      </Card>

      {sessionQuery.isPending && sessionId ? <PageLoading text="正在读取诊断详情..." /> : null}
      {sessionQuery.isError ? <ApiErrorAlert error={sessionQuery.error} /> : null}
      {sessionQuery.data ? (
        <div className="two-column">
          <Card title="诊断结论">
            <Descriptions
              size="small"
              bordered
              column={1}
              items={[
                { key: "question", label: "问题", children: sessionQuery.data.question },
                { key: "status", label: "状态", children: sessionQuery.data.status },
                { key: "scope", label: "范围", children: formatJson(sessionQuery.data.scope) },
                {
                  key: "diagnosis",
                  label: "结论",
                  children: formatJson(sessionQuery.data.diagnosis),
                },
                {
                  key: "actors",
                  label: "发起者",
                  children: `${sessionQuery.data.actor_type}/${sessionQuery.data.actor_id}`,
                },
              ]}
            />
          </Card>
          <Card title="假设">
            {hypothesesQuery.isError ? <ApiErrorAlert error={hypothesesQuery.error} /> : null}
            <Table
              rowKey="id"
              size="small"
              loading={hypothesesQuery.isFetching}
              dataSource={hypothesesQuery.data?.data ?? []}
              pagination={false}
              columns={[
                { title: "陈述", dataIndex: "statement" },
                {
                  title: "类型",
                  dataIndex: "hypothesis_type",
                  render: (value: string) => <Tag>{value}</Tag>,
                },
                {
                  title: "状态",
                  dataIndex: "status",
                  render: (value: string) => (
                    <Tag
                      color={value === "supported" ? "green" : value === "refuted" ? "red" : "gold"}
                    >
                      {value}
                    </Tag>
                  ),
                },
                { title: "置信", dataIndex: "confidence_level" },
              ]}
              locale={{ emptyText: <Empty description="暂无假设" /> }}
            />
          </Card>
        </div>
      ) : null}

      <Card title="证据">
        {evidenceQuery.isError ? <ApiErrorAlert error={evidenceQuery.error} /> : null}
        <Table
          rowKey="id"
          size="small"
          loading={evidenceQuery.isFetching}
          dataSource={evidenceQuery.data?.data ?? []}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          columns={[
            { title: "陈述", dataIndex: "statement" },
            { title: "来源", dataIndex: "source_type" },
            {
              title: "分类",
              dataIndex: "classification",
              render: (value: string) => <Tag>{value}</Tag>,
            },
            { title: "质量", dataIndex: "quality_status" },
            {
              title: "信任度",
              dataIndex: "trust_level",
              render: (value: number) => `${Math.round(value * 100)}%`,
            },
            { title: "时间", dataIndex: "source_time", render: formatDateTime },
          ]}
          locale={{ emptyText: <Empty description="暂无证据" /> }}
        />
      </Card>
    </section>
  );
}
