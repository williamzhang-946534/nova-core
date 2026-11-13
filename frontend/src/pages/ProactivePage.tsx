import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tag,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { ReloadOutlined } from "@ant-design/icons";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import PageLoading from "@/components/PageLoading";
import {
  acceptProactiveSuggestion,
  dismissProactiveSuggestion,
  feedbackProactiveSuggestion,
  listProactiveSuggestions,
  openProactiveSuggestion,
} from "@/api/intelligence";
import type { ProactiveSuggestion } from "@/types/intelligence";
import { formatDateTime, formatJson } from "@/utils/format";

const statuses = [
  "evaluated",
  "suppressed",
  "queued",
  "delivered",
  "opened",
  "accepted",
  "dismissed",
  "expired",
];
const triggers = [
  "trend",
  "anomaly",
  "goal_deviation",
  "task_failure",
  "coverage_gap",
  "device_fault",
  "cost_risk",
];

export default function ProactivePage() {
  const queryClient = useQueryClient();
  const [feedbackForm] = Form.useForm();
  const [dismissForm] = Form.useForm();
  const [status, setStatus] = useState<ProactiveSuggestion["status"] | undefined>();
  const [triggerType, setTriggerType] = useState<string | undefined>();
  const [importance, setImportance] = useState<string | undefined>();
  const [feedbackTarget, setFeedbackTarget] = useState<ProactiveSuggestion | null>(null);
  const [dismissTarget, setDismissTarget] = useState<ProactiveSuggestion | null>(null);

  const suggestionsQuery = useQuery({
    queryKey: ["proactive-suggestions", { status, triggerType, importance }],
    queryFn: () => listProactiveSuggestions({ status, triggerType, importance, pageSize: 50 }),
    placeholderData: keepPreviousData,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["proactive-suggestions"] });
  };
  const open = useMutation({ mutationFn: openProactiveSuggestion, onSuccess: invalidate });
  const accept = useMutation({ mutationFn: acceptProactiveSuggestion, onSuccess: invalidate });
  const feedback = useMutation({
    mutationFn: (input: { id: string; useful: boolean; correct: boolean; comment?: string }) =>
      feedbackProactiveSuggestion(input.id, input.useful, input.correct, input.comment),
    onSuccess: () => {
      setFeedbackTarget(null);
      invalidate();
    },
  });
  const dismiss = useMutation({
    mutationFn: (input: { id: string; suppress: boolean; hours: number }) =>
      dismissProactiveSuggestion(input.id, input.suppress, input.hours),
    onSuccess: () => {
      setDismissTarget(null);
      invalidate();
    },
  });

  const columns: ColumnsType<ProactiveSuggestion> = [
    {
      title: "建议",
      dataIndex: "title",
      render: (value: string, suggestion) => (
        <div>
          <strong>{value}</strong>
          <div className="secondary-text">{suggestion.message}</div>
        </div>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 115,
      render: (value: ProactiveSuggestion["status"]) => (
        <Tag
          color={
            value === "accepted"
              ? "green"
              : value === "dismissed"
                ? "red"
                : value === "delivered"
                  ? "blue"
                  : "gold"
          }
        >
          {value}
        </Tag>
      ),
    },
    { title: "触发", dataIndex: "trigger_type", width: 125 },
    {
      title: "重要性",
      dataIndex: "importance",
      width: 95,
      render: (value: string) => (
        <Tag color={value === "high" ? "red" : value === "normal" ? "blue" : "default"}>
          {value}
        </Tag>
      ),
    },
    { title: "自主级", dataIndex: "autonomy_level", width: 90 },
    { title: "创建", dataIndex: "created_at", render: formatDateTime, width: 165 },
    {
      title: "操作",
      key: "actions",
      fixed: "right",
      width: 250,
      render: (_, suggestion) => (
        <Space wrap>
          {suggestion.status === "delivered" || suggestion.status === "queued" ? (
            <Button
              size="small"
              loading={open.isPending && open.variables === suggestion.id}
              onClick={() => open.mutate(suggestion.id)}
            >
              打开
            </Button>
          ) : null}
          {suggestion.status !== "accepted" && suggestion.status !== "dismissed" ? (
            <>
              <Button
                size="small"
                type="primary"
                loading={accept.isPending && accept.variables === suggestion.id}
                onClick={() => accept.mutate(suggestion.id)}
              >
                接受
              </Button>
              <Button size="small" onClick={() => setDismissTarget(suggestion)}>
                忽略
              </Button>
            </>
          ) : null}
          <Button size="small" onClick={() => setFeedbackTarget(suggestion)}>
            反馈
          </Button>
        </Space>
      ),
    },
  ];

  if (suggestionsQuery.isPending) {
    return <PageLoading text="正在读取主动建议..." />;
  }

  return (
    <section className="page-stack">
      <header className="page-header">
        <div>
          <h1>主动建议</h1>
          <p>查看系统建议，接受或忽略建议，并反馈建议质量。</p>
        </div>
        <Button
          icon={<ReloadOutlined />}
          loading={suggestionsQuery.isFetching}
          onClick={() => void suggestionsQuery.refetch()}
        >
          刷新
        </Button>
      </header>

      {suggestionsQuery.isError ? <ApiErrorAlert error={suggestionsQuery.error} /> : null}
      {open.isError || accept.isError || feedback.isError || dismiss.isError ? (
        <Alert
          type="error"
          message="主动建议操作失败"
          description={String(open.error ?? accept.error ?? feedback.error ?? dismiss.error)}
        />
      ) : null}

      <Card>
        <Space className="filter-bar" wrap>
          <Select
            allowClear
            placeholder="状态"
            value={status}
            onChange={setStatus}
            className="fixed-select"
            options={statuses.map((value) => ({ value, label: value }))}
          />
          <Select
            allowClear
            placeholder="触发类型"
            value={triggerType}
            onChange={setTriggerType}
            className="fixed-select"
            options={triggers.map((value) => ({ value, label: value }))}
          />
          <Select
            allowClear
            placeholder="重要性"
            value={importance}
            onChange={setImportance}
            className="fixed-select"
            options={["low", "normal", "high"].map((value) => ({ value, label: value }))}
          />
        </Space>
      </Card>

      <Card title={`建议（${suggestionsQuery.data?.total ?? 0}）`}>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={suggestionsQuery.data?.data ?? []}
          loading={suggestionsQuery.isFetching}
          scroll={{ x: 1250 }}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          locale={{ emptyText: <Empty description="暂无主动建议" /> }}
          expandable={{
            expandedRowRender: (suggestion) => (
              <Space direction="vertical" size={8} style={{ width: "100%" }}>
                <Alert
                  message="候选动作"
                  description={formatJson(suggestion.candidate_action)}
                  type="info"
                />
                <Alert
                  message="证据引用"
                  description={formatJson(suggestion.evidence_refs)}
                  type="info"
                />
              </Space>
            ),
          }}
        />
      </Card>

      <Modal
        open={dismissTarget !== null}
        title="忽略建议"
        onCancel={() => setDismissTarget(null)}
        onOk={() => dismissForm.submit()}
        confirmLoading={dismiss.isPending}
      >
        <Form
          form={dismissForm}
          layout="vertical"
          initialValues={{ suppressFuture: false, hours: 24 }}
          onFinish={(values) => {
            if (dismissTarget)
              dismiss.mutate({
                id: dismissTarget.id,
                suppress: values.suppressFuture,
                hours: values.hours,
              });
          }}
        >
          <Form.Item name="suppressFuture" valuePropName="checked">
            <Checkbox>抑制同类后续建议</Checkbox>
          </Form.Item>
          <Form.Item name="hours" label="抑制时长（小时）">
            <InputNumber min={1} max={8760} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={feedbackTarget !== null}
        title="建议反馈"
        onCancel={() => setFeedbackTarget(null)}
        onOk={() => feedbackForm.submit()}
        confirmLoading={feedback.isPending}
      >
        <Form
          form={feedbackForm}
          layout="vertical"
          initialValues={{ useful: true, correct: true }}
          onFinish={(values) => {
            if (feedbackTarget)
              feedback.mutate({
                id: feedbackTarget.id,
                useful: values.useful,
                correct: values.correct,
                comment: values.comment,
              });
          }}
        >
          <Form.Item name="useful" label="有用" initialValue={true}>
            <Select
              options={[
                { value: true, label: "有用" },
                { value: false, label: "无用" },
              ]}
            />
          </Form.Item>
          <Form.Item name="correct" label="正确" initialValue={true}>
            <Select
              options={[
                { value: true, label: "正确" },
                { value: false, label: "不正确" },
              ]}
            />
          </Form.Item>
          <Form.Item name="comment" label="备注">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </section>
  );
}
