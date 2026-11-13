import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Checkbox,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
} from "antd";
import { Alert } from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  FormOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
} from "@ant-design/icons";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import JsonBlock from "@/components/JsonBlock";
import PageLoading from "@/components/PageLoading";
import StatusTag from "@/components/StatusTag";
import {
  cleanupMemories,
  compressMemories,
  confirmMemory,
  confirmPreference,
  correctMemory,
  createMemory,
  createPreference,
  deleteMemory,
  deletePreference,
  distillMemories,
  getMemory,
  getMemoryGraph,
  listMemories,
  listPreferences,
  memoryHistory,
  memoryRevisions,
  retrieveMemory,
  updatePreference,
} from "@/api/memory";
import type {
  MemoryGraph,
  MemoryItem,
  MemorySourceType,
  MemoryStatus,
  MemoryType,
  PreferenceItem,
  QuestionType,
} from "@/types/memory";
import { formatDateTime, formatJson } from "@/utils/format";
import { isJsonValue, isRecord } from "@/utils/validation";
import type { JsonRecord } from "@/types/common";

interface MemoryFormValues {
  memory_type: MemoryType;
  title: string;
  content: string;
  summary?: string;
  source_type: MemorySourceType;
  source_id?: string;
  user_confirmed: boolean;
  importance?: number;
  subject_type?: string;
  subject_id?: string;
  predicate?: string;
  object_text?: string;
  expires_at?: string;
}

interface PreferenceFormValues {
  key: string;
  value_text: string;
  category?: string;
  description?: string;
  source_record_id: string;
  consent_statement: string;
  confirmed: boolean;
}

interface PreferenceEditFormValues {
  value_text: string;
  category?: string;
  description?: string;
  expires_at?: string;
}

interface CompressFormValues {
  title?: string;
  summary?: string;
  expires_in_days: number;
}

interface DistillFormValues {
  title?: string;
  summary?: string;
  subject_type: string;
  subject_id: string;
  predicate: string;
  object_text: string;
  expires_in_days: number;
}

const typeLabels: Record<MemoryType, string> = {
  episodic: "情节",
  semantic: "语义",
  procedural: "程序",
};

const statusOptions: Array<MemoryStatus | "current"> = [
  "current",
  "active",
  "candidate",
  "corrected",
  "superseded",
  "expired",
  "archived",
];

const questionOptions: Array<{ value: QuestionType; label: string }> = [
  { value: "preference", label: "用户偏好" },
  { value: "semantic_fact", label: "语义事实" },
  { value: "spatial_fact", label: "空间事实" },
  { value: "historical_event", label: "历史事件" },
  { value: "task_record", label: "任务记录" },
  { value: "procedure", label: "已验证程序" },
  { value: "any", label: "全部" },
];

function parseJsonObject(text: string): JsonRecord {
  const value = JSON.parse(text) as unknown;
  if (!isRecord(value) || !Object.values(value).every(isJsonValue)) {
    throw new Error("必须是 JSON 对象");
  }
  return value as JsonRecord;
}

function objectFromText(text: string | undefined): JsonRecord | undefined {
  if (text === undefined || text.trim().length === 0) {
    return undefined;
  }
  return parseJsonObject(text);
}

function isValidIsoDateTime(value: string | undefined): boolean {
  if (value === undefined || value.trim().length === 0) {
    return true;
  }
  return !Number.isNaN(new Date(value).getTime());
}

export default function MemoryPage() {
  const queryClient = useQueryClient();
  const [memoryPage, setMemoryPage] = useState(1);
  const [memoryPageSize, setMemoryPageSize] = useState(20);
  const [memoryType, setMemoryType] = useState<MemoryType | undefined>();
  const [memoryStatus, setMemoryStatus] = useState<MemoryStatus | "current">("current");
  const [memorySource, setMemorySource] = useState<MemorySourceType | undefined>();
  const [memoryKeyword, setMemoryKeyword] = useState("");
  const [includeExpired, setIncludeExpired] = useState(false);
  const [createMemoryOpen, setCreateMemoryOpen] = useState(false);
  const [selectedMemoryId, setSelectedMemoryId] = useState<string | undefined>();
  const [correctingMemory, setCorrectingMemory] = useState<MemoryItem | undefined>();
  const [selectedMemoryIds, setSelectedMemoryIds] = useState<string[]>([]);
  const [compressOpen, setCompressOpen] = useState(false);
  const [distillOpen, setDistillOpen] = useState(false);
  const [activeTab, setActiveTab] = useState("memories");
  const [graphType, setGraphType] = useState<MemoryType | undefined>();
  const [graphKeyword, setGraphKeyword] = useState("");

  const [preferencePage, setPreferencePage] = useState(1);
  const [preferencePageSize, setPreferencePageSize] = useState(20);
  const [preferenceStatus, setPreferenceStatus] = useState<
    "draft" | "active" | "revoked" | undefined
  >("active");
  const [preferenceKeyword, setPreferenceKeyword] = useState("");
  const [createPreferenceOpen, setCreatePreferenceOpen] = useState(false);
  const [editingPreference, setEditingPreference] = useState<PreferenceItem | undefined>();

  const [questionType, setQuestionType] = useState<QuestionType>("semantic_fact");
  const [retrievalQuery, setRetrievalQuery] = useState("");

  const [memoryForm] = Form.useForm<MemoryFormValues>();
  const [preferenceForm] = Form.useForm<PreferenceFormValues>();
  const [preferenceEditForm] = Form.useForm<PreferenceEditFormValues>();
  const [correctForm] = Form.useForm<{ content: string; reason?: string }>();
  const [compressForm] = Form.useForm<CompressFormValues>();
  const [distillForm] = Form.useForm<DistillFormValues>();

  const memoriesQuery = useQuery({
    queryKey: [
      "memories",
      {
        memoryPage,
        memoryPageSize,
        memoryType,
        memoryStatus,
        memorySource,
        memoryKeyword,
        includeExpired,
      },
    ],
    queryFn: () =>
      listMemories({
        page: memoryPage,
        page_size: memoryPageSize,
        memory_type: memoryType,
        status: memoryStatus,
        source_type: memorySource,
        keyword: memoryKeyword.trim().length > 0 ? memoryKeyword.trim() : undefined,
        include_expired: includeExpired,
      }),
    placeholderData: keepPreviousData,
  });

  const preferencesQuery = useQuery({
    queryKey: [
      "memory-preferences",
      { preferencePage, preferencePageSize, preferenceStatus, preferenceKeyword },
    ],
    queryFn: () =>
      listPreferences({
        page: preferencePage,
        page_size: preferencePageSize,
        status: preferenceStatus,
        keyword: preferenceKeyword.trim().length > 0 ? preferenceKeyword.trim() : undefined,
      }),
    placeholderData: keepPreviousData,
  });

  const memoryDetailQuery = useQuery({
    queryKey: ["memory", selectedMemoryId],
    queryFn: () => getMemory(selectedMemoryId as string),
    enabled: selectedMemoryId !== undefined,
  });
  const revisionsQuery = useQuery({
    queryKey: ["memory-revisions", selectedMemoryId],
    queryFn: () => memoryRevisions(selectedMemoryId as string),
    enabled: selectedMemoryId !== undefined,
  });
  const historyQuery = useQuery({
    queryKey: ["memory-history", selectedMemoryId],
    queryFn: () => memoryHistory(selectedMemoryId as string),
    enabled: selectedMemoryId !== undefined,
  });
  const graphQuery = useQuery({
    queryKey: ["memory-graph", graphType, graphKeyword],
    queryFn: () =>
      getMemoryGraph({
        memory_type: graphType,
        keyword: graphKeyword.trim().length > 0 ? graphKeyword.trim() : undefined,
      }),
    enabled: activeTab === "graph",
  });

  const retrieveMutation = useMutation({
    mutationFn: () =>
      retrieveMemory({
        question_type: questionType,
        query: retrievalQuery.trim().length > 0 ? retrievalQuery.trim() : undefined,
      }),
  });
  const cleanupMutation = useMutation({
    mutationFn: cleanupMemories,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["memories"] });
      void queryClient.invalidateQueries({ queryKey: ["memory-preferences"] });
    },
  });
  const compressMutation = useMutation({
    mutationFn: (values: CompressFormValues) =>
      compressMemories({
        memory_ids: selectedMemoryIds,
        title: values.title,
        summary: values.summary,
        expires_in_days: values.expires_in_days,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["memories"] });
      void queryClient.invalidateQueries({ queryKey: ["memory-graph"] });
      setCompressOpen(false);
      setSelectedMemoryIds([]);
      void compressForm.resetFields();
    },
  });
  const distillMutation = useMutation({
    mutationFn: (values: DistillFormValues) =>
      distillMemories({
        memory_ids: selectedMemoryIds,
        title: values.title,
        summary: values.summary,
        subject_type: values.subject_type,
        subject_id: values.subject_id,
        predicate: values.predicate,
        object_value: objectFromText(values.object_text),
        expires_in_days: values.expires_in_days,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["memories"] });
      void queryClient.invalidateQueries({ queryKey: ["memory-graph"] });
      setDistillOpen(false);
      setSelectedMemoryIds([]);
      void distillForm.resetFields();
    },
  });
  const createMemoryMutation = useMutation({
    mutationFn: createMemory,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["memories"] });
      setCreateMemoryOpen(false);
      void memoryForm.resetFields();
    },
  });
  const confirmMemoryMutation = useMutation({
    mutationFn: confirmMemory,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["memories"] });
      void queryClient.invalidateQueries({ queryKey: ["memory", selectedMemoryId] });
      void queryClient.invalidateQueries({ queryKey: ["memory-revisions", selectedMemoryId] });
    },
  });
  const correctMemoryMutation = useMutation({
    mutationFn: ({
      memoryId,
      content,
      reason,
    }: {
      memoryId: string;
      content: string;
      reason?: string;
    }) => correctMemory(memoryId, content, reason),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["memories"] });
      void queryClient.invalidateQueries({ queryKey: ["memory", selectedMemoryId] });
      void queryClient.invalidateQueries({ queryKey: ["memory-revisions", selectedMemoryId] });
      setCorrectingMemory(undefined);
      void correctForm.resetFields();
    },
  });
  const deleteMemoryMutation = useMutation({
    mutationFn: deleteMemory,
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["memories"] });
      if (selectedMemoryId === result.id) {
        setSelectedMemoryId(undefined);
      }
    },
  });

  const createPreferenceMutation = useMutation({
    mutationFn: createPreference,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["memory-preferences"] });
      setCreatePreferenceOpen(false);
      void preferenceForm.resetFields();
    },
  });
  const confirmPreferenceMutation = useMutation({
    mutationFn: confirmPreference,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["memory-preferences"] });
    },
  });
  const updatePreferenceMutation = useMutation({
    mutationFn: ({
      preferenceId,
      value,
      category,
      description,
      expiresAt,
    }: {
      preferenceId: string;
      value: JsonRecord;
      category?: string;
      description?: string;
      expiresAt?: string;
    }) =>
      updatePreference(preferenceId, {
        value,
        category,
        description,
        expires_at: expiresAt,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["memory-preferences"] });
      setEditingPreference(undefined);
      void preferenceEditForm.resetFields();
    },
  });
  const deletePreferenceMutation = useMutation({
    mutationFn: deletePreference,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["memory-preferences"] });
    },
  });

  const memoryColumns: ColumnsType<MemoryItem> = [
    {
      title: "记忆",
      dataIndex: "title",
      render: (value: string, memory) => (
        <div>
          <strong>{value}</strong>
          <div className="secondary-text">{memory.content}</div>
        </div>
      ),
    },
    {
      title: "类型",
      dataIndex: "memory_type",
      width: 90,
      render: (value: MemoryType) => <Tag>{typeLabels[value]}</Tag>,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 120,
      render: (value: MemoryStatus) => <StatusTag status={value} />,
    },
    {
      title: "来源",
      dataIndex: "source_type",
      width: 130,
      render: (value: MemorySourceType, memory) => (
        <Space direction="vertical" size={0}>
          <Tag color={value === "user" ? "green" : value === "ai_inference" ? "orange" : "blue"}>
            {value}
          </Tag>
          <span className="mono-text">{memory.source_id ?? "-"}</span>
        </Space>
      ),
    },
    {
      title: "确认",
      dataIndex: "user_confirmed",
      width: 80,
      render: (value: boolean) => (value ? <Tag color="green">已确认</Tag> : <Tag>未确认</Tag>),
    },
    {
      title: "有效期",
      dataIndex: "expires_at",
      width: 150,
      render: formatDateTime,
    },
    {
      title: "更新",
      dataIndex: "updated_at",
      width: 150,
      render: formatDateTime,
    },
    {
      title: "操作",
      key: "actions",
      width: 220,
      render: (_, memory) => (
        <Space wrap size={4}>
          <Button
            size="small"
            icon={<EyeOutlined />}
            onClick={() => setSelectedMemoryId(memory.id)}
          >
            详情
          </Button>
          {memory.source_type === "user" && !memory.user_confirmed ? (
            <Button
              size="small"
              loading={
                confirmMemoryMutation.isPending && confirmMemoryMutation.variables === memory.id
              }
              onClick={() => confirmMemoryMutation.mutate(memory.id)}
            >
              确认
            </Button>
          ) : null}
          {["active", "candidate", "corrected"].includes(memory.status) ? (
            <Button
              size="small"
              icon={<EditOutlined />}
              onClick={() => {
                setCorrectingMemory(memory);
                void correctForm.setFieldsValue({ content: memory.content });
              }}
            >
              纠正
            </Button>
          ) : null}
          <Popconfirm
            title="永久删除这条记忆？"
            onConfirm={() => deleteMemoryMutation.mutate(memory.id)}
            okButtonProps={{ danger: true }}
          >
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              loading={
                deleteMemoryMutation.isPending && deleteMemoryMutation.variables === memory.id
              }
            />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const preferenceColumns: ColumnsType<PreferenceItem> = [
    {
      title: "偏好",
      dataIndex: "key",
      render: (value: string, preference) => (
        <div>
          <strong>{value}</strong>
          <div className="secondary-text">
            {preference.description ?? formatJson(preference.value)}
          </div>
        </div>
      ),
    },
    { title: "分类", dataIndex: "category", width: 120 },
    {
      title: "状态",
      dataIndex: "status",
      width: 110,
      render: (value: PreferenceItem["status"], preference) => (
        <Space direction="vertical" size={0}>
          <StatusTag status={value} />
          <span className="secondary-text">{preference.confirmed ? "已授权" : "待确认"}</span>
        </Space>
      ),
    },
    {
      title: "来源",
      dataIndex: "source_record_id",
      width: 180,
      render: (value: string, preference) => (
        <span className="mono-text">
          {value}
          {preference.conversation_id ? ` / ${preference.conversation_id}` : ""}
        </span>
      ),
    },
    { title: "过期", dataIndex: "expires_at", width: 150, render: formatDateTime },
    { title: "更新", dataIndex: "updated_at", width: 150, render: formatDateTime },
    {
      title: "操作",
      key: "actions",
      width: 190,
      render: (_, preference) =>
        preference.status === "revoked" ? (
          <Popconfirm
            title="删除这条偏好及其访问记录？"
            onConfirm={() => deletePreferenceMutation.mutate(preference.id)}
            okButtonProps={{ danger: true }}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        ) : (
          <Space wrap size={4}>
            {!preference.confirmed ? (
              <Button
                size="small"
                loading={
                  confirmPreferenceMutation.isPending &&
                  confirmPreferenceMutation.variables === preference.id
                }
                onClick={() => confirmPreferenceMutation.mutate(preference.id)}
              >
                确认
              </Button>
            ) : null}
            <Button
              size="small"
              icon={<EditOutlined />}
              onClick={() => {
                setEditingPreference(preference);
                void preferenceEditForm.setFieldsValue({
                  value_text: JSON.stringify(preference.value, null, 2),
                  category: preference.category,
                  description: preference.description ?? undefined,
                });
              }}
            >
              编辑
            </Button>
            <Popconfirm
              title="永久删除这条偏好？"
              onConfirm={() => deletePreferenceMutation.mutate(preference.id)}
              okButtonProps={{ danger: true }}
            >
              <Button
                size="small"
                danger
                icon={<DeleteOutlined />}
                loading={
                  deletePreferenceMutation.isPending &&
                  deletePreferenceMutation.variables === preference.id
                }
              />
            </Popconfirm>
          </Space>
        ),
    },
  ];

  const selectedMemory = memoryDetailQuery.data;
  const graph: MemoryGraph | undefined = graphQuery.data;

  if (memoriesQuery.isPending || preferencesQuery.isPending) {
    return <PageLoading text="正在读取记忆..." />;
  }

  return (
    <section className="page-stack">
      <header className="page-header">
        <div>
          <h1>World Memory</h1>
          <p>管理长期记忆、用户授权偏好、来源追踪、纠正和生命周期。</p>
        </div>
        <Space wrap>
          <Button icon={<PlusOutlined />} onClick={() => setCreateMemoryOpen(true)}>
            新记忆
          </Button>
          <Button icon={<FormOutlined />} onClick={() => setCreatePreferenceOpen(true)}>
            新偏好
          </Button>
          <Button
            icon={<ReloadOutlined />}
            loading={memoriesQuery.isFetching || preferencesQuery.isFetching}
            onClick={() => {
              void memoriesQuery.refetch();
              void preferencesQuery.refetch();
            }}
          >
            刷新
          </Button>
          <Popconfirm
            title="立即清理过期和到达保留期的数据？"
            onConfirm={() => cleanupMutation.mutate()}
          >
            <Button danger loading={cleanupMutation.isPending}>
              清理
            </Button>
          </Popconfirm>
        </Space>
      </header>

      {memoriesQuery.isError ? (
        <ApiErrorAlert
          error={memoriesQuery.error}
          onRetry={() => void memoriesQuery.refetch()}
          retrying={memoriesQuery.isFetching}
        />
      ) : null}
      {cleanupMutation.isError ? <ApiErrorAlert error={cleanupMutation.error} /> : null}
      {createMemoryMutation.isError ? <ApiErrorAlert error={createMemoryMutation.error} /> : null}
      {confirmMemoryMutation.isError ? <ApiErrorAlert error={confirmMemoryMutation.error} /> : null}
      {correctMemoryMutation.isError ? <ApiErrorAlert error={correctMemoryMutation.error} /> : null}
      {deleteMemoryMutation.isError ? <ApiErrorAlert error={deleteMemoryMutation.error} /> : null}
      {compressMutation.isError ? <ApiErrorAlert error={compressMutation.error} /> : null}
      {distillMutation.isError ? <ApiErrorAlert error={distillMutation.error} /> : null}

      <Card title="记忆检索">
        <div className="memory-retrieval">
          <Select
            value={questionType}
            onChange={setQuestionType}
            options={questionOptions}
            className="memory-question-select"
          />
          <Input
            value={retrievalQuery}
            placeholder="按关键词检索已确认的长期知识"
            onChange={(event) => setRetrievalQuery(event.target.value)}
            onPressEnter={() => retrieveMutation.mutate()}
          />
          <Button
            type="primary"
            icon={<SearchOutlined />}
            loading={retrieveMutation.isPending}
            onClick={() => retrieveMutation.mutate()}
          >
            检索
          </Button>
        </div>
        {retrieveMutation.isError ? <ApiErrorAlert error={retrieveMutation.error} /> : null}
        {retrieveMutation.data ? (
          <div className="memory-retrieval-result">
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="记忆">
                {retrieveMutation.data.memories.length}
              </Descriptions.Item>
              <Descriptions.Item label="偏好">
                {retrieveMutation.data.preferences.length}
              </Descriptions.Item>
            </Descriptions>
            {retrieveMutation.data.source_references.length > 0 ? (
              <JsonBlock value={retrieveMutation.data.source_references} />
            ) : (
              <Empty description="本次检索没有可引用的历史来源" />
            )}
          </div>
        ) : null}
      </Card>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: "memories",
            label: "长期记忆",
            children: (
              <>
                <Card>
                  <Space className="filter-bar" wrap>
                    <Select
                      allowClear
                      placeholder="类型"
                      value={memoryType}
                      onChange={(value) => {
                        setMemoryPage(1);
                        setMemoryType(value);
                      }}
                      options={Object.entries(typeLabels).map(([value, label]) => ({
                        value,
                        label,
                      }))}
                      className="fixed-select"
                    />
                    <Select
                      placeholder="状态"
                      value={memoryStatus}
                      onChange={(value) => {
                        setMemoryPage(1);
                        setMemoryStatus(value);
                      }}
                      options={statusOptions.map((value) => ({
                        value,
                        label: value === "current" ? "当前" : value,
                      }))}
                      className="fixed-select"
                    />
                    <Select
                      allowClear
                      placeholder="来源"
                      value={memorySource}
                      onChange={(value) => {
                        setMemoryPage(1);
                        setMemorySource(value);
                      }}
                      options={memorySourceTypes.map((value) => ({
                        value,
                        label: value,
                      }))}
                      className="fixed-select"
                    />
                    <Input
                      allowClear
                      placeholder="关键词"
                      value={memoryKeyword}
                      onChange={(event) => setMemoryKeyword(event.target.value)}
                      onPressEnter={() => setMemoryPage(1)}
                    />
                    <Checkbox
                      checked={includeExpired}
                      onChange={(event) => {
                        setMemoryPage(1);
                        setIncludeExpired(event.target.checked);
                      }}
                    >
                      含过期
                    </Checkbox>
                  </Space>
                </Card>
                <Card
                  title={`记忆（${memoriesQuery.data?.total ?? 0}）`}
                  extra={
                    <Space wrap>
                      <Button
                        icon={<FormOutlined />}
                        disabled={selectedMemoryIds.length < 2}
                        onClick={() => {
                          void compressForm.setFieldsValue({ expires_in_days: 7 });
                          setCompressOpen(true);
                        }}
                      >
                        压缩候选
                      </Button>
                      <Button
                        icon={<PlusOutlined />}
                        disabled={selectedMemoryIds.length < 1}
                        onClick={() => {
                          void distillForm.setFieldsValue({ expires_in_days: 7 });
                          setDistillOpen(true);
                        }}
                      >
                        知识提炼
                      </Button>
                    </Space>
                  }
                >
                  <Table
                    rowKey="id"
                    rowSelection={{
                      selectedRowKeys: selectedMemoryIds,
                      onChange: (selectedRowKeys) =>
                        setSelectedMemoryIds(selectedRowKeys.map(String)),
                    }}
                    columns={memoryColumns}
                    dataSource={memoriesQuery.data?.data ?? []}
                    loading={memoriesQuery.isFetching}
                    size="small"
                    pagination={{
                      current: memoryPage,
                      pageSize: memoryPageSize,
                      total: memoriesQuery.data?.total ?? 0,
                      showSizeChanger: true,
                      onChange: (page, pageSize) => {
                        setMemoryPage(page);
                        setMemoryPageSize(pageSize);
                      },
                    }}
                    locale={{ emptyText: <Empty description="暂无长期记忆" /> }}
                  />
                </Card>
              </>
            ),
          },
          {
            key: "graph",
            label: "关系图",
            children: (
              <>
                {graphQuery.isError ? (
                  <ApiErrorAlert
                    error={graphQuery.error}
                    onRetry={() => void graphQuery.refetch()}
                    retrying={graphQuery.isFetching}
                  />
                ) : null}
                <Card>
                  <Space className="filter-bar" wrap>
                    <Select
                      allowClear
                      placeholder="记忆类型"
                      value={graphType}
                      onChange={setGraphType}
                      options={Object.entries(typeLabels).map(([value, label]) => ({
                        value,
                        label,
                      }))}
                      className="fixed-select"
                    />
                    <Input
                      allowClear
                      placeholder="节点关键词"
                      value={graphKeyword}
                      onChange={(event) => setGraphKeyword(event.target.value)}
                      onPressEnter={() => void graphQuery.refetch()}
                    />
                    <Button icon={<ReloadOutlined />} onClick={() => void graphQuery.refetch()}>
                      刷新
                    </Button>
                  </Space>
                </Card>
                <Card
                  title={graph ? `关系投影（${graph.nodes.length}）` : "关系投影"}
                  extra={graph?.truncated ? <Tag color="orange">已截断</Tag> : null}
                >
                  {graphQuery.isPending ? (
                    <PageLoading text="正在读取关系投影..." />
                  ) : graph ? (
                    <>
                      <Descriptions size="small" column={3} bordered className="margin-bottom">
                        <Descriptions.Item label="节点">{graph.nodes.length}</Descriptions.Item>
                        <Descriptions.Item label="关系">{graph.edges.length}</Descriptions.Item>
                        <Descriptions.Item label="生成时间">
                          {formatDateTime(graph.generated_at)}
                        </Descriptions.Item>
                      </Descriptions>
                      <Table
                        rowKey="id"
                        size="small"
                        pagination={{ pageSize: 10, showSizeChanger: false }}
                        dataSource={graph.nodes}
                        columns={[
                          { title: "ID", dataIndex: "id", width: 280, ellipsis: true },
                          { title: "类型", dataIndex: "node_type", width: 110 },
                          { title: "标签", dataIndex: "label", ellipsis: true },
                          { title: "状态", dataIndex: "status", width: 120 },
                        ]}
                        locale={{ emptyText: <Empty description="暂无关系节点" /> }}
                      />
                      <div className="margin-top">
                        <JsonBlock value={graph.edges} />
                      </div>
                    </>
                  ) : null}
                </Card>
              </>
            ),
          },
          {
            key: "preferences",
            label: "用户偏好",
            children: (
              <>
                {preferencesQuery.isError ? (
                  <ApiErrorAlert
                    error={preferencesQuery.error}
                    onRetry={() => void preferencesQuery.refetch()}
                    retrying={preferencesQuery.isFetching}
                  />
                ) : null}
                {confirmPreferenceMutation.isError ? (
                  <ApiErrorAlert error={confirmPreferenceMutation.error} />
                ) : null}
                {updatePreferenceMutation.isError ? (
                  <ApiErrorAlert error={updatePreferenceMutation.error} />
                ) : null}
                {deletePreferenceMutation.isError ? (
                  <ApiErrorAlert error={deletePreferenceMutation.error} />
                ) : null}
                <Card>
                  <Space className="filter-bar" wrap>
                    <Select
                      allowClear
                      placeholder="状态"
                      value={preferenceStatus}
                      onChange={(value) => {
                        setPreferencePage(1);
                        setPreferenceStatus(value);
                      }}
                      options={[
                        { value: "draft", label: "草稿" },
                        { value: "active", label: "启用" },
                        { value: "revoked", label: "已撤销" },
                      ]}
                      className="fixed-select"
                    />
                    <Input
                      allowClear
                      placeholder="键或描述"
                      value={preferenceKeyword}
                      onChange={(event) => setPreferenceKeyword(event.target.value)}
                      onPressEnter={() => setPreferencePage(1)}
                    />
                  </Space>
                </Card>
                <Card title={`偏好（${preferencesQuery.data?.total ?? 0}）`}>
                  <Table
                    rowKey="id"
                    columns={preferenceColumns}
                    dataSource={preferencesQuery.data?.data ?? []}
                    loading={preferencesQuery.isFetching}
                    size="small"
                    pagination={{
                      current: preferencePage,
                      pageSize: preferencePageSize,
                      total: preferencesQuery.data?.total ?? 0,
                      showSizeChanger: true,
                      onChange: (page, pageSize) => {
                        setPreferencePage(page);
                        setPreferencePageSize(pageSize);
                      },
                    }}
                    locale={{ emptyText: <Empty description="暂无授权偏好" /> }}
                  />
                </Card>
              </>
            ),
          },
        ]}
      />

      <Modal
        title="创建长期记忆"
        open={createMemoryOpen}
        onCancel={() => setCreateMemoryOpen(false)}
        onOk={() => void memoryForm.submit()}
        confirmLoading={createMemoryMutation.isPending}
        destroyOnClose
      >
        <Form
          form={memoryForm}
          layout="vertical"
          initialValues={{
            memory_type: "semantic",
            source_type: "user",
            importance: 2,
            user_confirmed: false,
          }}
          onFinish={handleSubmitMemory}
        >
          <Form.Item name="memory_type" label="类型" rules={[{ required: true }]}>
            <Select
              options={[
                { value: "episodic", label: "情节记忆" },
                { value: "semantic", label: "语义记忆" },
                { value: "procedural", label: "程序记忆候选" },
              ]}
            />
          </Form.Item>
          <Form.Item name="title" label="标题" rules={[{ required: true, message: "请输入标题" }]}>
            <Input />
          </Form.Item>
          <Form.Item
            name="content"
            label="内容"
            rules={[{ required: true, message: "请输入内容" }]}
          >
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="source_type" label="来源类型" rules={[{ required: true }]}>
            <Select options={memorySourceTypes.map((value) => ({ value, label: value }))} />
          </Form.Item>
          <Form.Item name="source_id" label="来源记录 ID">
            <Input />
          </Form.Item>
          <Form.Item
            name="user_confirmed"
            label="用户已明确确认"
            valuePropName="checked"
            extra="AI 推断只能保存为待确认候选。"
          >
            <Switch />
          </Form.Item>
          <Form.Item name="importance" label="重要性">
            <InputNumber min={1} max={5} precision={0} className="number-input" />
          </Form.Item>
          <Form.Item name="subject_type" label="主体类型（语义/程序）">
            <Input />
          </Form.Item>
          <Form.Item name="subject_id" label="主体 ID">
            <Input />
          </Form.Item>
          <Form.Item name="predicate" label="谓词">
            <Input />
          </Form.Item>
          <Form.Item
            name="object_text"
            label="对象 JSON"
            rules={[{ validator: (_, value: string | undefined) => isValidJson(value) }]}
          >
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item
            name="expires_at"
            label="过期时间 ISO"
            rules={[{ validator: (_, value: string | undefined) => isValidDateTime(value) }]}
          >
            <Input />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="创建用户偏好"
        open={createPreferenceOpen}
        onCancel={() => setCreatePreferenceOpen(false)}
        onOk={() => void preferenceForm.submit()}
        confirmLoading={createPreferenceMutation.isPending}
        destroyOnClose
      >
        <Form
          form={preferenceForm}
          layout="vertical"
          initialValues={{ confirmed: false, category: "general" }}
          onFinish={handleSubmitPreference}
        >
          <Form.Item name="key" label="键" rules={[{ required: true, message: "请输入键" }]}>
            <Input />
          </Form.Item>
          <Form.Item
            name="value_text"
            label="值 JSON"
            rules={[
              { required: true, message: "请输入 JSON 对象" },
              { validator: (_, value: string) => isValidJsonObject(value) },
            ]}
          >
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="category" label="分类">
            <Input />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item
            name="source_record_id"
            label="来源记录 ID"
            rules={[{ required: true, message: "用户偏好必须有来源" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="consent_statement"
            label="授权说明"
            rules={[{ required: true, message: "请输入用户授权说明" }]}
          >
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="confirmed" label="立即保存为启用偏好" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="编辑用户偏好"
        open={editingPreference !== undefined}
        onCancel={() => setEditingPreference(undefined)}
        onOk={() => void preferenceEditForm.submit()}
        confirmLoading={updatePreferenceMutation.isPending}
        destroyOnClose
      >
        <Form form={preferenceEditForm} layout="vertical" onFinish={handleSubmitPreferenceEdit}>
          <Form.Item
            name="value_text"
            label="值 JSON"
            rules={[
              { required: true, message: "请输入 JSON 对象" },
              { validator: (_, value: string) => isValidJsonObject(value) },
            ]}
          >
            <Input.TextArea rows={4} />
          </Form.Item>
          <Form.Item name="category" label="分类">
            <Input />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item
            name="expires_at"
            label="过期时间 ISO"
            rules={[{ validator: (_, value: string | undefined) => isValidDateTime(value) }]}
          >
            <Input />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="纠正记忆"
        open={correctingMemory !== undefined}
        onCancel={() => setCorrectingMemory(undefined)}
        onOk={() => void correctForm.submit()}
        confirmLoading={correctMemoryMutation.isPending}
        destroyOnClose
      >
        <Form form={correctForm} layout="vertical" onFinish={handleSubmitCorrection}>
          <Form.Item
            name="content"
            label="纠正后的内容"
            rules={[{ required: true, message: "请输入内容" }]}
          >
            <Input.TextArea rows={4} />
          </Form.Item>
          <Form.Item name="reason" label="纠正原因">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="压缩情节记忆"
        open={compressOpen}
        onCancel={() => setCompressOpen(false)}
        onOk={() => void compressForm.submit()}
        confirmLoading={compressMutation.isPending}
        destroyOnClose
      >
        <Alert
          className="margin-bottom"
          type="info"
          showIcon
          message={`已选择 ${selectedMemoryIds.length} 条来源；候选不会删除或覆盖源记忆。`}
        />
        <Form form={compressForm} layout="vertical" onFinish={handleSubmitCompression}>
          <Form.Item name="title" label="候选标题">
            <Input />
          </Form.Item>
          <Form.Item name="summary" label="候选摘要">
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item
            name="expires_in_days"
            label="有效期（天）"
            rules={[{ required: true, message: "请输入有效期" }]}
          >
            <InputNumber min={1} max={365} precision={0} className="number-input" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="提炼语义知识候选"
        open={distillOpen}
        onCancel={() => setDistillOpen(false)}
        onOk={() => void distillForm.submit()}
        confirmLoading={distillMutation.isPending}
        destroyOnClose
      >
        <Alert
          className="margin-bottom"
          type="warning"
          showIcon
          message="提炼只能来自已确认且已验证的情节记忆；结果保持待审核候选。"
        />
        <Form form={distillForm} layout="vertical" onFinish={handleSubmitDistillation}>
          <Form.Item name="title" label="候选标题">
            <Input />
          </Form.Item>
          <Form.Item
            name="subject_type"
            label="主体类型"
            rules={[{ required: true, message: "请输入主体类型" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="subject_id"
            label="主体 ID"
            rules={[{ required: true, message: "请输入主体 ID" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="predicate"
            label="谓词"
            rules={[{ required: true, message: "请输入谓词" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="object_text"
            label="对象 JSON"
            rules={[
              { required: true, message: "请输入对象 JSON" },
              { validator: (_, value: string | undefined) => isValidJson(value) },
            ]}
          >
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name="summary" label="候选摘要">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item
            name="expires_in_days"
            label="有效期（天）"
            rules={[{ required: true, message: "请输入有效期" }]}
          >
            <InputNumber min={1} max={365} precision={0} className="number-input" />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title={selectedMemory?.title ?? "记忆详情"}
        width={720}
        open={selectedMemoryId !== undefined}
        onClose={() => setSelectedMemoryId(undefined)}
        destroyOnClose
      >
        {memoryDetailQuery.isPending ? (
          <PageLoading text="正在读取详情..." />
        ) : memoryDetailQuery.isError ? (
          <ApiErrorAlert
            error={memoryDetailQuery.error}
            onRetry={() => void memoryDetailQuery.refetch()}
          />
        ) : selectedMemory ? (
          <div className="memory-detail">
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="类型">{selectedMemory.memory_type}</Descriptions.Item>
              <Descriptions.Item label="状态">{selectedMemory.status}</Descriptions.Item>
              <Descriptions.Item label="来源">
                {selectedMemory.source_type}
                {selectedMemory.source_id ? ` / ${selectedMemory.source_id}` : ""}
              </Descriptions.Item>
              <Descriptions.Item label="确认">
                {selectedMemory.user_confirmed ? "是" : "否"}
              </Descriptions.Item>
              <Descriptions.Item label="验证">
                {selectedMemory.verification_status}
              </Descriptions.Item>
              <Descriptions.Item label="权限">
                {selectedMemory.owner_id} / {selectedMemory.access_level}
              </Descriptions.Item>
              <Descriptions.Item label="有效期">
                {formatDateTime(selectedMemory.expires_at)}
              </Descriptions.Item>
            </Descriptions>
            <JsonBlock value={selectedMemory.object_value} />
            <Tabs
              items={[
                {
                  key: "revisions",
                  label: "修订",
                  children:
                    revisionsQuery.data && revisionsQuery.data.length > 0 ? (
                      <JsonBlock value={revisionsQuery.data} />
                    ) : (
                      <Empty description="暂无修订记录" />
                    ),
                },
                {
                  key: "history",
                  label: "来源历史",
                  children:
                    historyQuery.data && historyQuery.data.length > 0 ? (
                      <JsonBlock value={historyQuery.data} />
                    ) : (
                      <Empty description="暂无关联历史证据" />
                    ),
                },
              ]}
            />
          </div>
        ) : null}
      </Drawer>
    </section>
  );

  function isValidJson(value: string | undefined) {
    if (value === undefined || value.trim().length === 0) {
      return Promise.resolve();
    }
    try {
      JSON.parse(value);
      return Promise.resolve();
    } catch {
      return Promise.reject(new Error("请输入有效 JSON"));
    }
  }

  function isValidJsonObject(value: string | undefined) {
    if (value === undefined || value.trim().length === 0) {
      return Promise.reject(new Error("请输入 JSON 对象"));
    }
    try {
      parseJsonObject(value);
      return Promise.resolve();
    } catch {
      return Promise.reject(new Error("请输入 JSON 对象"));
    }
  }

  function isValidDateTime(value: string | undefined) {
    return isValidIsoDateTime(value)
      ? Promise.resolve()
      : Promise.reject(new Error("请输入有效 ISO 时间"));
  }

  function handleSubmitMemory(values: MemoryFormValues) {
    createMemoryMutation.mutate({
      memory_type: values.memory_type,
      title: values.title,
      content: values.content,
      summary: values.summary,
      source_type: values.source_type,
      source_id: values.source_id,
      user_confirmed: values.user_confirmed,
      importance: values.importance,
      subject_type: values.subject_type,
      subject_id: values.subject_id,
      predicate: values.predicate,
      object_value: objectFromText(values.object_text),
      expires_at: values.expires_at,
    });
  }

  function handleSubmitPreference(values: PreferenceFormValues) {
    createPreferenceMutation.mutate({
      key: values.key,
      value: parseJsonObject(values.value_text),
      category: values.category,
      description: values.description,
      source_record_id: values.source_record_id,
      consent_statement: values.consent_statement,
      confirmed: values.confirmed,
    });
  }

  function handleSubmitPreferenceEdit(values: PreferenceEditFormValues) {
    if (editingPreference === undefined) {
      return;
    }
    updatePreferenceMutation.mutate({
      preferenceId: editingPreference.id,
      value: parseJsonObject(values.value_text),
      category: values.category,
      description: values.description,
      expiresAt: values.expires_at,
    });
  }

  function handleSubmitCorrection(values: { content: string; reason?: string }) {
    if (correctingMemory === undefined) {
      return;
    }
    correctMemoryMutation.mutate({
      memoryId: correctingMemory.id,
      content: values.content,
      reason: values.reason,
    });
  }

  function handleSubmitCompression(values: CompressFormValues) {
    compressMutation.mutate(values);
  }

  function handleSubmitDistillation(values: DistillFormValues) {
    distillMutation.mutate(values);
  }
}

const memorySourceTypes = [
  "user",
  "observation",
  "event",
  "task",
  "conversation",
  "ai_inference",
  "procedure_execution",
  "system",
] as const satisfies readonly MemorySourceType[];
