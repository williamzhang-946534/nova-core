import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
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
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { ReloadOutlined, SearchOutlined } from "@ant-design/icons";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import PageLoading from "@/components/PageLoading";
import {
  askHistory,
  diffSnapshots,
  getCorrelatedHistory,
  getHistoryRange,
  getHistoryTrends,
  getSnapshotAt,
} from "@/api/history";
import type {
  CorrelatedHistory,
  EnvironmentSnapshot,
  HistoryQuery,
  HistoryQueryResult,
  HistoryRecord,
  NaturalHistoryAnswer,
  SnapshotDiffResult,
} from "@/types/history";
import { formatDateTime, formatJson } from "@/utils/format";

const qualityOptions = ["good", "estimated", "suspect", "bad"].map((value) => ({
  value,
  label: value,
}));

function toLocalInputValue(date: Date) {
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function fromLocalInputValue(value: string) {
  return new Date(`${value}:00`).toISOString();
}

function parseRangeForm(values: {
  startTime: string;
  endTime: string;
  timezone?: string;
  entityId?: string;
  spaceId?: string;
  attribute?: string;
  qualityStatus?: string;
  expectedIntervalSeconds?: number;
  limit?: number;
}): HistoryQuery {
  return {
    startTime: fromLocalInputValue(values.startTime),
    endTime: fromLocalInputValue(values.endTime),
    timezone: values.timezone || undefined,
    entityId: values.entityId || undefined,
    spaceId: values.spaceId || undefined,
    attribute: values.attribute || undefined,
    qualityStatus: values.qualityStatus || undefined,
    expectedIntervalSeconds: values.expectedIntervalSeconds,
    limit: values.limit,
  };
}

function HistoryResultPanel({ result }: { result: Omit<HistoryQueryResult, "counts"> }) {
  const columns: ColumnsType<HistoryRecord> = [
    { title: "类型", dataIndex: "record_type", width: 105 },
    { title: "业务时间", dataIndex: "occurred_at", render: formatDateTime, width: 165 },
    { title: "接收时间", dataIndex: "received_at", render: formatDateTime, width: 165 },
    { title: "属性", dataIndex: "attribute", render: (value?: string | null) => value ?? "-" },
    {
      title: "值",
      dataIndex: "value",
      render: (value, record) => `${String(value ?? "-")}${record.unit ? ` ${record.unit}` : ""}`,
    },
    { title: "实体", dataIndex: "entity_id", render: (value?: string | null) => value ?? "-" },
    { title: "空间", dataIndex: "space_id", render: (value?: string | null) => value ?? "-" },
    {
      title: "质量",
      dataIndex: "quality_status",
      render: (value?: string | null) => (value ? <Tag>{value}</Tag> : "-"),
    },
    { title: "来源", dataIndex: "source", render: (value?: string | null) => value ?? "-" },
  ];

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Descriptions
        size="small"
        bordered
        column={{ xs: 1, md: 3 }}
        items={[
          { key: "count", label: "记录数", children: result.records.length },
          {
            key: "range",
            label: "本地范围",
            children: `${result.range.local_start_time} 至 ${result.range.local_end_time}`,
          },
          { key: "basis", label: "时间基准", children: result.time_semantics.query_time_basis },
        ]}
      />
      {result.warnings.length > 0 ? (
        <Alert
          type="warning"
          showIcon
          message="时间语义警告"
          description={result.warnings.join("；")}
        />
      ) : null}
      {result.missing_ranges.length > 0 ? (
        <Alert
          type="info"
          showIcon
          message={`${result.missing_ranges.length} 个缺失区间`}
          description={result.missing_ranges
            .map(
              (gap) =>
                `${formatDateTime(gap.start_time)} 至 ${formatDateTime(gap.end_time)}：${gap.reason}`,
            )
            .join("；")}
        />
      ) : null}
      <Table
        rowKey={(record) => `${record.record_type}:${record.record_id}`}
        columns={columns}
        dataSource={result.records}
        scroll={{ x: 1250 }}
        size="small"
        pagination={{ pageSize: 20, showSizeChanger: false }}
        locale={{ emptyText: <Empty description="没有匹配的历史记录" /> }}
      />
    </Space>
  );
}

export default function HistoryPage() {
  const [rangeForm] = Form.useForm();
  const [trendForm] = Form.useForm();
  const [snapshotForm] = Form.useForm();
  const [correlationForm] = Form.useForm();
  const [askForm] = Form.useForm();

  const initialRange = useMemo<HistoryQuery>(() => {
    const end = new Date();
    const start = new Date(end.getTime() - 24 * 60 * 60 * 1000);
    return { startTime: start.toISOString(), endTime: end.toISOString(), limit: 500 };
  }, []);
  const [rangeQuery, setRangeQuery] = useState(initialRange);
  const [trendQuery, setTrendQuery] = useState<{
    startTime: string;
    endTime: string;
    attribute: string;
    groupBy: "space" | "entity";
    limit?: number;
  }>({
    startTime: initialRange.startTime,
    endTime: initialRange.endTime,
    attribute: "temperature",
    groupBy: "space",
    limit: 1000,
  });
  const [snapshotQuery, setSnapshotQuery] = useState({
    atTime: new Date().toISOString(),
    environmentId: undefined as string | undefined,
    nearest: false,
  });
  const [diffIds, setDiffIds] = useState({ baselineId: "", targetId: "" });
  const [correlation, setCorrelation] = useState<{
    recordType: "observation" | "event" | "task";
    recordId: string;
  }>({ recordType: "observation", recordId: "" });
  const [askText, setAskText] = useState("");

  const rangeResult = useQuery({
    queryKey: ["history", "range", rangeQuery],
    queryFn: () => getHistoryRange(rangeQuery),
  });
  const trendResult = useQuery({
    queryKey: ["history", "trend", trendQuery],
    queryFn: () => getHistoryTrends(trendQuery),
  });
  const snapshotResult = useQuery({
    queryKey: ["history", "snapshot", snapshotQuery],
    queryFn: () =>
      getSnapshotAt(snapshotQuery.atTime, snapshotQuery.environmentId, snapshotQuery.nearest),
  });
  const diffResult = useQuery({
    queryKey: ["history", "snapshot-diff", diffIds],
    queryFn: () => diffSnapshots(diffIds.baselineId, diffIds.targetId),
    enabled: diffIds.baselineId.length > 0 && diffIds.targetId.length > 0,
  });
  const correlatedResult = useQuery({
    queryKey: ["history", "correlation", correlation],
    queryFn: () => getCorrelatedHistory(correlation.recordType, correlation.recordId),
    enabled: correlation.recordId.trim().length > 0,
  });
  const askResult = useQuery({
    queryKey: ["history", "ask", askText],
    queryFn: () => askHistory(askText),
    enabled: askText.trim().length > 0,
  });

  if (rangeResult.isPending) {
    return <PageLoading text="正在读取历史能力..." />;
  }

  function renderSnapshot(snapshot: EnvironmentSnapshot | null | undefined) {
    if (!snapshot) {
      return <Empty description="没有符合条件的快照" />;
    }
    return (
      <Descriptions
        size="small"
        bordered
        column={{ xs: 1, md: 2 }}
        items={[
          { key: "id", label: "快照 ID", children: snapshot.id },
          { key: "env", label: "环境", children: snapshot.environment_id },
          { key: "created", label: "创建时间", children: formatDateTime(snapshot.created_at) },
          { key: "local", label: "本地时间", children: snapshot.local_created_at },
          { key: "version", label: "上下文版本", children: snapshot.context_version },
          { key: "tasks", label: "活动任务", children: snapshot.active_task_ids.length },
        ]}
      />
    );
  }

  function renderDiff(result: SnapshotDiffResult) {
    return (
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        <Typography.Text>
          {result.changes.length} 处变化，{result.unchanged_count} 项未变化。
        </Typography.Text>
        <Table
          rowKey="path"
          size="small"
          pagination={false}
          dataSource={result.changes}
          columns={[
            { title: "路径", dataIndex: "path" },
            {
              title: "变化",
              dataIndex: "change_type",
              render: (value: string) => (
                <Tag color={value === "added" ? "green" : value === "removed" ? "red" : "gold"}>
                  {value}
                </Tag>
              ),
            },
            {
              title: "前值",
              dataIndex: "before",
              render: (value?: unknown) => formatJson(value ?? null),
            },
            {
              title: "后值",
              dataIndex: "after",
              render: (value?: unknown) => formatJson(value ?? null),
            },
            { title: "恢复性", dataIndex: "recoverability" },
            { title: "说明", dataIndex: "explanation" },
          ]}
        />
      </Space>
    );
  }

  function renderCorrelation(result: CorrelatedHistory) {
    return (
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        <Descriptions
          size="small"
          bordered
          column={1}
          items={[
            { key: "record", label: "记录", children: formatJson(result.record) },
            { key: "basis", label: "关联依据", children: formatJson(result.relation_basis) },
          ]}
        />
        <Descriptions
          size="small"
          column={3}
          items={[
            { key: "events", label: "事件", children: result.events.length },
            { key: "tasks", label: "任务", children: result.tasks.length },
            { key: "observations", label: "观测", children: result.observations.length },
          ]}
        />
        {result.snapshots.length > 0 ? renderSnapshot(result.snapshots[0]) : null}
        {result.warnings.length > 0 ? (
          <Alert type="warning" message={result.warnings.join("；")} />
        ) : null}
      </Space>
    );
  }

  function renderAsk(result: NaturalHistoryAnswer) {
    return (
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        <Alert
          type={result.answer.startsWith("无法") ? "warning" : "success"}
          message={result.answer}
          description={`${result.based_on_record_count} 条记录；置信度 ${Math.round(result.interpretation.confidence * 100)}%；${result.interpretation.explanation}`}
        />
        <HistoryResultPanel result={result} />
      </Space>
    );
  }

  return (
    <section className="page-stack">
      <header className="page-header">
        <div>
          <h1>历史</h1>
          <p>按时间语义查询观测、事件、任务、快照、趋势和关联记录。</p>
        </div>
        <Button
          icon={<ReloadOutlined />}
          loading={rangeResult.isFetching}
          onClick={() => void rangeResult.refetch()}
        >
          刷新
        </Button>
      </header>

      {rangeResult.isError ? <ApiErrorAlert error={rangeResult.error} /> : null}
      {trendResult.isError ? <ApiErrorAlert error={trendResult.error} /> : null}
      {snapshotResult.isError ? <ApiErrorAlert error={snapshotResult.error} /> : null}
      {diffResult.isError ? <ApiErrorAlert error={diffResult.error} /> : null}
      {correlatedResult.isError ? <ApiErrorAlert error={correlatedResult.error} /> : null}
      {askResult.isError ? <ApiErrorAlert error={askResult.error} /> : null}

      <Card title="时间范围查询">
        <Form
          form={rangeForm}
          layout="vertical"
          initialValues={{
            startTime: toLocalInputValue(new Date(Date.now() - 24 * 60 * 60 * 1000)),
            endTime: toLocalInputValue(new Date()),
            limit: 500,
          }}
          onFinish={(values) => setRangeQuery(parseRangeForm(values))}
        >
          <Space wrap size={12} align="end">
            <Form.Item name="startTime" label="开始时间" rules={[{ required: true }]}>
              <Input type="datetime-local" />
            </Form.Item>
            <Form.Item name="endTime" label="结束时间" rules={[{ required: true }]}>
              <Input type="datetime-local" />
            </Form.Item>
            <Form.Item name="attribute" label="属性">
              <Input placeholder="temperature" allowClear />
            </Form.Item>
            <Form.Item name="entityId" label="实体 ID">
              <Input allowClear />
            </Form.Item>
            <Form.Item name="spaceId" label="空间 ID">
              <Input allowClear />
            </Form.Item>
            <Form.Item name="qualityStatus" label="质量">
              <Select options={qualityOptions} allowClear className="fixed-select" />
            </Form.Item>
            <Form.Item name="expectedIntervalSeconds" label="期望间隔（秒）">
              <InputNumber min={1} />
            </Form.Item>
            <Form.Item name="limit" label="上限">
              <InputNumber min={1} max={2000} />
            </Form.Item>
            <Form.Item>
              <Button type="primary" htmlType="submit" icon={<SearchOutlined />}>
                查询
              </Button>
            </Form.Item>
          </Space>
        </Form>
        {rangeResult.data ? <HistoryResultPanel result={rangeResult.data} /> : null}
      </Card>

      <Card title="趋势统计">
        <Form
          form={trendForm}
          layout="vertical"
          initialValues={trendQuery}
          onFinish={(values) =>
            setTrendQuery({
              startTime: fromLocalInputValue(values.startTime),
              endTime: fromLocalInputValue(values.endTime),
              attribute: values.attribute,
              groupBy: values.groupBy,
              limit: values.limit,
            })
          }
        >
          <Space wrap size={12} align="end">
            <Form.Item name="startTime" label="开始时间" rules={[{ required: true }]}>
              <Input type="datetime-local" />
            </Form.Item>
            <Form.Item name="endTime" label="结束时间" rules={[{ required: true }]}>
              <Input type="datetime-local" />
            </Form.Item>
            <Form.Item name="attribute" label="属性" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="groupBy" label="分组">
              <Select
                options={[
                  { value: "space", label: "空间" },
                  { value: "entity", label: "实体" },
                ]}
                className="fixed-select"
              />
            </Form.Item>
            <Form.Item name="limit" label="上限">
              <InputNumber min={1} max={5000} />
            </Form.Item>
            <Form.Item>
              <Button type="primary" htmlType="submit" icon={<SearchOutlined />}>
                分析
              </Button>
            </Form.Item>
          </Space>
        </Form>
        {trendResult.data ? (
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Table
              rowKey={(record) => `${record.group_key}:${record.attribute}`}
              size="small"
              pagination={false}
              dataSource={trendResult.data.statistics}
              columns={[
                { title: "分组", dataIndex: "label" },
                { title: "属性", dataIndex: "attribute" },
                { title: "观测", dataIndex: "observation_count" },
                { title: "有效", dataIndex: "valid_count" },
                { title: "数值", dataIndex: "numeric_count" },
                { title: "最小", dataIndex: "minimum" },
                { title: "最大", dataIndex: "maximum" },
                { title: "平均", dataIndex: "average" },
                { title: "变化", dataIndex: "change" },
              ]}
              locale={{ emptyText: <Empty description="没有趋势数据" /> }}
            />
            {trendResult.data.warnings.length > 0 ? (
              <Alert type="warning" message={trendResult.data.warnings.join("；")} />
            ) : null}
          </Space>
        ) : null}
      </Card>

      <div className="two-column">
        <Card title="快照回放">
          <Form
            form={snapshotForm}
            layout="vertical"
            onFinish={(values) =>
              setSnapshotQuery({
                atTime: new Date(`${values.atTime}:00`).toISOString(),
                environmentId: values.environmentId || undefined,
                nearest: values.nearest === true,
              })
            }
          >
            <Space wrap size={12} align="end">
              <Form.Item name="atTime" label="时间点" initialValue={toLocalInputValue(new Date())}>
                <Input type="datetime-local" />
              </Form.Item>
              <Form.Item name="environmentId" label="环境 ID">
                <Input allowClear />
              </Form.Item>
              <Form.Item name="nearest" label="最近匹配" valuePropName="checked">
                <Switch />
              </Form.Item>
              <Form.Item>
                <Button type="primary" htmlType="submit" icon={<SearchOutlined />}>
                  回放
                </Button>
              </Form.Item>
            </Space>
          </Form>
          {snapshotResult.data ? (
            <Space direction="vertical" size={12} style={{ width: "100%" }}>
              {renderSnapshot(snapshotResult.data.snapshot)}
              {snapshotResult.data.warning ? (
                <Alert type="warning" message={snapshotResult.data.warning} />
              ) : null}
              {snapshotResult.data.distance_seconds !== null &&
              snapshotResult.data.distance_seconds !== undefined ? (
                <Typography.Text>
                  距离请求时间 {snapshotResult.data.distance_seconds} 秒
                </Typography.Text>
              ) : null}
            </Space>
          ) : null}
        </Card>

        <Card title="快照差异">
          <Space.Compact block direction="vertical">
            <Input
              placeholder="基线快照 ID"
              value={diffIds.baselineId}
              onChange={(event) =>
                setDiffIds((old) => ({ ...old, baselineId: event.target.value.trim() }))
              }
            />
            <Input
              placeholder="目标快照 ID"
              value={diffIds.targetId}
              onChange={(event) =>
                setDiffIds((old) => ({ ...old, targetId: event.target.value.trim() }))
              }
            />
          </Space.Compact>
          {diffResult.data ? renderDiff(diffResult.data) : null}
        </Card>
      </div>

      <div className="two-column">
        <Card title="关联历史">
          <Form
            form={correlationForm}
            layout="vertical"
            onFinish={(values) => setCorrelation(values)}
          >
            <Space wrap size={12} align="end">
              <Form.Item name="recordType" label="记录类型" initialValue="observation">
                <Select
                  options={[
                    { value: "observation", label: "观测" },
                    { value: "event", label: "事件" },
                    { value: "task", label: "任务" },
                  ]}
                  className="fixed-select"
                />
              </Form.Item>
              <Form.Item name="recordId" label="记录 ID" rules={[{ required: true }]}>
                <Input style={{ minWidth: 240 }} />
              </Form.Item>
              <Form.Item>
                <Button type="primary" htmlType="submit" icon={<SearchOutlined />}>
                  查询
                </Button>
              </Form.Item>
            </Space>
          </Form>
          {correlatedResult.data ? renderCorrelation(correlatedResult.data) : null}
        </Card>

        <Card title="自然语言历史查询">
          <Form
            form={askForm}
            layout="vertical"
            onFinish={(values) => setAskText(values.query.trim())}
          >
            <Form.Item
              name="query"
              label="问题"
              rules={[{ required: true, message: "请输入历史问题" }]}
            >
              <Input.TextArea rows={3} placeholder="昨天客厅温度有什么变化？" />
            </Form.Item>
            <Button type="primary" htmlType="submit" icon={<SearchOutlined />}>
              提问
            </Button>
          </Form>
          {askResult.data ? renderAsk(askResult.data) : null}
        </Card>
      </div>
    </section>
  );
}
