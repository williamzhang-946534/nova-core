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
  Switch,
  Modal,
  Table,
  Tag,
  message,
} from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import { useState } from "react";

import {
  getStateEstimateEvidence,
  listStateEstimates,
  rebuildStateEstimates,
} from "@/api/state-estimates";
import type { StateEstimate, StateEstimateEvidence } from "@/types/state-estimates";

const statusColors: Record<string, string> = {
  observed: "green",
  derived: "blue",
  inferred: "gold",
  unknown: "default",
  stale: "orange",
  unavailable: "red",
  conflict: "volcano",
};

export default function StateEstimatesPage() {
  const queryClient = useQueryClient();
  const [form] = Form.useForm();
  const [status, setStatus] = useState<StateEstimate["status"] | undefined>();
  const [attribute, setAttribute] = useState<string | undefined>();
  const [includeHistory, setIncludeHistory] = useState(false);
  const [evidence, setEvidence] = useState<StateEstimateEvidence[] | null>(null);

  const listQuery = useQuery({
    queryKey: ["state-estimates", { status, attribute, includeHistory }],
    queryFn: () => listStateEstimates({ status, attribute, pageSize: 100, includeHistory }),
  });
  const rebuild = useMutation({
    mutationFn: rebuildStateEstimates,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["state-estimates"] });
      void message.success("状态投影已重建");
    },
  });
  async function showEvidence(record: StateEstimate) {
    try {
      setEvidence(await getStateEstimateEvidence(record.id));
    } catch (error) {
      message.error(error instanceof Error ? error.message : "加载证据失败");
    }
  }

  const items = listQuery.data?.data ?? [];

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Card
        title="State Estimates"
        extra={
          <Button
            icon={<ReloadOutlined />}
            loading={rebuild.isPending}
            onClick={() => rebuild.mutate()}
          >
            重建投影
          </Button>
        }
      >
        {rebuild.data ? (
          <Descriptions
            size="small"
            column={4}
            items={[
              { key: "env", label: "环境", children: rebuild.data.environment_id },
              { key: "targets", label: "目标", children: rebuild.data.targets },
              { key: "appended", label: "新增", children: rebuild.data.appended },
              { key: "unchanged", label: "未变化", children: rebuild.data.unchanged },
            ]}
          />
        ) : null}
      </Card>

      <Card
        title="估计状态"
        extra={
          <Space>
            <Switch
              checked={includeHistory}
              onChange={setIncludeHistory}
              checkedChildren="含历史"
              unCheckedChildren="当前值"
            />
            <Button loading={listQuery.isFetching} onClick={() => void listQuery.refetch()}>
              刷新
            </Button>
          </Space>
        }
      >
        <Form form={form} component={false}>
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
              placeholder="属性"
              value={attribute}
              onChange={(event) => setAttribute(event.target.value || undefined)}
              onSearch={setAttribute}
              style={{ width: 220 }}
            />
          </Space>
        </Form>
        {listQuery.isError ? (
          <Alert
            type="error"
            showIcon
            message="状态投影加载失败"
            description={listQuery.error.message}
          />
        ) : null}
        <Table
          rowKey="id"
          loading={listQuery.isPending}
          dataSource={items}
          scroll={{ x: 1200 }}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          columns={[
            { title: "属性", dataIndex: "attribute" },
            {
              title: "状态",
              dataIndex: "status",
              render: (value: string) => <Tag color={statusColors[value]}>{value}</Tag>,
            },
            {
              title: "值",
              dataIndex: "value",
              render: (value, record) =>
                `${String(value ?? "-")}${record.unit ? ` ${record.unit}` : ""}`,
            },
            {
              title: "置信度",
              dataIndex: "confidence",
              render: (value?: number | null) =>
                value === null || value === undefined ? "-" : `${Math.round(value * 100)}%`,
            },
            { title: "目标", dataIndex: "target_id" },
            {
              title: "实体",
              dataIndex: "entity_id",
              render: (value?: string | null) => value ?? "-",
            },
            {
              title: "空间",
              dataIndex: "space_id",
              render: (value?: string | null) => value ?? "-",
            },
            {
              title: "生成时间",
              dataIndex: "generated_at",
              render: (value: string) => new Date(value).toLocaleString(),
            },
            {
              title: "证据",
              key: "evidence",
              fixed: "right",
              render: (_, record) => (
                <Button type="link" onClick={() => void showEvidence(record)}>
                  查看
                </Button>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        open={evidence !== null}
        title="估计证据"
        footer={null}
        onCancel={() => setEvidence(null)}
      >
        <Table
          rowKey="observation_id"
          dataSource={evidence ?? []}
          pagination={false}
          columns={[
            { title: "来源", dataIndex: "source_type" },
            { title: "观测", dataIndex: "observation_id" },
            { title: "贡献", dataIndex: "contribution" },
            { title: "质量", dataIndex: "quality_status" },
            {
              title: "权重",
              dataIndex: "weight",
              render: (value?: number | null) =>
                value === null || value === undefined ? "-" : value.toFixed(3),
            },
            {
              title: "排除原因",
              dataIndex: "exclusion_reason",
              render: (value?: string | null) => value ?? "-",
            },
          ]}
        />
      </Modal>
    </Space>
  );
}
