import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Collapse,
  Descriptions,
  Empty,
  Alert,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { AimOutlined, ReloadOutlined } from "@ant-design/icons";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import PageLoading from "@/components/PageLoading";
import {
  closeGoal,
  confirmGoal,
  createGoal,
  createPlan,
  decidePlan,
  listGoals,
  listPlans,
  replanPlan,
  submitPlan,
} from "@/api/intelligence";
import type { Goal, Plan } from "@/types/intelligence";
import { formatDateTime, formatJson } from "@/utils/format";

const goalStatuses = [
  "candidate",
  "active",
  "paused",
  "completed",
  "failed",
  "cancelled",
  "expired",
];
const planStatuses = [
  "draft",
  "validated",
  "awaiting_confirmation",
  "approved",
  "submitted",
  "superseded",
  "cancelled",
  "rejected",
];

export default function PlanningPage() {
  const queryClient = useQueryClient();
  const [goalForm] = Form.useForm();
  const [closeForm] = Form.useForm();
  const [replanForm] = Form.useForm();
  const [goalStatus, setGoalStatus] = useState<Goal["status"] | undefined>();
  const [planStatus, setPlanStatus] = useState<Plan["status"] | undefined>();
  const [closeTarget, setCloseTarget] = useState<Goal | null>(null);
  const [replanTarget, setReplanTarget] = useState<Plan | null>(null);
  const [planDetail, setPlanDetail] = useState<Plan | null>(null);

  const goalsQuery = useQuery({
    queryKey: ["planning-goals", goalStatus],
    queryFn: () => listGoals({ status: goalStatus, pageSize: 50 }),
    placeholderData: keepPreviousData,
  });
  const plansQuery = useQuery({
    queryKey: ["planning-plans", planStatus],
    queryFn: () => listPlans({ status: planStatus, pageSize: 50 }),
    placeholderData: keepPreviousData,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["planning-goals"] });
    void queryClient.invalidateQueries({ queryKey: ["planning-plans"] });
  };
  const create = useMutation({
    mutationFn: createGoal,
    onSuccess: () => {
      goalForm.resetFields();
      invalidate();
    },
  });
  const confirm = useMutation({ mutationFn: confirmGoal, onSuccess: invalidate });
  const close = useMutation({
    mutationFn: (input: {
      id: string;
      status: "completed" | "failed" | "cancelled" | "expired";
      reason: string;
    }) => closeGoal(input.id, input.status, input.reason),
    onSuccess: () => {
      setCloseTarget(null);
      invalidate();
    },
  });
  const compile = useMutation({
    mutationFn: (goalId: string) => createPlan(goalId, false),
    onSuccess: (plan) => {
      setPlanDetail(plan);
      invalidate();
    },
  });
  const decide = useMutation({
    mutationFn: (input: { id: string; action: "approve" | "reject" }) =>
      decidePlan(input.id, input.action, "Web console decision"),
    onSuccess: invalidate,
  });
  const submit = useMutation({ mutationFn: submitPlan, onSuccess: invalidate });
  const replan = useMutation({
    mutationFn: (input: {
      id: string;
      triggerType: "tool_failed" | "verification_failed" | "timeout";
      reason: string;
    }) => replanPlan(input.id, input.triggerType, input.reason),
    onSuccess: () => {
      setReplanTarget(null);
      invalidate();
    },
  });

  const goalColumns: ColumnsType<Goal> = [
    {
      title: "目标",
      dataIndex: "title",
      render: (value: string, goal) => (
        <div>
          <strong>{value}</strong>
          <div className="secondary-text">{goal.objective}</div>
        </div>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      render: (value: Goal["status"]) => (
        <Tag color={value === "active" ? "green" : value === "failed" ? "red" : "gold"}>
          {value}
        </Tag>
      ),
    },
    { title: "优先级", dataIndex: "priority", width: 100 },
    {
      title: "确认",
      dataIndex: "confirmed_by_user",
      width: 90,
      render: (value: boolean) => (value ? "是" : "否"),
    },
    { title: "更新", dataIndex: "updated_at", render: formatDateTime, width: 165 },
    {
      title: "操作",
      key: "actions",
      fixed: "right",
      width: 190,
      render: (_, goal) => (
        <Space>
          {!goal.confirmed_by_user ? (
            <Button
              size="small"
              loading={confirm.isPending && confirm.variables === goal.id}
              onClick={() => confirm.mutate(goal.id)}
            >
              确认
            </Button>
          ) : null}
          <Button size="small" onClick={() => setCloseTarget(goal)}>
            关闭
          </Button>
          <Button
            size="small"
            loading={compile.isPending && compile.variables === goal.id}
            onClick={() => compile.mutate(goal.id)}
          >
            编译
          </Button>
        </Space>
      ),
    },
  ];

  const planColumns: ColumnsType<Plan> = [
    {
      title: "计划",
      dataIndex: "id",
      render: (value: string, plan) => (
        <div>
          <strong>{value}</strong>
          <div className="secondary-text">
            v{plan.version} · {plan.goal_id}
          </div>
        </div>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      render: (value: Plan["status"]) => (
        <Tag color={value === "submitted" ? "green" : value === "rejected" ? "red" : "gold"}>
          {value}
        </Tag>
      ),
    },
    { title: "规划器", dataIndex: "planner_type", width: 100 },
    { title: "风险", dataIndex: "max_risk_level", width: 110 },
    {
      title: "步骤",
      dataIndex: "steps",
      render: (value: Plan["steps"]) => value.length,
      width: 80,
    },
    { title: "更新", dataIndex: "updated_at", render: formatDateTime, width: 165 },
    {
      title: "操作",
      key: "actions",
      fixed: "right",
      width: 230,
      render: (_, plan) => (
        <Space wrap>
          <Button size="small" onClick={() => setPlanDetail(plan)}>
            详情
          </Button>
          {plan.status === "awaiting_confirmation" || plan.status === "validated" ? (
            <>
              <Button
                size="small"
                type="primary"
                loading={decide.isPending && decide.variables?.id === plan.id}
                onClick={() => decide.mutate({ id: plan.id, action: "approve" })}
              >
                批准
              </Button>
              <Button
                size="small"
                danger
                loading={decide.isPending && decide.variables?.id === plan.id}
                onClick={() => decide.mutate({ id: plan.id, action: "reject" })}
              >
                拒绝
              </Button>
            </>
          ) : null}
          {plan.status === "approved" ? (
            <Button
              size="small"
              loading={submit.isPending && submit.variables === plan.id}
              onClick={() => submit.mutate(plan.id)}
            >
              提交
            </Button>
          ) : null}
          <Button size="small" onClick={() => setReplanTarget(plan)}>
            重新规划
          </Button>
        </Space>
      ),
    },
  ];

  if (goalsQuery.isPending) {
    return <PageLoading text="正在读取规划目标..." />;
  }

  return (
    <section className="page-stack">
      <header className="page-header">
        <div>
          <h1>计划</h1>
          <p>创建目标，编译受安全约束的计划，执行批准、拒绝、提交和重新规划。</p>
        </div>
        <Button
          icon={<ReloadOutlined />}
          loading={goalsQuery.isFetching || plansQuery.isFetching}
          onClick={() => {
            void goalsQuery.refetch();
            void plansQuery.refetch();
          }}
        >
          刷新
        </Button>
      </header>

      {goalsQuery.isError ? <ApiErrorAlert error={goalsQuery.error} /> : null}
      {plansQuery.isError ? <ApiErrorAlert error={plansQuery.error} /> : null}
      {create.isError ||
      confirm.isError ||
      close.isError ||
      compile.isError ||
      decide.isError ||
      submit.isError ||
      replan.isError ? (
        <Alert
          type="error"
          message="规划操作失败"
          description={String(
            create.error ??
              confirm.error ??
              close.error ??
              compile.error ??
              decide.error ??
              submit.error ??
              replan.error,
          )}
        />
      ) : null}
      {create.isSuccess ? (
        <Alert type="success" message="目标已创建" description={create.data.id} closable />
      ) : null}

      <Card title="创建目标">
        <Form form={goalForm} layout="vertical" onFinish={(values) => create.mutate(values)}>
          <Space wrap size={12} align="end">
            <Form.Item
              name="objective"
              label="目标"
              rules={[{ required: true, message: "请输入目标" }]}
              style={{ minWidth: 340 }}
            >
              <Input.TextArea rows={2} placeholder="保持客厅温度在 24 度附近" />
            </Form.Item>
            <Form.Item name="description" label="说明">
              <Input.TextArea rows={2} />
            </Form.Item>
            <Form.Item name="priority" label="优先级" initialValue="normal">
              <Select
                options={["low", "normal", "high", "critical"].map((value) => ({
                  value,
                  label: value,
                }))}
                className="fixed-select"
              />
            </Form.Item>
            <Form.Item name="reasoningSessionId" label="推理会话 ID">
              <Input allowClear />
            </Form.Item>
            <Form.Item>
              <Button
                type="primary"
                htmlType="submit"
                icon={<AimOutlined />}
                loading={create.isPending}
              >
                创建
              </Button>
            </Form.Item>
          </Space>
        </Form>
      </Card>

      <Card title={`目标（${goalsQuery.data?.total ?? 0}）`}>
        <Space className="filter-bar" wrap style={{ marginBottom: 16 }}>
          <Select
            allowClear
            placeholder="目标状态"
            value={goalStatus}
            onChange={setGoalStatus}
            className="fixed-select"
            options={goalStatuses.map((value) => ({ value, label: value }))}
          />
        </Space>
        <Table
          rowKey="id"
          columns={goalColumns}
          dataSource={goalsQuery.data?.data ?? []}
          loading={goalsQuery.isFetching}
          scroll={{ x: 1000 }}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          locale={{ emptyText: <Empty description="暂无目标" /> }}
        />
      </Card>

      <Card title={`计划（${plansQuery.data?.total ?? 0}）`}>
        <Space className="filter-bar" wrap style={{ marginBottom: 16 }}>
          <Select
            allowClear
            placeholder="计划状态"
            value={planStatus}
            onChange={setPlanStatus}
            className="fixed-select"
            options={planStatuses.map((value) => ({ value, label: value }))}
          />
        </Space>
        <Table
          rowKey="id"
          columns={planColumns}
          dataSource={plansQuery.data?.data ?? []}
          loading={plansQuery.isFetching}
          scroll={{ x: 1200 }}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          locale={{ emptyText: <Empty description="暂无计划" /> }}
        />
      </Card>

      <Modal
        open={closeTarget !== null}
        title="关闭目标"
        onCancel={() => setCloseTarget(null)}
        onOk={() => closeForm.submit()}
        confirmLoading={close.isPending}
      >
        <Form
          form={closeForm}
          layout="vertical"
          onFinish={(values) => {
            if (closeTarget)
              close.mutate({ id: closeTarget.id, status: values.status, reason: values.reason });
          }}
        >
          <Form.Item
            name="status"
            label="结束状态"
            initialValue="completed"
            rules={[{ required: true }]}
          >
            <Select
              options={["completed", "failed", "cancelled", "expired"].map((value) => ({
                value,
                label: value,
              }))}
            />
          </Form.Item>
          <Form.Item name="reason" label="原因" rules={[{ required: true, message: "请输入原因" }]}>
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={replanTarget !== null}
        title="重新规划"
        onCancel={() => setReplanTarget(null)}
        onOk={() => replanForm.submit()}
        confirmLoading={replan.isPending}
      >
        <Form
          form={replanForm}
          layout="vertical"
          onFinish={(values) => {
            if (replanTarget)
              replan.mutate({
                id: replanTarget.id,
                triggerType: values.triggerType,
                reason: values.reason,
              });
          }}
        >
          <Form.Item
            name="triggerType"
            label="触发类型"
            initialValue="environment_changed"
            rules={[{ required: true }]}
          >
            <Select
              options={["environment_changed", "tool_failed", "verification_failed", "timeout"].map(
                (value) => ({ value, label: value }),
              )}
            />
          </Form.Item>
          <Form.Item name="reason" label="原因" rules={[{ required: true, message: "请输入原因" }]}>
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={planDetail !== null}
        title="计划详情"
        footer={null}
        onCancel={() => setPlanDetail(null)}
        width={960}
      >
        {planDetail ? (
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            <Descriptions
              size="small"
              bordered
              column={2}
              items={[
                { key: "id", label: "计划 ID", children: planDetail.id },
                { key: "status", label: "状态", children: planDetail.status },
                { key: "mode", label: "执行模式", children: planDetail.run_mode },
                { key: "risk", label: "最高风险", children: planDetail.max_risk_level },
              ]}
            />
            <Descriptions
              size="small"
              bordered
              column={1}
              items={[
                { key: "strategy", label: "策略", children: formatJson(planDetail.strategy) },
              ]}
            />
            <Collapse
              items={planDetail.steps.map((step) => ({
                key: step.id,
                label: `${step.step_index + 1}. ${step.name}`,
                children: (
                  <Descriptions
                    size="small"
                    bordered
                    column={1}
                    items={[
                      { key: "purpose", label: "目的", children: step.purpose },
                      { key: "tool", label: "工具", children: step.tool_name },
                      { key: "input", label: "输入", children: formatJson(step.input) },
                      { key: "risk", label: "风险", children: step.risk_level },
                      {
                        key: "confirm",
                        label: "需要确认",
                        children: step.requires_confirmation ? "是" : "否",
                      },
                      { key: "failure", label: "失败策略", children: step.on_failure },
                    ]}
                  />
                ),
              }))}
            />
          </Space>
        ) : null}
      </Modal>
    </section>
  );
}
