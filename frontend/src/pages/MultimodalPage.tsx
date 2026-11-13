import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { ReloadOutlined } from "@ant-design/icons";
import { useState } from "react";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import PageLoading from "@/components/PageLoading";
import {
  createMultimodalConsent,
  createMultimodalGrant,
  getMultimodalCapabilities,
  listMultimodalAuditEvents,
  listMultimodalConsents,
  listMultimodalExtractions,
  listMultimodalGrants,
  listMultimodalProviders,
  purgeMultimodalAsset,
  revokeMultimodalConsent,
  revokeMultimodalGrant,
} from "@/api/governance";
import type {
  MultimodalAuditEvent,
  MultimodalConsent,
  MultimodalDataAccessGrant,
  MultimodalExtraction,
} from "@/types/governance";
import { formatDateTime, formatJson } from "@/utils/format";

const consentTypes = ["capture", "processing", "retention"];
const modalities = ["image", "video_frame", "audio"];
const purposes = [
  "user_query",
  "scene_check",
  "ocr",
  "speech_input",
  "audio_event",
  "active_perception",
  "accessibility_output",
];
const grantModalities = ["image", "video_frame", "audio", "sensor", "device"];

export default function MultimodalPage() {
  const queryClient = useQueryClient();
  const [environmentId, setEnvironmentId] = useState("");
  const [auditEnvironmentId, setAuditEnvironmentId] = useState("");
  const [auditAction, setAuditAction] = useState<string | undefined>();
  const [consentForm] = Form.useForm();
  const [grantForm] = Form.useForm();
  const [assetId, setAssetId] = useState("");

  const capabilitiesQuery = useQuery({
    queryKey: ["multimodal-capabilities"],
    queryFn: getMultimodalCapabilities,
  });
  const providersQuery = useQuery({
    queryKey: ["multimodal-providers"],
    queryFn: listMultimodalProviders,
  });
  const consentsQuery = useQuery({
    queryKey: ["multimodal-consents", environmentId],
    queryFn: () => listMultimodalConsents(environmentId || undefined),
  });
  const grantsQuery = useQuery({
    queryKey: ["multimodal-grants", environmentId],
    queryFn: () => listMultimodalGrants(environmentId || undefined),
  });
  const auditQuery = useQuery({
    queryKey: ["multimodal-audit", auditEnvironmentId, auditAction],
    queryFn: () => listMultimodalAuditEvents(auditEnvironmentId, auditAction, 200),
    enabled: auditEnvironmentId.trim().length > 0,
  });
  const extractionsQuery = useQuery({
    queryKey: ["multimodal-extractions"],
    queryFn: listMultimodalExtractions,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["multimodal-consents"] });
    void queryClient.invalidateQueries({ queryKey: ["multimodal-grants"] });
    void queryClient.invalidateQueries({ queryKey: ["multimodal-capabilities"] });
  };
  const createConsent = useMutation({
    mutationFn: createMultimodalConsent,
    onSuccess: () => {
      consentForm.resetFields();
      invalidate();
      void message.success("Consent 已创建");
    },
  });
  const revokeConsent = useMutation({ mutationFn: revokeMultimodalConsent, onSuccess: invalidate });
  const createGrant = useMutation({
    mutationFn: createMultimodalGrant,
    onSuccess: () => {
      grantForm.resetFields();
      invalidate();
      void message.success("访问授权已创建");
    },
  });
  const revokeGrant = useMutation({ mutationFn: revokeMultimodalGrant, onSuccess: invalidate });
  const purgeAsset = useMutation({
    mutationFn: purgeMultimodalAsset,
    onSuccess: () => {
      setAssetId("");
      invalidate();
      void queryClient.invalidateQueries({ queryKey: ["multimodal-extractions"] });
      void message.success("媒体清理请求已完成");
    },
  });

  const consentColumns: ColumnsType<MultimodalConsent> = [
    { title: "用户", dataIndex: "user_id", width: 150 },
    { title: "类型", dataIndex: "consent_type", width: 110 },
    { title: "模态", dataIndex: "modality", width: 110 },
    { title: "用途", dataIndex: "purpose", width: 165 },
    {
      title: "Provider",
      dataIndex: "provider_name",
      render: (value?: string | null) => value ?? "-",
    },
    {
      title: "空间",
      dataIndex: "space_ids",
      render: (value: string[]) => value.join(", ") || "全部",
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 105,
      render: (value: string) => (
        <Tag color={value === "active" ? "green" : "default"}>{value}</Tag>
      ),
    },
    { title: "授权时间", dataIndex: "granted_at", render: formatDateTime, width: 165 },
    { title: "过期", dataIndex: "expires_at", render: formatDateTime, width: 165 },
    {
      title: "操作",
      key: "actions",
      fixed: "right",
      width: 95,
      render: (_, record) =>
        record.status === "active" ? (
          <Button
            size="small"
            danger
            loading={revokeConsent.isPending && revokeConsent.variables === record.id}
            onClick={() => revokeConsent.mutate(record.id)}
          >
            撤销
          </Button>
        ) : null,
    },
  ];

  const grantColumns: ColumnsType<MultimodalDataAccessGrant> = [
    { title: "用户", dataIndex: "user_id", width: 150 },
    { title: "模态", dataIndex: "modalities", render: (value: string[]) => value.join(", ") },
    { title: "空间", dataIndex: "space_ids", render: (value: string[]) => value.join(", ") },
    {
      title: "状态",
      dataIndex: "status",
      width: 105,
      render: (value: string) => (
        <Tag color={value === "active" ? "green" : "default"}>{value}</Tag>
      ),
    },
    { title: "授权时间", dataIndex: "granted_at", render: formatDateTime, width: 165 },
    { title: "过期", dataIndex: "expires_at", render: formatDateTime, width: 165 },
    {
      title: "操作",
      key: "actions",
      fixed: "right",
      width: 95,
      render: (_, record) =>
        record.status === "active" ? (
          <Button
            size="small"
            danger
            loading={revokeGrant.isPending && revokeGrant.variables === record.id}
            onClick={() => revokeGrant.mutate(record.id)}
          >
            撤销
          </Button>
        ) : null,
    },
  ];

  const auditColumns: ColumnsType<MultimodalAuditEvent> = [
    { title: "动作", dataIndex: "action", width: 210 },
    { title: "Actor", dataIndex: "actor_id", render: (value?: string | null) => value ?? "-" },
    { title: "主体", dataIndex: "subject_id", render: (value?: string | null) => value ?? "-" },
    { title: "发生时间", dataIndex: "occurred_at", render: formatDateTime, width: 165 },
    { title: "详情", dataIndex: "details", render: formatJson },
  ];

  const extractionColumns: ColumnsType<MultimodalExtraction> = [
    { title: "媒体", dataIndex: "media_asset_id", width: 250 },
    { title: "结果类型", dataIndex: "result_kind", width: 150 },
    { title: "置信级别", dataIndex: "confidence_level", width: 120 },
    { title: "质量", dataIndex: "quality_status", width: 120 },
    { title: "模型", dataIndex: "model_id", width: 190 },
    { title: "有效开始", dataIndex: "valid_from", render: formatDateTime, width: 165 },
    { title: "结果", dataIndex: "result", render: formatJson },
  ];

  if (capabilitiesQuery.isPending) {
    return <PageLoading text="正在读取多模态能力..." />;
  }

  return (
    <section className="page-stack">
      <header className="page-header">
        <div>
          <h1>多模态治理</h1>
          <p>管理采集授权、数据访问授权、Provider 能力、审计记录和媒体清理。</p>
        </div>
        <Button
          icon={<ReloadOutlined />}
          loading={capabilitiesQuery.isFetching || providersQuery.isFetching}
          onClick={() => invalidate()}
        >
          刷新
        </Button>
      </header>

      {capabilitiesQuery.isError ? <ApiErrorAlert error={capabilitiesQuery.error} /> : null}
      {providersQuery.isError ? <ApiErrorAlert error={providersQuery.error} /> : null}

      <Card title="能力开关">
        <Descriptions
          size="small"
          bordered
          column={4}
          items={[
            {
              key: "camera",
              label: "摄像头",
              children: capabilitiesQuery.data?.camera_capture_enabled ? "启用" : "禁用",
            },
            {
              key: "microphone",
              label: "麦克风",
              children: capabilitiesQuery.data?.microphone_capture_enabled ? "启用" : "禁用",
            },
            {
              key: "continuous",
              label: "持续视频",
              children: capabilitiesQuery.data?.continuous_video_analysis_enabled ? "启用" : "禁用",
            },
            {
              key: "cloud",
              label: "云处理",
              children: capabilitiesQuery.data?.cloud_processing_enabled ? "启用" : "禁用",
            },
          ]}
        />
      </Card>

      <Tabs
        items={[
          {
            key: "providers",
            label: "Provider",
            children: (
              <Table
                rowKey="id"
                dataSource={providersQuery.data ?? []}
                loading={providersQuery.isFetching}
                scroll={{ x: 1400 }}
                pagination={false}
                columns={[
                  { title: "名称", dataIndex: "provider_name" },
                  { title: "能力", dataIndex: "capability", width: 150 },
                  { title: "处理位置", dataIndex: "processing_location", width: 125 },
                  { title: "模型", dataIndex: "model_id", width: 190 },
                  {
                    title: "超时",
                    dataIndex: "timeout_ms",
                    width: 100,
                    render: (value: number) => `${value} ms`,
                  },
                  { title: "上限", dataIndex: "max_bytes", width: 120 },
                  {
                    title: "状态",
                    key: "state",
                    width: 165,
                    render: (_, record) => (
                      <Space>
                        <Tag color={record.enabled ? "green" : "default"}>
                          {record.enabled ? "启用" : "禁用"}
                        </Tag>
                        {record.is_default ? <Tag color="blue">默认</Tag> : null}
                      </Space>
                    ),
                  },
                  {
                    title: "数据策略",
                    dataIndex: "data_sent_policy",
                    render: formatJson,
                  },
                ]}
              />
            ),
          },
          {
            key: "consents",
            label: "Consent",
            children: (
              <Space direction="vertical" size={16} style={{ width: "100%" }}>
                <Space wrap>
                  <Input.Search
                    allowClear
                    placeholder="按环境过滤"
                    value={environmentId}
                    onChange={(event) => setEnvironmentId(event.target.value)}
                    onSearch={setEnvironmentId}
                    style={{ width: 260 }}
                  />
                </Space>
                {createConsent.isError ? <ApiErrorAlert error={createConsent.error} /> : null}
                {revokeConsent.isError ? <ApiErrorAlert error={revokeConsent.error} /> : null}
                <Card title="创建本地处理 Consent">
                  <Form
                    form={consentForm}
                    layout="vertical"
                    onFinish={(values) => createConsent.mutate(values)}
                  >
                    <Space wrap size={12} align="end">
                      <Form.Item
                        name="environmentId"
                        label="环境 ID"
                        rules={[{ required: true, message: "请输入环境 ID" }]}
                      >
                        <Input style={{ width: 220 }} />
                      </Form.Item>
                      <Form.Item
                        name="userId"
                        label="用户 ID"
                        rules={[{ required: true, message: "请输入用户 ID" }]}
                      >
                        <Input style={{ width: 180 }} />
                      </Form.Item>
                      <Form.Item
                        name="consentType"
                        label="类型"
                        initialValue="processing"
                        rules={[{ required: true }]}
                      >
                        <Select
                          className="fixed-select"
                          options={consentTypes.map((value) => ({ value, label: value }))}
                        />
                      </Form.Item>
                      <Form.Item
                        name="modality"
                        label="模态"
                        initialValue="audio"
                        rules={[{ required: true }]}
                      >
                        <Select
                          className="fixed-select"
                          options={modalities.map((value) => ({ value, label: value }))}
                        />
                      </Form.Item>
                      <Form.Item
                        name="purpose"
                        label="用途"
                        initialValue="speech_input"
                        rules={[{ required: true }]}
                      >
                        <Select
                          className="fixed-select"
                          options={purposes.map((value) => ({ value, label: value }))}
                        />
                      </Form.Item>
                      <Form.Item name="providerName" label="Provider">
                        <Input allowClear style={{ width: 180 }} />
                      </Form.Item>
                      <Form.Item name="expiresAt" label="过期时间">
                        <Input type="datetime-local" style={{ width: 220 }} />
                      </Form.Item>
                      <Form.Item>
                        <Button type="primary" htmlType="submit" loading={createConsent.isPending}>
                          创建
                        </Button>
                      </Form.Item>
                    </Space>
                  </Form>
                </Card>
                <Table
                  rowKey="id"
                  dataSource={consentsQuery.data ?? []}
                  loading={consentsQuery.isFetching}
                  scroll={{ x: 1450 }}
                  pagination={{ pageSize: 10, showSizeChanger: false }}
                  columns={consentColumns}
                />
              </Space>
            ),
          },
          {
            key: "grants",
            label: "数据访问",
            children: (
              <Space direction="vertical" size={16} style={{ width: "100%" }}>
                <Space wrap>
                  <Input.Search
                    allowClear
                    placeholder="按环境过滤"
                    value={environmentId}
                    onChange={(event) => setEnvironmentId(event.target.value)}
                    onSearch={setEnvironmentId}
                    style={{ width: 260 }}
                  />
                </Space>
                {createGrant.isError ? <ApiErrorAlert error={createGrant.error} /> : null}
                {revokeGrant.isError ? <ApiErrorAlert error={revokeGrant.error} /> : null}
                <Card title="创建数据访问授权">
                  <Form
                    form={grantForm}
                    layout="vertical"
                    onFinish={(values) => createGrant.mutate(values)}
                  >
                    <Space wrap size={12} align="end">
                      <Form.Item
                        name="environmentId"
                        label="环境 ID"
                        rules={[{ required: true, message: "请输入环境 ID" }]}
                      >
                        <Input style={{ width: 220 }} />
                      </Form.Item>
                      <Form.Item
                        name="userId"
                        label="用户 ID"
                        rules={[{ required: true, message: "请输入用户 ID" }]}
                      >
                        <Input style={{ width: 180 }} />
                      </Form.Item>
                      <Form.Item
                        name="modalities"
                        label="可访问模态"
                        rules={[{ required: true, message: "请选择模态" }]}
                      >
                        <Select
                          mode="multiple"
                          className="fixed-select"
                          options={grantModalities.map((value) => ({ value, label: value }))}
                        />
                      </Form.Item>
                      <Form.Item
                        name="spaceIds"
                        label="空间 ID 列表"
                        rules={[{ required: true, message: "至少一个空间" }]}
                      >
                        <Select
                          mode="tags"
                          className="fixed-select"
                          open={false}
                          tokenSeparators={[","]}
                        />
                      </Form.Item>
                      <Form.Item name="expiresAt" label="过期时间">
                        <Input type="datetime-local" style={{ width: 220 }} />
                      </Form.Item>
                      <Form.Item>
                        <Button type="primary" htmlType="submit" loading={createGrant.isPending}>
                          创建
                        </Button>
                      </Form.Item>
                    </Space>
                  </Form>
                </Card>
                <Table
                  rowKey="id"
                  dataSource={grantsQuery.data ?? []}
                  loading={grantsQuery.isFetching}
                  scroll={{ x: 1150 }}
                  pagination={{ pageSize: 10, showSizeChanger: false }}
                  columns={grantColumns}
                />
              </Space>
            ),
          },
          {
            key: "audit",
            label: "审计",
            children: (
              <Space direction="vertical" size={16} style={{ width: "100%" }}>
                {auditQuery.isError ? <ApiErrorAlert error={auditQuery.error} /> : null}
                <Space wrap>
                  <Input.Search
                    allowClear
                    placeholder="审计环境 ID（必填）"
                    value={auditEnvironmentId}
                    onChange={(event) => setAuditEnvironmentId(event.target.value)}
                    onSearch={setAuditEnvironmentId}
                    style={{ width: 280 }}
                  />
                  <Input.Search
                    allowClear
                    placeholder="动作过滤"
                    value={auditAction}
                    onChange={(event) => setAuditAction(event.target.value || undefined)}
                    onSearch={setAuditAction}
                    style={{ width: 220 }}
                  />
                </Space>
                <Table
                  rowKey="id"
                  dataSource={auditQuery.data ?? []}
                  loading={auditQuery.isFetching}
                  scroll={{ x: 1300 }}
                  pagination={{ pageSize: 10, showSizeChanger: false }}
                  columns={auditColumns}
                />
              </Space>
            ),
          },
          {
            key: "media",
            label: "提取与清理",
            children: (
              <Space direction="vertical" size={16} style={{ width: "100%" }}>
                {purgeAsset.isError ? <ApiErrorAlert error={purgeAsset.error} /> : null}
                {extractionsQuery.isError ? (
                  <Alert
                    type="error"
                    showIcon
                    message="提取结果加载失败"
                    description={extractionsQuery.error.message}
                  />
                ) : null}
                <Card title="按媒体 ID 清理">
                  <Space wrap>
                    <Input
                      allowClear
                      placeholder="媒体资产 ID"
                      value={assetId}
                      onChange={(event) => setAssetId(event.target.value)}
                      style={{ width: 320 }}
                    />
                    <Button
                      danger
                      loading={purgeAsset.isPending}
                      disabled={assetId.trim().length === 0}
                      onClick={() => purgeAsset.mutate(assetId.trim())}
                    >
                      清理媒体
                    </Button>
                  </Space>
                </Card>
                <Table
                  rowKey="id"
                  dataSource={extractionsQuery.data ?? []}
                  loading={extractionsQuery.isFetching}
                  scroll={{ x: 1350 }}
                  pagination={{ pageSize: 10, showSizeChanger: false }}
                  columns={extractionColumns}
                />
              </Space>
            ),
          },
        ]}
      />
    </section>
  );
}
