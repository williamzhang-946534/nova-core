import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  Form,
  Input,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { ReloadOutlined } from "@ant-design/icons";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import PageLoading from "@/components/PageLoading";
import {
  getRobot,
  getRuntimeStatus,
  grantConsent,
  listCapabilities,
  listConsents,
  listRobotEvents,
  listRobotTaskRequests,
  listRobots,
  revokeConsent,
  setCapabilityGovernance,
} from "@/api/robots";
import type {
  RobotCapability,
  RobotCapabilityName,
  RobotConsent,
  RobotEvent,
  RobotTaskRequest,
} from "@/types/robots";
import { formatDateTime, formatJson } from "@/utils/format";

interface ConsentFormValues {
  capability: RobotCapabilityName;
  data_category: RobotConsent["data_category"];
  space_id?: string;
  expiry: "24h" | "7d" | "never";
}

interface GovernanceVariables {
  capability: RobotCapabilityName;
  enabled: boolean;
}

const statusColor = (value: string) => {
  if (["online", "idle", "succeeded", "granted", "connected"].includes(value)) {
    return "green";
  }
  if (
    [
      "busy",
      "stale",
      "running",
      "awaiting_confirmation",
      "cancel_requested",
      "stopping",
      "execution_state_unknown",
    ].includes(value)
  ) {
    return "gold";
  }
  if (
    ["error", "offline", "failed", "revoked", "expired", "timeout", "cancel_failed"].includes(value)
  ) {
    return "red";
  }
  if (["emergency_stopped", "critical", "unavailable"].includes(value)) {
    return "volcano";
  }
  return "default";
};

const StatusTag = ({ value }: { value: string }) => (
  <Tag color={statusColor(value)}>{value.replace(/_/g, " ")}</Tag>
);

export default function RobotManagementPage() {
  const queryClient = useQueryClient();
  const [selectedRobotId, setSelectedRobotId] = useState<string>();
  const [consentForm] = Form.useForm<ConsentFormValues>();
  const selectedConsentCapability = Form.useWatch("capability", consentForm);

  const robotsQuery = useQuery({
    queryKey: ["robots"],
    queryFn: () => listRobots(),
  });
  const robotId = selectedRobotId ?? robotsQuery.data?.[0]?.id;

  const robotQuery = useQuery({
    queryKey: ["robot", robotId],
    queryFn: () => getRobot(robotId ?? ""),
    enabled: Boolean(robotId),
  });
  const runtimeQuery = useQuery({
    queryKey: ["robot-runtime", robotId],
    queryFn: () => getRuntimeStatus(robotId ?? ""),
    enabled: Boolean(robotId),
  });
  const capabilitiesQuery = useQuery({
    queryKey: ["robot-capabilities", robotId],
    queryFn: () => listCapabilities(robotId ?? ""),
    enabled: Boolean(robotId),
  });
  const consentsQuery = useQuery({
    queryKey: ["robot-consents", robotId],
    queryFn: () => listConsents(robotId ?? ""),
    enabled: Boolean(robotId),
  });
  const taskRequestsQuery = useQuery({
    queryKey: ["robot-task-requests", robotId],
    queryFn: () => listRobotTaskRequests(robotId ?? ""),
    enabled: Boolean(robotId),
  });
  const eventsQuery = useQuery({
    queryKey: ["robot-events", robotId],
    queryFn: () => listRobotEvents(robotId ?? ""),
    enabled: Boolean(robotId),
  });

  const governanceMutation = useMutation({
    mutationFn: ({ capability, enabled }: GovernanceVariables) => {
      return setCapabilityGovernance(robotId ?? "", capability, enabled);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["robot-capabilities", robotId] });
      void queryClient.invalidateQueries({ queryKey: ["robot", robotId] });
    },
  });

  const grantMutation = useMutation({
    mutationFn: (values: ConsentFormValues) => {
      const expiresAt =
        values.expiry === "never"
          ? undefined
          : new Date(
              Date.now() + (values.expiry === "24h" ? 24 : 24 * 7) * 60 * 60 * 1000,
            ).toISOString();
      return grantConsent(robotId ?? "", {
        capability: values.capability,
        data_category: values.data_category,
        space_id: values.space_id?.trim() || undefined,
        expires_at: expiresAt,
        grant_source: "web-console",
        granted_by: "web-console-user",
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["robot-consents", robotId] });
      void queryClient.invalidateQueries({ queryKey: ["robot-capabilities", robotId] });
      consentForm.resetFields();
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (consentId: string) => revokeConsent(robotId ?? "", consentId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["robot-consents", robotId] });
      void queryClient.invalidateQueries({ queryKey: ["robot-capabilities", robotId] });
    },
  });

  if (robotsQuery.isPending) {
    return <PageLoading text="正在读取机器人..." />;
  }

  const robot = robotQuery.data;
  const runtime = runtimeQuery.data;
  const supportedCapabilities = capabilitiesQuery.data ?? [];
  const consentableCapabilities = supportedCapabilities.filter(
    (capability) => capability.supported && capability.requires_consents.length > 0,
  );
  const consentCategoriesByCapability = new Map(
    consentableCapabilities.map((capability) => [
      capability.capability,
      capability.requires_consents,
    ]),
  );
  const capabilityOptions = consentableCapabilities.map((capability) => ({
    value: capability.capability,
    label: capability.capability.replace(/_/g, " "),
  }));
  const selectedConsentCategories =
    selectedConsentCapability === undefined
      ? undefined
      : (consentCategoriesByCapability.get(selectedConsentCapability) ?? []);

  const capabilityColumns: ColumnsType<RobotCapability> = [
    {
      title: "能力",
      dataIndex: "capability",
      render: (value: RobotCapabilityName) => value.replace(/_/g, " "),
    },
    {
      title: "发现",
      dataIndex: "discovered",
      render: (value: boolean) => (value ? <Tag color="blue">discovered</Tag> : "-"),
      responsive: ["md"],
    },
    {
      title: "支持",
      dataIndex: "supported",
      render: (value: boolean) => (value ? <Tag color="green">supported</Tag> : <Tag>no</Tag>),
    },
    {
      title: "启用",
      dataIndex: "enabled",
      render: (value: boolean) => (value ? <Tag color="green">enabled</Tag> : <Tag>disabled</Tag>),
    },
    {
      title: "可执行",
      dataIndex: "executable",
      render: (value: boolean) =>
        value ? <Tag color="green">executable</Tag> : <Tag color="orange">blocked</Tag>,
    },
    {
      title: "风险",
      dataIndex: "risk_level",
      render: (value: string) => <StatusTag value={value} />,
      responsive: ["md"],
    },
    {
      title: "授权",
      dataIndex: "requires_consents",
      render: (value: RobotConsent["data_category"][]) =>
        value.length > 0 ? value.map((category) => <Tag key={category}>{category}</Tag>) : "-",
      responsive: ["md"],
    },
    {
      title: "启用状态",
      key: "governance",
      render: (_, capability) => (
        <Switch
          checked={capability.enabled}
          disabled={!capability.supported || governanceMutation.isPending}
          loading={
            governanceMutation.isPending &&
            governanceMutation.variables?.capability === capability.capability
          }
          onChange={(enabled) =>
            governanceMutation.mutate({ capability: capability.capability, enabled })
          }
        />
      ),
    },
  ];

  const consentColumns: ColumnsType<RobotConsent> = [
    {
      title: "能力",
      dataIndex: "capability",
      render: (value: RobotCapabilityName) => value.replace(/_/g, " "),
    },
    {
      title: "数据类别",
      dataIndex: "data_category",
      render: (value: string) => <Tag>{value}</Tag>,
    },
    {
      title: "空间",
      dataIndex: "space_id",
      render: (value: string | null) => <span className="mono-text">{value ?? "所有空间"}</span>,
      responsive: ["md"],
    },
    {
      title: "状态",
      dataIndex: "status",
      render: (value: RobotConsent["status"]) => <StatusTag value={value} />,
    },
    {
      title: "到期时间",
      dataIndex: "expires_at",
      render: formatDateTime,
      responsive: ["md"],
    },
    {
      title: "操作",
      key: "actions",
      render: (_, consent) =>
        consent.status === "granted" ? (
          <Popconfirm
            title="撤销这个授权？"
            onConfirm={() => revokeMutation.mutate(consent.id)}
            okButtonProps={{ danger: true }}
          >
            <Button
              size="small"
              danger
              loading={revokeMutation.isPending && revokeMutation.variables === consent.id}
            >
              撤销
            </Button>
          </Popconfirm>
        ) : (
          "-"
        ),
    },
  ];

  const taskColumns: ColumnsType<RobotTaskRequest> = [
    {
      title: "请求 ID",
      dataIndex: "id",
      render: (value: string) => <span className="mono-text">{value}</span>,
    },
    {
      title: "能力",
      dataIndex: "capability",
      render: (value: RobotCapabilityName) => value.replace(/_/g, " "),
    },
    { title: "状态", dataIndex: "status", render: (value: string) => <StatusTag value={value} /> },
    {
      title: "任务",
      dataIndex: "task_id",
      render: (value: string | null) => <span className="mono-text">{value ?? "-"}</span>,
      responsive: ["md"],
    },
    {
      title: "工具执行",
      dataIndex: "tool_execution_id",
      render: (value: string | null) => <span className="mono-text">{value ?? "-"}</span>,
      responsive: ["md"],
    },
    { title: "创建时间", dataIndex: "created_at", render: formatDateTime, responsive: ["md"] },
  ];

  const eventColumns: ColumnsType<RobotEvent> = [
    {
      title: "事件",
      dataIndex: "event_type",
      render: (value: string) => <StatusTag value={value} />,
    },
    {
      title: "级别",
      dataIndex: "severity",
      render: (value: RobotEvent["severity"]) => <StatusTag value={value} />,
    },
    {
      title: "关联请求",
      dataIndex: "task_request_id",
      render: (value: string | null) => <span className="mono-text">{value ?? "-"}</span>,
      responsive: ["md"],
    },
    { title: "发生时间", dataIndex: "occurred_at", render: formatDateTime },
    {
      title: "详情",
      dataIndex: "payload",
      render: (value: Record<string, unknown>) => (
        <span className="mono-text secondary-text">{formatJson(value)}</span>
      ),
      responsive: ["lg"],
    },
  ];

  return (
    <section className="page-stack">
      <header className="page-header">
        <div>
          <h1>机器人</h1>
          <p>桌面机器人状态、能力治理、授权和执行记录。</p>
        </div>
        <Space wrap>
          <Select
            value={robotId}
            onChange={setSelectedRobotId}
            loading={robotsQuery.isFetching}
            className="fixed-select"
            options={(robotsQuery.data ?? []).map((item) => ({
              value: item.id,
              label: item.name,
            }))}
          />
          <Button
            icon={<ReloadOutlined />}
            loading={robotsQuery.isFetching || robotQuery.isFetching}
            onClick={() => {
              void robotsQuery.refetch();
              void runtimeQuery.refetch();
              void capabilitiesQuery.refetch();
              void consentsQuery.refetch();
              void taskRequestsQuery.refetch();
              void eventsQuery.refetch();
            }}
          >
            刷新
          </Button>
        </Space>
      </header>

      {robotsQuery.isError ? (
        <ApiErrorAlert error={robotsQuery.error} onRetry={() => void robotsQuery.refetch()} />
      ) : null}
      {robotQuery.isError ? <ApiErrorAlert error={robotQuery.error} /> : null}
      {runtimeQuery.isError ? <ApiErrorAlert error={runtimeQuery.error} /> : null}
      {capabilitiesQuery.isError ? <ApiErrorAlert error={capabilitiesQuery.error} /> : null}
      {governanceMutation.isError ? <ApiErrorAlert error={governanceMutation.error} /> : null}
      {consentsQuery.isError ? <ApiErrorAlert error={consentsQuery.error} /> : null}
      {grantMutation.isError ? <ApiErrorAlert error={grantMutation.error} /> : null}
      {revokeMutation.isError ? <ApiErrorAlert error={revokeMutation.error} /> : null}

      {!robot ? (
        <Card>
          <Empty description="暂无注册机器人" />
        </Card>
      ) : (
        <>
          <Card title="运行状态">
            <Descriptions bordered size="small" column={{ xs: 1, md: 3 }}>
              <Descriptions.Item label="运行状态">
                {runtime ? <StatusTag value={runtime.state} /> : "-"}
              </Descriptions.Item>
              <Descriptions.Item label="连接">
                {runtime?.connection_state ?? robot.connection_state}
              </Descriptions.Item>
              <Descriptions.Item label="状态新鲜度">
                {runtime ? (
                  <Tag color={runtime.is_fresh ? "green" : "orange"}>
                    {runtime.is_fresh ? "fresh" : "stale"}
                  </Tag>
                ) : (
                  "-"
                )}
              </Descriptions.Item>
              <Descriptions.Item label="安全停止">
                <Tag color={robot.emergency_stop ? "volcano" : "green"}>
                  {robot.emergency_stop ? "emergency_stopped" : "normal"}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="运动安全">
                <StatusTag value={runtime?.motion_safety_state ?? robot.motion_safety_state} />
              </Descriptions.Item>
              <Descriptions.Item label="故障代码">
                <span className="mono-text">{runtime?.error_code ?? "-"}</span>
              </Descriptions.Item>
              <Descriptions.Item label="最后活动">
                {formatDateTime(runtime?.last_seen_at ?? robot.last_seen_at)}
              </Descriptions.Item>
              <Descriptions.Item label="活动任务">
                {runtime?.active_task_count ?? "-"}
              </Descriptions.Item>
              <Descriptions.Item label="电量">{robot.battery_percent ?? "-"}</Descriptions.Item>
            </Descriptions>
          </Card>

          {runtime?.error_code ? (
            <Alert type="error" showIcon message="机器人故障" description={runtime.error_code} />
          ) : null}
          {runtime?.state === "stale" ? (
            <Alert type="warning" showIcon message="机器人状态已过期" />
          ) : null}

          <Card title={`能力（${supportedCapabilities.length}）`}>
            <Table
              rowKey="capability"
              columns={capabilityColumns}
              dataSource={supportedCapabilities}
              loading={capabilitiesQuery.isFetching}
              size="small"
              pagination={false}
              locale={{ emptyText: <Empty description="暂无能力" /> }}
            />
          </Card>

          <Card title={`授权（${consentsQuery.data?.length ?? 0}）`}>
            <Form<ConsentFormValues>
              form={consentForm}
              layout="vertical"
              onFinish={(values) => grantMutation.mutate(values)}
              initialValues={{
                capability: "speak",
                data_category: "speaker",
                space_id: robot.space_id ?? undefined,
                expiry: "7d",
              }}
            >
              <Space className="filter-bar" wrap align="start">
                <Form.Item name="capability" label="能力" rules={[{ required: true }]}>
                  <Select
                    className="fixed-select"
                    options={capabilityOptions}
                    onChange={(value: RobotCapabilityName) => {
                      const categories = consentCategoriesByCapability.get(value) ?? [];
                      const currentCategory = consentForm.getFieldValue("data_category");
                      if (!categories.includes(currentCategory)) {
                        consentForm.setFieldValue("data_category", categories[0]);
                      }
                    }}
                  />
                </Form.Item>
                <Form.Item name="data_category" label="数据类别" rules={[{ required: true }]}>
                  <Select
                    className="fixed-select"
                    options={(selectedConsentCategories ?? []).map((category) => ({
                      value: category,
                      label: category,
                    }))}
                  />
                </Form.Item>
                <Form.Item name="space_id" label="空间 ID">
                  <Input
                    allowClear
                    placeholder={robot.space_id ?? "所有空间"}
                    className="fixed-input"
                  />
                </Form.Item>
                <Form.Item name="expiry" label="有效期" rules={[{ required: true }]}>
                  <Select
                    className="fixed-select"
                    options={[
                      { value: "24h", label: "24 小时" },
                      { value: "7d", label: "7 天" },
                      { value: "never", label: "不过期" },
                    ]}
                  />
                </Form.Item>
                <Form.Item label=" ">
                  <Button type="primary" htmlType="submit" loading={grantMutation.isPending}>
                    授权
                  </Button>
                </Form.Item>
              </Space>
            </Form>
            <Table
              rowKey="id"
              columns={consentColumns}
              dataSource={consentsQuery.data ?? []}
              loading={consentsQuery.isFetching}
              size="small"
              pagination={{ pageSize: 5, hideOnSinglePage: true }}
              locale={{ emptyText: <Empty description="暂无授权记录" /> }}
            />
          </Card>

          <Card title={`机器人任务（${taskRequestsQuery.data?.length ?? 0}）`}>
            <Table
              rowKey="id"
              columns={taskColumns}
              dataSource={taskRequestsQuery.data ?? []}
              loading={taskRequestsQuery.isFetching}
              size="small"
              pagination={{ pageSize: 8, hideOnSinglePage: true }}
              locale={{ emptyText: <Empty description="暂无机器人任务" /> }}
            />
          </Card>

          <Card title={`机器人事件（${eventsQuery.data?.length ?? 0}）`}>
            <Table
              rowKey="id"
              columns={eventColumns}
              dataSource={eventsQuery.data ?? []}
              loading={eventsQuery.isFetching}
              size="small"
              pagination={{ pageSize: 8, hideOnSinglePage: true }}
              locale={{ emptyText: <Empty description="暂无机器人事件" /> }}
            />
          </Card>
        </>
      )}
    </section>
  );
}
