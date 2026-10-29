import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Empty, Select, Space, Switch, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { ReloadOutlined } from "@ant-design/icons";
import { Link } from "react-router-dom";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import PageLoading from "@/components/PageLoading";
import { listAutomations, setAutomationEnabled } from "@/api/automations";
import type { Automation } from "@/types/automations";
import { formatDateTime } from "@/utils/format";

export default function AutomationListPage() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [enabledFilter, setEnabledFilter] = useState<string | undefined>();

  const automationsQuery = useQuery({
    queryKey: ["automations", { page, pageSize, enabledFilter }],
    queryFn: () =>
      listAutomations({
        page,
        page_size: pageSize,
        enabled: enabledFilter === undefined ? undefined : enabledFilter === "enabled",
      }),
    placeholderData: keepPreviousData,
  });

  const enabledMutation = useMutation({
    mutationFn: ({ automation, enabled }: { automation: Automation; enabled: boolean }) =>
      setAutomationEnabled(automation.id, enabled),
    onSuccess: (automation) => {
      void queryClient.invalidateQueries({ queryKey: ["automations"] });
      void queryClient.invalidateQueries({ queryKey: ["automation", automation.id] });
    },
  });

  const columns: ColumnsType<Automation> = [
    {
      title: "规则",
      dataIndex: "name",
      render: (value: string, automation) => (
        <div>
          <Link to={`/automations/${automation.id}`}>{value}</Link>
          <div className="secondary-text">{automation.trigger.event_type}</div>
        </div>
      ),
    },
    {
      title: "动作",
      dataIndex: "action",
      render: (_, automation) => (
        <Space direction="vertical" size={0}>
          <span>{automation.action.title}</span>
          <span className="secondary-text">
            {automation.action.type === "tool" ? automation.action.tool_name : "站内通知"}
          </span>
        </Space>
      ),
    },
    {
      title: "风险",
      dataIndex: "risk_level",
      render: (value: Automation["risk_level"]) => (
        <Tag color={value === "read_only" ? "green" : value === "low_risk" ? "blue" : "red"}>
          {value}
        </Tag>
      ),
    },
    { title: "冷却（秒）", dataIndex: "cooldown_seconds", width: 110 },
    {
      title: "启用",
      dataIndex: "enabled",
      width: 100,
      render: (value: boolean, automation) => (
        <Switch
          checked={value}
          loading={
            enabledMutation.isPending && enabledMutation.variables?.automation.id === automation.id
          }
          onChange={(enabled) => enabledMutation.mutate({ automation, enabled })}
        />
      ),
    },
    { title: "更新时间", dataIndex: "updated_at", render: formatDateTime },
  ];

  if (automationsQuery.isPending) {
    return <PageLoading text="正在读取自动化规则..." />;
  }

  return (
    <section className="page-stack">
      <header className="page-header">
        <div>
          <h1>自动化</h1>
          <p>仅显示 Arvuno 上下文规则；普通场景和定时自动化仍由 Home Assistant 管理。</p>
        </div>
        <Button
          icon={<ReloadOutlined />}
          loading={automationsQuery.isFetching}
          onClick={() => void automationsQuery.refetch()}
        >
          刷新
        </Button>
      </header>

      {automationsQuery.isError ? (
        <ApiErrorAlert
          error={automationsQuery.error}
          onRetry={() => void automationsQuery.refetch()}
          retrying={automationsQuery.isFetching}
        />
      ) : null}
      {enabledMutation.isError ? <ApiErrorAlert error={enabledMutation.error} /> : null}

      <Card>
        <Space className="filter-bar" wrap>
          <Select
            allowClear
            placeholder="启用状态"
            value={enabledFilter}
            onChange={(value) => {
              setPage(1);
              setEnabledFilter(value);
            }}
            options={[
              { value: "enabled", label: "已启用" },
              { value: "disabled", label: "已禁用" },
            ]}
            className="fixed-select"
          />
        </Space>
      </Card>

      <Card title={`规则（${automationsQuery.data?.total ?? 0}）`}>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={automationsQuery.data?.data ?? []}
          loading={automationsQuery.isFetching}
          size="small"
          pagination={{
            current: page,
            pageSize,
            total: automationsQuery.data?.total ?? 0,
            showSizeChanger: true,
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPage);
              setPageSize(nextPageSize);
            },
          }}
          locale={{ emptyText: <Empty description="暂无自动化规则" /> }}
        />
      </Card>
    </section>
  );
}
