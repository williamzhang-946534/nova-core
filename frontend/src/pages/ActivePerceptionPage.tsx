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
  Select,
  Space,
  Table,
  Tag,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { EyeOutlined, ReloadOutlined } from "@ant-design/icons";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import PageLoading from "@/components/PageLoading";
import {
  authorizeActivePerception,
  evaluateActivePerception,
  executeActivePerception,
  expireActivePerceptionRequests,
  listActivePerceptionRequests,
  rejectActivePerception,
} from "@/api/intelligence";
import type { ActivePerceptionRequest } from "@/types/intelligence";
import { formatDateTime, formatJson } from "@/utils/format";

const statuses = [
  "proposed",
  "awaiting_consent",
  "rejected",
  "queued",
  "executed",
  "fulfilled",
  "unavailable",
  "expired",
];
const gapTypes = [
  "space_coverage",
  "time_coverage",
  "quality",
  "entity_identity",
  "post_action_verification",
  "procedure",
];

export default function ActivePerceptionPage() {
  const queryClient = useQueryClient();
  const [evaluateForm] = Form.useForm();
  const [status, setStatus] = useState<ActivePerceptionRequest["status"] | undefined>();
  const [gapType, setGapType] = useState<string | undefined>();
  const [privacyLevel, setPrivacyLevel] = useState<string | undefined>();

  const requestsQuery = useQuery({
    queryKey: ["active-perception", { status, gapType, privacyLevel }],
    queryFn: () => listActivePerceptionRequests({ status, gapType, privacyLevel, pageSize: 50 }),
    placeholderData: keepPreviousData,
  });
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["active-perception"] });
  };
  const evaluate = useMutation({
    mutationFn: evaluateActivePerception,
    onSuccess: () => {
      evaluateForm.resetFields();
      invalidate();
    },
  });
  const authorize = useMutation({
    mutationFn: (id: string) => authorizeActivePerception(id),
    onSuccess: invalidate,
  });
  const reject = useMutation({
    mutationFn: (id: string) => rejectActivePerception(id, "Rejected from Web console"),
    onSuccess: invalidate,
  });
  const execute = useMutation({
    mutationFn: executeActivePerception,
    onSuccess: invalidate,
  });
  const expire = useMutation({
    mutationFn: expireActivePerceptionRequests,
    onSuccess: invalidate,
  });

  const columns: ColumnsType<ActivePerceptionRequest> = [
    {
      title: "问题",
      dataIndex: "question",
      render: (value: string, request) => (
        <div>
          <strong>{value}</strong>
          <div className="secondary-text">{request.attribute ?? "-"}</div>
        </div>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 135,
      render: (value: ActivePerceptionRequest["status"]) => (
        <Tag
          color={
            value === "fulfilled"
              ? "green"
              : value === "rejected" || value === "unavailable"
                ? "red"
                : value === "awaiting_consent"
                  ? "gold"
                  : "blue"
          }
        >
          {value}
        </Tag>
      ),
    },
    { title: "缺口", dataIndex: "gap_type", width: 150 },
    {
      title: "隐私",
      dataIndex: "privacy_level",
      width: 100,
      render: (value: string) => (
        <Tag color={value === "sensitive" ? "volcano" : "default"}>{value}</Tag>
      ),
    },
    {
      title: "授权",
      key: "consent",
      width: 100,
      render: (_, request) => (request.requires_user_consent ? "必需" : "不需要"),
    },
    { title: "创建", dataIndex: "created_at", render: formatDateTime, width: 165 },
    {
      title: "操作",
      key: "actions",
      fixed: "right",
      width: 220,
      render: (_, request) => (
        <Space wrap>
          {request.status === "proposed" || request.status === "awaiting_consent" ? (
            <>
              <Button
                size="small"
                type="primary"
                loading={authorize.isPending && authorize.variables === request.id}
                onClick={() => authorize.mutate(request.id)}
              >
                授权
              </Button>
              <Button
                size="small"
                danger
                loading={reject.isPending && reject.variables === request.id}
                onClick={() => reject.mutate(request.id)}
              >
                拒绝
              </Button>
            </>
          ) : null}
          {request.status === "proposed" ||
          request.status === "queued" ||
          request.status === "awaiting_consent" ? (
            <Button
              size="small"
              loading={execute.isPending && execute.variables === request.id}
              onClick={() => execute.mutate(request.id)}
            >
              执行
            </Button>
          ) : null}
        </Space>
      ),
    },
  ];

  if (requestsQuery.isPending) {
    return <PageLoading text="正在读取主动感知请求..." />;
  }

  return (
    <section className="page-stack">
      <header className="page-header">
        <div>
          <h1>主动感知</h1>
          <p>识别数据缺口，经授权后执行只读观测，并保留完整执行痕迹。</p>
        </div>
        <Space>
          <Button loading={expire.isPending} onClick={() => expire.mutate()}>
            清理过期请求
          </Button>
          <Button
            icon={<ReloadOutlined />}
            loading={requestsQuery.isFetching}
            onClick={() => void requestsQuery.refetch()}
          >
            刷新
          </Button>
        </Space>
      </header>

      {requestsQuery.isError ? <ApiErrorAlert error={requestsQuery.error} /> : null}
      {evaluate.isError ||
      authorize.isError ||
      reject.isError ||
      execute.isError ||
      expire.isError ? (
        <Alert
          type="error"
          message="主动感知操作失败"
          description={String(
            evaluate.error ?? authorize.error ?? reject.error ?? execute.error ?? expire.error,
          )}
        />
      ) : null}
      {expire.isSuccess ? (
        <Alert type="success" message={`已处理过期请求：${expire.data.expired_count}`} />
      ) : null}

      <Card title="识别数据缺口">
        <Form form={evaluateForm} layout="vertical" onFinish={(values) => evaluate.mutate(values)}>
          <Space wrap size={12} align="end">
            <Form.Item
              name="question"
              label="问题"
              rules={[{ required: true, message: "请输入问题" }]}
              style={{ minWidth: 320 }}
            >
              <Input.TextArea rows={2} placeholder="客厅当前温度是多少？" />
            </Form.Item>
            <Form.Item
              name="attribute"
              label="属性"
              rules={[{ required: true, message: "请输入属性" }]}
            >
              <Input placeholder="temperature" />
            </Form.Item>
            <Form.Item name="environmentId" label="环境 ID">
              <Input allowClear />
            </Form.Item>
            <Form.Item name="reasoningSessionId" label="推理会话 ID">
              <Input allowClear />
            </Form.Item>
            <Form.Item name="hypothesisId" label="假设 ID">
              <Input allowClear />
            </Form.Item>
            <Form.Item name="spaceId" label="空间 ID">
              <Input allowClear />
            </Form.Item>
            <Form.Item name="entityId" label="实体 ID">
              <Input allowClear />
            </Form.Item>
            <Form.Item>
              <Button
                type="primary"
                htmlType="submit"
                icon={<EyeOutlined />}
                loading={evaluate.isPending}
              >
                评估
              </Button>
            </Form.Item>
          </Space>
        </Form>
        {evaluate.isSuccess ? (
          <Alert
            type="success"
            message="请求已创建"
            description={evaluate.data.status}
            style={{ marginTop: 16 }}
          />
        ) : null}
      </Card>

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
            placeholder="缺口类型"
            value={gapType}
            onChange={setGapType}
            className="fixed-select"
            options={gapTypes.map((value) => ({ value, label: value }))}
          />
          <Select
            allowClear
            placeholder="隐私级别"
            value={privacyLevel}
            onChange={setPrivacyLevel}
            className="fixed-select"
            options={["normal", "sensitive"].map((value) => ({ value, label: value }))}
          />
        </Space>
      </Card>

      <Card title={`感知请求（${requestsQuery.data?.total ?? 0}）`}>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={requestsQuery.data?.data ?? []}
          loading={requestsQuery.isFetching}
          scroll={{ x: 1300 }}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          locale={{ emptyText: <Empty description="暂无感知请求" /> }}
          expandable={{
            expandedRowRender: (request) => (
              <Descriptions
                size="small"
                bordered
                column={{ xs: 1, md: 2 }}
                items={[
                  { key: "input", label: "提议输入", children: formatJson(request.proposed_input) },
                  {
                    key: "range",
                    label: "需要时间范围",
                    children: formatJson(request.needed_time_range),
                  },
                  {
                    key: "capability",
                    label: "提议能力",
                    children: request.proposed_capability ?? "-",
                  },
                  {
                    key: "trace",
                    label: "执行痕迹",
                    children: formatJson(request.execution_trace ?? {}),
                  },
                  {
                    key: "reason",
                    label: "不可用原因",
                    children: request.unavailable_reason ?? "-",
                  },
                  {
                    key: "source",
                    label: "结果来源",
                    children: request.fulfilled_by_type
                      ? `${request.fulfilled_by_type}/${request.fulfilled_by_id}`
                      : "-",
                  },
                ]}
              />
            ),
          }}
        />
      </Card>
    </section>
  );
}
