import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space as AntSpace,
  Table,
  Tag,
  Tooltip,
  Tree,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  EditOutlined,
  EyeOutlined,
  HistoryOutlined,
  LinkOutlined,
  PlusOutlined,
  ReloadOutlined,
  StopOutlined,
  SwapOutlined,
} from "@ant-design/icons";
import type { DataNode } from "antd/es/tree";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import JsonBlock from "@/components/JsonBlock";
import PageLoading from "@/components/PageLoading";
import StatusTag from "@/components/StatusTag";
import { listDevices } from "@/api/devices";
import {
  archiveSpace,
  assignDeviceSpace,
  createSpace,
  getDeviceSpaceHistory,
  getSpaceOverview,
  getSpaceTree,
  listSpaceDevices,
  moveSpace,
  updateSpace,
} from "@/api/spaces";
import type { Device } from "@/types/console";
import type { JsonRecord, JsonValue } from "@/types/common";
import { listObservations } from "@/api/observations";
import type { ObservationItem, ObservationQualityStatus } from "@/types/observations";
import type {
  AssignedDevice,
  AssignmentHistoryItem,
  AssignmentType,
  EnvironmentCoverageStatus,
  QuerySourceSummary,
  Space,
  SpaceTreeNode,
  StateCoverage,
  StateEstimate,
  StateEstimateEvidence,
  StateEstimationStatus,
} from "@/types/spaces";
import { formatDateTime, formatDeviceType } from "@/utils/format";

interface CreateFormValues {
  parent_id: string;
  name: string;
  space_type: "floor" | "room" | "zone";
  sort_order: number;
}

interface EditFormValues {
  name: string;
  sort_order: number;
  status: "active" | "inactive";
}

interface MoveFormValues {
  new_parent_id: string;
}

interface AssignmentFormValues {
  space_id: string;
  assignment_type: string;
  confidence: number;
  reason: string;
}

function flattenSpaces(nodes: SpaceTreeNode[]): Space[] {
  return nodes.flatMap((node) => [node, ...flattenSpaces(node.children)]);
}

function descendantIds(node: SpaceTreeNode): string[] {
  return [node.id, ...node.children.flatMap(descendantIds)];
}

function spaceTypeLabel(value: Space["space_type"]): string {
  const labels: Record<Space["space_type"], string> = {
    home: "住宅",
    floor: "楼层",
    room: "房间",
    zone: "区域",
  };
  return labels[value];
}

function assignmentTypeLabel(value: string): string {
  const labels: Record<string, string> = {
    fixed_installation: "固定安装",
    current_placement: "当前位置",
    observed_presence: "观测在场",
    user_asserted: "用户指定",
  };
  return labels[value] ?? value;
}

const stateStatusMeta: Record<StateEstimationStatus, { label: string; color: string }> = {
  observed: { label: "已观测", color: "green" },
  derived: { label: "已推导", color: "cyan" },
  inferred: { label: "推断", color: "blue" },
  unknown: { label: "未知", color: "default" },
  stale: { label: "已过期", color: "orange" },
  unavailable: { label: "不可用", color: "red" },
  conflict: { label: "冲突", color: "purple" },
};

const coverageMeta: Record<EnvironmentCoverageStatus, { label: string; color: string }> = {
  covered: { label: "已覆盖", color: "green" },
  partial: { label: "部分覆盖", color: "orange" },
  blind: { label: "盲区", color: "default" },
  lost: { label: "覆盖丢失", color: "red" },
};

const qualityMeta: Record<ObservationQualityStatus, { label: string; color: string }> = {
  pending: { label: "待处理", color: "default" },
  valid: { label: "有效", color: "green" },
  warning: { label: "警告", color: "orange" },
  invalid: { label: "无效", color: "red" },
};

function stateStatusTag(value: StateEstimationStatus) {
  const meta = stateStatusMeta[value];
  return <Tag color={meta.color}>{meta.label}</Tag>;
}

function coverageTag(value: EnvironmentCoverageStatus) {
  const meta = coverageMeta[value];
  return <Tag color={meta.color}>{meta.label}</Tag>;
}

function qualityTag(value: ObservationQualityStatus) {
  const meta = qualityMeta[value];
  return <Tag color={meta.color}>{meta.label}</Tag>;
}

function formatStateValue(value: JsonValue, unit: string | null): string {
  if (value === null) {
    return "-";
  }
  if (typeof value === "boolean") {
    return value ? "开" : "关";
  }
  const rendered = typeof value === "object" ? JSON.stringify(value) : String(value);
  return unit ? `${rendered} ${unit}` : rendered;
}

function stringIds(summary: JsonRecord, key: string): string[] {
  const value = summary[key];
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

export default function SpacesPage() {
  const queryClient = useQueryClient();
  const [selectedSpaceId, setSelectedSpaceId] = useState<string | null>(null);
  const [expandedKeys, setExpandedKeys] = useState<string[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [observationPage, setObservationPage] = useState(1);
  const [observationPageSize, setObservationPageSize] = useState(20);
  const [createOpen, setCreateOpen] = useState(false);
  const [editingSpace, setEditingSpace] = useState<Space | null>(null);
  const [movingSpace, setMovingSpace] = useState<SpaceTreeNode | null>(null);
  const [assignmentDevice, setAssignmentDevice] = useState<Device | null>(null);
  const [historyDeviceId, setHistoryDeviceId] = useState<string | null>(null);
  const [selectedStateId, setSelectedStateId] = useState<string | null>(null);

  const [createForm] = Form.useForm<CreateFormValues>();
  const [editForm] = Form.useForm<EditFormValues>();
  const [moveForm] = Form.useForm<MoveFormValues>();
  const [assignmentForm] = Form.useForm<AssignmentFormValues>();

  const spacesQuery = useQuery({ queryKey: ["spaces", "tree"], queryFn: getSpaceTree });
  const devicesQuery = useQuery({
    queryKey: ["devices", "spaces-page", page, pageSize],
    queryFn: () => listDevices({ page, page_size: pageSize }),
  });
  const root = spacesQuery.data;
  const spaces = useMemo(() => (root ? flattenSpaces([root]) : []), [root]);
  const selectedSpace = useMemo(
    () => spaces.find((space) => space.id === selectedSpaceId) ?? root ?? null,
    [spaces, selectedSpaceId, root],
  );

  const spaceDevicesQuery = useQuery({
    queryKey: ["spaces", "devices", selectedSpace?.id ?? null, true],
    queryFn: () => listSpaceDevices(selectedSpace?.id ?? "", true),
    enabled: selectedSpace !== null,
  });
  const overviewQuery = useQuery({
    queryKey: ["spaces", "overview", selectedSpace?.id ?? null, true, true],
    queryFn: () =>
      getSpaceOverview(selectedSpace?.id ?? "", {
        includeDescendants: true,
        includeEvidence: true,
      }),
    enabled: selectedSpace !== null,
  });
  const observationsQuery = useQuery({
    queryKey: [
      "observations",
      "space",
      selectedSpace?.id ?? null,
      true,
      observationPage,
      observationPageSize,
    ],
    queryFn: () =>
      listObservations({
        spaceId: selectedSpace?.id,
        includeDescendants: true,
        page: observationPage,
        pageSize: observationPageSize,
      }),
    enabled: selectedSpace !== null,
    placeholderData: keepPreviousData,
  });
  const historyQuery = useQuery({
    queryKey: ["spaces", "device-history", historyDeviceId],
    queryFn: () => getDeviceSpaceHistory(historyDeviceId ?? ""),
    enabled: historyDeviceId !== null,
  });

  useEffect(() => {
    if (root) {
      setExpandedKeys((current) =>
        current.length > 0 ? current : spaces.map((space) => space.id),
      );
    }
  }, [root, spaces]);

  useEffect(() => {
    setObservationPage(1);
    setSelectedStateId(null);
  }, [selectedSpace?.id]);

  useEffect(() => {
    if (editingSpace) {
      editForm.setFieldsValue({
        name: editingSpace.name,
        sort_order: editingSpace.sort_order,
        status: editingSpace.status === "active" ? "active" : "inactive",
      });
    }
  }, [editForm, editingSpace]);

  useEffect(() => {
    if (assignmentDevice) {
      assignmentForm.setFieldsValue({
        space_id: selectedSpace?.id,
        assignment_type: "fixed_installation",
        confidence: 1,
        reason: "",
      });
    }
  }, [assignmentForm, assignmentDevice, selectedSpace]);

  function invalidateSpatialData(deviceId?: string) {
    void queryClient.invalidateQueries({ queryKey: ["spaces"] });
    void queryClient.invalidateQueries({ queryKey: ["devices"] });
    void queryClient.invalidateQueries({ queryKey: ["observations", "space"] });
    if (deviceId) {
      void queryClient.invalidateQueries({
        queryKey: ["spaces", "device-history", deviceId],
      });
    }
  }

  const createMutation = useMutation({
    mutationFn: createSpace,
    onSuccess: (space) => {
      setCreateOpen(false);
      setSelectedSpaceId(space.id);
      invalidateSpatialData();
    },
  });
  const updateMutation = useMutation({
    mutationFn: (input: { spaceId: string; values: EditFormValues }) =>
      updateSpace(input.spaceId, input.values),
    onSuccess: (space) => {
      setEditingSpace(null);
      setSelectedSpaceId(space.id);
      invalidateSpatialData();
    },
  });
  const moveMutation = useMutation({
    mutationFn: (input: { spaceId: string; parentId: string }) =>
      moveSpace(input.spaceId, input.parentId),
    onSuccess: (space) => {
      setMovingSpace(null);
      setSelectedSpaceId(space.id);
      invalidateSpatialData();
    },
  });
  const archiveMutation = useMutation({
    mutationFn: archiveSpace,
    onSuccess: (space) => {
      if (selectedSpaceId === space.id) {
        setSelectedSpaceId(space.parent_id);
      }
      invalidateSpatialData();
    },
  });
  const assignmentMutation = useMutation({
    mutationFn: (input: { deviceId: string; values: AssignmentFormValues }) =>
      assignDeviceSpace(input.deviceId, {
        space_id: input.values.space_id,
        assignment_type: input.values.assignment_type as AssignmentType,
        confidence: input.values.confidence,
        reason: input.values.reason || undefined,
      }),
    onSuccess: (_assignment, input) => {
      setAssignmentDevice(null);
      invalidateSpatialData(input.deviceId);
    },
  });

  const treeData: DataNode[] = useMemo(() => {
    function build(nodes: SpaceTreeNode[]): DataNode[] {
      return nodes.map((node) => ({
        key: node.id,
        title: (
          <AntSpace size={6} wrap>
            <span>
              <strong>{node.name}</strong> <Tag>{spaceTypeLabel(node.space_type)}</Tag>
            </span>
            {node.id !== root?.id ? (
              <>
                <Tooltip title="编辑空间">
                  <Button
                    size="small"
                    type="text"
                    icon={<EditOutlined />}
                    onClick={() => setEditingSpace(node)}
                  />
                </Tooltip>
                <Tooltip title="移动空间">
                  <Button
                    size="small"
                    type="text"
                    icon={<SwapOutlined />}
                    onClick={() => setMovingSpace(node)}
                  />
                </Tooltip>
                <Popconfirm
                  title="停用这个空间？"
                  description="需先处理子空间和当前设备归属。"
                  okText="停用"
                  cancelText="取消"
                  onConfirm={() => archiveMutation.mutate(node.id)}
                >
                  <Tooltip title="停用空间">
                    <Button size="small" type="text" icon={<StopOutlined />} />
                  </Tooltip>
                </Popconfirm>
              </>
            ) : null}
          </AntSpace>
        ),
        children: build(node.children),
      }));
    }
    return root ? build([root]) : [];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [archiveMutation, root]);

  const activeParentOptions = spaces
    .filter((space) => space.status === "active")
    .map((space) => ({
      value: space.id,
      label: `${space.path} · ${space.name}`,
    }));

  const moveOptions = movingSpace
    ? (() => {
        const excludedIds = new Set(descendantIds(movingSpace));
        return spaces
          .filter((space) => space.status === "active" && !excludedIds.has(space.id))
          .map((space) => ({ value: space.id, label: `${space.path} · ${space.name}` }));
      })()
    : [];

  const queriedSpaces = overviewQuery.data?.spaces ?? [];
  const queriedEntities = overviewQuery.data?.entities ?? [];
  const spaceById = new Map(queriedSpaces.map((space) => [space.space_id, space]));
  const entityById = new Map(queriedEntities.map((entity) => [entity.entity_id, entity]));
  const selectedState = useMemo(
    () => overviewQuery.data?.states.find((state) => state.id === selectedStateId) ?? null,
    [overviewQuery.data?.states, selectedStateId],
  );
  const selectedObservationIds = useMemo(
    () =>
      new Set(selectedState ? stringIds(selectedState.evidence_summary, "observation_ids") : []),
    [selectedState],
  );
  const selectedEvidence = useMemo(
    () =>
      (overviewQuery.data?.evidence ?? []).filter((item) =>
        selectedObservationIds.has(item.observation_id),
      ),
    [overviewQuery.data?.evidence, selectedObservationIds],
  );

  const stateColumns: ColumnsType<StateEstimate> = [
    {
      title: "目标",
      dataIndex: "target_id",
      render: (_, state) => {
        if (state.target_type === "space" && state.space_id) {
          return spaceById.get(state.space_id)?.name ?? state.target_id;
        }
        if (state.target_type === "entity" && state.entity_id) {
          return entityById.get(state.entity_id)?.name ?? state.target_id;
        }
        return state.target_id;
      },
    },
    {
      title: "属性",
      dataIndex: "attribute",
      render: (value: string) => <Tag>{value}</Tag>,
    },
    {
      title: "当前值",
      dataIndex: "value",
      render: (_, state) => formatStateValue(state.value, state.unit),
    },
    {
      title: "状态",
      dataIndex: "status",
      render: (value: StateEstimationStatus) => stateStatusTag(value),
    },
    {
      title: "置信度",
      dataIndex: "confidence",
      render: (value: number | null) => (value === null ? "-" : value.toFixed(2)),
    },
    {
      title: "规则",
      dataIndex: "rule",
      render: (_, state) => (
        <span className="mono-text">
          {state.rule.id} v{state.rule.version}
        </span>
      ),
    },
    {
      title: "来源数",
      key: "source_count",
      render: (_, state) => stringIds(state.evidence_summary, "source_ids").length,
    },
    {
      title: "生成 / 生效 / 有效至",
      dataIndex: "generated_at",
      render: (_, state) => (
        <div className="secondary-text">
          <div>生成：{formatDateTime(state.generated_at)}</div>
          <div>生效：{formatDateTime(state.effective_from)}</div>
          <div>有效至：{formatDateTime(state.valid_until)}</div>
        </div>
      ),
    },
    {
      title: "证据",
      key: "evidence",
      render: (_, state) => {
        const ids = new Set(stringIds(state.evidence_summary, "observation_ids"));
        const hasEvidence = (overviewQuery.data?.evidence ?? []).some((item) =>
          ids.has(item.observation_id),
        );
        return (
          <Button
            size="small"
            type="text"
            icon={<EyeOutlined />}
            disabled={!hasEvidence}
            onClick={() => setSelectedStateId(state.id)}
          >
            查看
          </Button>
        );
      },
    },
  ];

  const coverageColumns: ColumnsType<StateCoverage> = [
    {
      title: "空间",
      dataIndex: "space_id",
      render: (_, coverage) => spaceById.get(coverage.space_id)?.name ?? coverage.space_id,
    },
    {
      title: "属性",
      dataIndex: "attribute",
      render: (value: string) => <Tag>{value}</Tag>,
    },
    {
      title: "覆盖",
      dataIndex: "coverage",
      render: (value: EnvironmentCoverageStatus) => coverageTag(value),
    },
    {
      title: "估计状态",
      dataIndex: "state_status",
      render: (value: StateEstimationStatus | null) =>
        value ? stateStatusTag(value) : <Tag>未建立</Tag>,
    },
    { title: "来源数", dataIndex: "source_count" },
    {
      title: "说明",
      dataIndex: "explanation",
      ellipsis: true,
    },
  ];

  const observationColumns: ColumnsType<ObservationItem> = [
    {
      title: "属性",
      dataIndex: "attribute",
      render: (value: string) => <Tag>{value}</Tag>,
    },
    {
      title: "标准化值",
      dataIndex: "normalized_value",
      render: (_, observation) =>
        formatStateValue(observation.normalized_value, observation.normalized_unit),
    },
    {
      title: "质量",
      dataIndex: "quality_status",
      render: (value: ObservationQualityStatus) => qualityTag(value),
    },
    {
      title: "采集时间",
      dataIndex: "observed_at",
      render: (_, observation) => (
        <div>
          <div>{formatDateTime(observation.observed_at)}</div>
          <div className="secondary-text">
            {observation.observed_at ? (observation.observed_at_source ?? "-") : "采集时间未知"}
          </div>
        </div>
      ),
    },
    {
      title: "接收时间",
      dataIndex: "received_at",
      render: formatDateTime,
    },
    {
      title: "来源",
      dataIndex: "source_type",
      render: (_, observation) => (
        <div>
          <div>{observation.source_type}</div>
          <div className="mono-text secondary-text">{observation.source_id}</div>
        </div>
      ),
    },
  ];

  const evidenceColumns: ColumnsType<StateEstimateEvidence> = [
    {
      title: "观测",
      dataIndex: "observation_id",
      render: (value: string) => <span className="mono-text">{value}</span>,
    },
    {
      title: "来源",
      dataIndex: "source_type",
      render: (_, evidence) => (
        <div>
          <div>{evidence.source_type}</div>
          <div className="mono-text secondary-text">{evidence.source_id}</div>
        </div>
      ),
    },
    {
      title: "贡献",
      dataIndex: "contribution",
      render: (value: string) => <Tag>{value}</Tag>,
    },
    {
      title: "标准化值",
      dataIndex: "normalized_value",
      render: (_, evidence) =>
        formatStateValue(evidence.normalized_value, evidence.normalized_unit),
    },
    {
      title: "采集时间",
      dataIndex: "observed_at",
      render: (_, evidence) => (
        <div>
          <div>{formatDateTime(evidence.observed_at)}</div>
          <div className="secondary-text">
            {evidence.observed_at ? (evidence.observed_at_source ?? "-") : "采集时间未知"}
          </div>
        </div>
      ),
    },
    {
      title: "接收时间",
      dataIndex: "received_at",
      render: formatDateTime,
    },
    {
      title: "质量",
      dataIndex: "quality_status",
      render: (value: string) => <Tag>{value}</Tag>,
    },
    {
      title: "权重",
      dataIndex: "weight",
      render: (value: number | null) => (value === null ? "-" : value.toFixed(2)),
    },
    {
      title: "排除原因",
      dataIndex: "exclusion_reason",
      render: (value: string | null) => value ?? "-",
    },
  ];

  const sourceColumns: ColumnsType<QuerySourceSummary> = [
    {
      title: "来源",
      dataIndex: "source_id",
      render: (value: string) => <span className="mono-text">{value}</span>,
    },
    { title: "观测数", dataIndex: "observation_count" },
    {
      title: "关联实体",
      dataIndex: "entity_ids",
      render: (values: string[]) => values.join(", ") || "-",
    },
  ];

  const deviceColumns: ColumnsType<Device> = [
    {
      title: "设备",
      dataIndex: "name",
      render: (_, device) => (
        <div>
          <strong>{device.name}</strong>
          <div className="secondary-text">{device.external_id}</div>
        </div>
      ),
    },
    {
      title: "类型",
      dataIndex: "device_type",
      render: (value: string) => <Tag>{formatDeviceType(value)}</Tag>,
    },
    {
      title: "当前区域",
      dataIndex: "area",
      render: (value: string | null) => value ?? "-",
    },
    {
      title: "操作",
      key: "actions",
      render: (_, device) => (
        <AntSpace size={4}>
          <Button size="small" icon={<LinkOutlined />} onClick={() => setAssignmentDevice(device)}>
            归属
          </Button>
          <Button
            size="small"
            type="text"
            icon={<HistoryOutlined />}
            onClick={() => setHistoryDeviceId(device.id)}
          >
            历史
          </Button>
        </AntSpace>
      ),
    },
  ];

  const spaceDeviceColumns: ColumnsType<AssignedDevice> = [
    { title: "设备", dataIndex: "name" },
    {
      title: "归属",
      dataIndex: "assignment_type",
      render: (value: AssignedDevice["assignment_type"]) => <Tag>{assignmentTypeLabel(value)}</Tag>,
    },
    {
      title: "开始时间",
      dataIndex: "valid_from",
      render: formatDateTime,
    },
    {
      title: "置信度",
      dataIndex: "confidence",
      render: (value: number | null) => (value === null ? "-" : value.toFixed(2)),
    },
  ];

  const historyColumns: ColumnsType<AssignmentHistoryItem> = [
    { title: "空间", dataIndex: "space_path" },
    {
      title: "归属",
      dataIndex: "assignment_type",
      render: (value: AssignmentHistoryItem["assignment_type"]) => (
        <Tag>{assignmentTypeLabel(value)}</Tag>
      ),
    },
    {
      title: "生效区间",
      dataIndex: "valid_from",
      render: (_, item) =>
        `${formatDateTime(item.valid_from)} → ${formatDateTime(item.valid_until)}`,
    },
    { title: "来源", dataIndex: "source_type" },
  ];

  if (spacesQuery.isPending) {
    return <PageLoading text="正在读取空间层级..." />;
  }

  const mutationError =
    createMutation.error ??
    updateMutation.error ??
    moveMutation.error ??
    archiveMutation.error ??
    assignmentMutation.error;

  return (
    <section className="page-stack">
      <header className="page-header">
        <div>
          <h1>空间</h1>
          <p>管理住宅、楼层、房间、功能区以及设备的空间归属。</p>
        </div>
        <AntSpace wrap>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              createForm.setFieldsValue({
                parent_id: selectedSpace?.id ?? root?.id,
                name: "",
                space_type: "room",
                sort_order: 0,
              });
              setCreateOpen(true);
            }}
          >
            新建空间
          </Button>
          <Button
            icon={<ReloadOutlined />}
            loading={spacesQuery.isFetching}
            onClick={() => void spacesQuery.refetch()}
          >
            刷新
          </Button>
        </AntSpace>
      </header>

      {spacesQuery.isError ? (
        <ApiErrorAlert
          error={spacesQuery.error}
          onRetry={() => void spacesQuery.refetch()}
          retrying={spacesQuery.isFetching}
        />
      ) : null}
      {mutationError ? <ApiErrorAlert error={mutationError} /> : null}

      <div className="two-column">
        <Card title="空间层级">
          <Tree
            blockNode
            treeData={treeData}
            expandedKeys={expandedKeys}
            selectedKeys={selectedSpace ? [selectedSpace.id] : []}
            onExpand={(keys) =>
              setExpandedKeys(keys.filter((key): key is string => typeof key === "string"))
            }
            onSelect={(keys) => {
              const key = keys[0];
              setSelectedSpaceId(typeof key === "string" ? key : null);
            }}
          />
        </Card>
        <Card title="空间详情">
          {selectedSpace ? (
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="名称">{selectedSpace.name}</Descriptions.Item>
              <Descriptions.Item label="类型">
                <Tag>{spaceTypeLabel(selectedSpace.space_type)}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <StatusTag
                  status={
                    selectedSpace.status === "active"
                      ? "healthy"
                      : selectedSpace.status === "inactive"
                        ? "degraded"
                        : "unavailable"
                  }
                />
              </Descriptions.Item>
              <Descriptions.Item label="路径">
                <span className="mono-text">{selectedSpace.path}</span>
              </Descriptions.Item>
              <Descriptions.Item label="创建时间">
                {formatDateTime(selectedSpace.created_at)}
              </Descriptions.Item>
            </Descriptions>
          ) : (
            <Empty description="选择一个空间" />
          )}
        </Card>
      </div>

      {overviewQuery.isError ? (
        <ApiErrorAlert
          error={overviewQuery.error}
          onRetry={() => void overviewQuery.refetch()}
          retrying={overviewQuery.isFetching}
        />
      ) : null}
      {overviewQuery.data && !overviewQuery.data.service_available ? (
        <Alert
          type="warning"
          showIcon
          message="状态估计服务暂不可用"
          description="当前没有可展示的环境事实。请先恢复 Observation Pipeline 或 State Estimation 服务。"
        />
      ) : null}
      {overviewQuery.isPending ? (
        <Card>
          <PageLoading text="正在读取环境状态..." />
        </Card>
      ) : overviewQuery.data?.service_available ? (
        <>
          <Card
            title={`当前状态估计（${overviewQuery.data.states.length}）`}
            extra={
              <span className="secondary-text">
                生成于 {formatDateTime(overviewQuery.data.generated_at)}
              </span>
            }
          >
            <Table
              rowKey="id"
              columns={stateColumns}
              dataSource={overviewQuery.data.states}
              loading={overviewQuery.isFetching}
              pagination={false}
              size="small"
              scroll={{ x: 1100 }}
              locale={{ emptyText: <Empty description="暂无状态估计" /> }}
            />
          </Card>
          <div className="two-column">
            <Card title={`感知覆盖（${overviewQuery.data.coverage.length}）`}>
              <Table
                rowKey={(coverage) => `${coverage.space_id}:${coverage.attribute}`}
                columns={coverageColumns}
                dataSource={overviewQuery.data.coverage}
                loading={overviewQuery.isFetching}
                pagination={false}
                size="small"
                locale={{ emptyText: <Empty description="暂无覆盖信息" /> }}
              />
            </Card>
            <Card title={`状态来源（${overviewQuery.data.sources.length}）`}>
              <Table
                rowKey="source_id"
                columns={sourceColumns}
                dataSource={overviewQuery.data.sources}
                loading={overviewQuery.isFetching}
                pagination={false}
                size="small"
                locale={{ emptyText: <Empty description="暂无状态来源" /> }}
              />
            </Card>
          </div>
        </>
      ) : null}

      {observationsQuery.isError ? (
        <ApiErrorAlert
          error={observationsQuery.error}
          onRetry={() => void observationsQuery.refetch()}
          retrying={observationsQuery.isFetching}
        />
      ) : null}
      <Card title={`观测历史（${observationsQuery.data?.total ?? 0}）`}>
        <Table
          rowKey="observation_id"
          columns={observationColumns}
          dataSource={observationsQuery.data?.data ?? []}
          loading={observationsQuery.isFetching}
          size="small"
          scroll={{ x: 900 }}
          pagination={{
            current: observationPage,
            pageSize: observationPageSize,
            total: observationsQuery.data?.total ?? 0,
            pageSizeOptions: [10, 20, 50, 100],
            showSizeChanger: true,
            onChange: (nextPage, nextPageSize) => {
              setObservationPage(nextPage);
              setObservationPageSize(nextPageSize);
            },
          }}
          locale={{ emptyText: <Empty description="暂无观测记录" /> }}
        />
      </Card>

      <div className="two-column">
        <Card title={`当前空间设备（${spaceDevicesQuery.data?.length ?? 0}）`}>
          <Table
            rowKey="assignment_id"
            columns={spaceDeviceColumns}
            dataSource={spaceDevicesQuery.data ?? []}
            loading={spaceDevicesQuery.isFetching}
            pagination={false}
            size="small"
            locale={{ emptyText: <Empty description="当前空间树暂无设备" /> }}
          />
        </Card>
        <Card title={`设备归属（${devicesQuery.data?.total ?? 0}）`}>
          <Table
            rowKey="id"
            columns={deviceColumns}
            dataSource={devicesQuery.data?.data ?? []}
            loading={devicesQuery.isFetching}
            pagination={{
              current: page,
              pageSize,
              total: devicesQuery.data?.total ?? 0,
              showSizeChanger: true,
              onChange: (nextPage, nextPageSize) => {
                setPage(nextPage);
                setPageSize(nextPageSize);
              },
            }}
            size="small"
            locale={{ emptyText: <Empty description="暂无设备" /> }}
          />
        </Card>
      </div>

      <Card title="设备空间历史">
        <Table
          rowKey="id"
          columns={historyColumns}
          dataSource={historyQuery.data ?? []}
          loading={historyQuery.isFetching}
          pagination={false}
          size="small"
          locale={{ emptyText: <Empty description="选择设备后查看历史" /> }}
        />
      </Card>

      <Drawer
        title={selectedState ? `${selectedState.attribute} 状态证据` : "状态证据"}
        width={760}
        open={selectedStateId !== null}
        onClose={() => setSelectedStateId(null)}
      >
        {overviewQuery.isFetching && !selectedState ? (
          <PageLoading text="正在读取状态证据..." />
        ) : selectedState ? (
          <div className="page-stack">
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="状态">
                {stateStatusTag(selectedState.status)}
              </Descriptions.Item>
              <Descriptions.Item label="当前值">
                {formatStateValue(selectedState.value, selectedState.unit)}
              </Descriptions.Item>
              <Descriptions.Item label="置信度">
                {selectedState.confidence === null ? "-" : selectedState.confidence.toFixed(2)}
              </Descriptions.Item>
              <Descriptions.Item label="规则">
                <span className="mono-text">
                  {selectedState.rule.id} v{selectedState.rule.version}
                </span>
              </Descriptions.Item>
              <Descriptions.Item label="输入截止">
                {formatDateTime(selectedState.input_cutoff_at)}
              </Descriptions.Item>
              <Descriptions.Item label="生成时间">
                {formatDateTime(selectedState.generated_at)}
              </Descriptions.Item>
              <Descriptions.Item label="生效时间">
                {formatDateTime(selectedState.effective_from)}
              </Descriptions.Item>
              <Descriptions.Item label="有效至">
                {formatDateTime(selectedState.valid_until)}
              </Descriptions.Item>
            </Descriptions>
            {selectedState.conflict_details ? (
              <Card title="冲突详情" size="small">
                <JsonBlock value={selectedState.conflict_details} />
              </Card>
            ) : null}
            <Card title={`输入观测（${selectedEvidence.length}）`} size="small">
              <Table
                rowKey="observation_id"
                columns={evidenceColumns}
                dataSource={selectedEvidence}
                pagination={false}
                size="small"
                scroll={{ x: 900 }}
                locale={{ emptyText: <Empty description="该状态没有可用输入观测" /> }}
              />
            </Card>
          </div>
        ) : (
          <Empty description="状态已被更新，请重新选择状态" />
        )}
      </Drawer>

      <Modal
        title="新建空间"
        open={createOpen}
        okText="创建"
        cancelText="取消"
        confirmLoading={createMutation.isPending}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
      >
        <Form
          form={createForm}
          layout="vertical"
          onFinish={(values) => createMutation.mutate(values)}
        >
          <Form.Item
            name="parent_id"
            label="父空间"
            rules={[{ required: true, message: "请选择父空间" }]}
          >
            <Select options={activeParentOptions} />
          </Form.Item>
          <Form.Item
            name="space_type"
            label="空间类型"
            rules={[{ required: true, message: "请选择空间类型" }]}
          >
            <Select
              options={[
                { value: "floor", label: "楼层" },
                { value: "room", label: "房间" },
                { value: "zone", label: "区域" },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: "请输入空间名称" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="sort_order" label="排序" initialValue={0}>
            <InputNumber min={0} precision={0} className="number-input" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="编辑空间"
        open={editingSpace !== null}
        okText="保存"
        cancelText="取消"
        confirmLoading={updateMutation.isPending}
        onCancel={() => setEditingSpace(null)}
        onOk={() => editForm.submit()}
      >
        <Form
          form={editForm}
          layout="vertical"
          onFinish={(values) => {
            if (editingSpace) {
              updateMutation.mutate({ spaceId: editingSpace.id, values });
            }
          }}
        >
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: "请输入空间名称" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="sort_order" label="排序">
            <InputNumber min={0} precision={0} className="number-input" />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Select
              options={[
                { value: "active", label: "启用" },
                { value: "inactive", label: "停用" },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="移动空间"
        open={movingSpace !== null}
        okText="移动"
        cancelText="取消"
        confirmLoading={moveMutation.isPending}
        onCancel={() => setMovingSpace(null)}
        onOk={() => moveForm.submit()}
      >
        <Form
          form={moveForm}
          layout="vertical"
          initialValues={movingSpace ? { new_parent_id: movingSpace.parent_id ?? undefined } : {}}
          onFinish={(values) => {
            if (movingSpace) {
              moveMutation.mutate({ spaceId: movingSpace.id, parentId: values.new_parent_id });
            }
          }}
        >
          <Form.Item
            name="new_parent_id"
            label="新的父空间"
            rules={[{ required: true, message: "请选择父空间" }]}
          >
            <Select options={moveOptions} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={assignmentDevice ? `设置 ${assignmentDevice.name} 的空间归属` : "设置空间归属"}
        open={assignmentDevice !== null}
        okText="保存"
        cancelText="取消"
        confirmLoading={assignmentMutation.isPending}
        onCancel={() => setAssignmentDevice(null)}
        onOk={() => assignmentForm.submit()}
      >
        <Form
          form={assignmentForm}
          layout="vertical"
          onFinish={(values) => {
            if (assignmentDevice) {
              assignmentMutation.mutate({ deviceId: assignmentDevice.id, values });
            }
          }}
        >
          <Form.Item
            name="space_id"
            label="空间"
            rules={[{ required: true, message: "请选择空间" }]}
          >
            <Select options={activeParentOptions} />
          </Form.Item>
          <Form.Item name="assignment_type" label="归属类型">
            <Select
              options={[
                { value: "fixed_installation", label: "固定安装" },
                { value: "current_placement", label: "当前位置" },
                { value: "observed_presence", label: "观测在场" },
                { value: "user_asserted", label: "用户指定" },
              ]}
            />
          </Form.Item>
          <Form.Item name="confidence" label="置信度">
            <InputNumber min={0} max={1} step={0.1} className="number-input" />
          </Form.Item>
          <Form.Item name="reason" label="说明">
            <Input.TextArea rows={2} maxLength={2000} />
          </Form.Item>
        </Form>
      </Modal>
    </section>
  );
}
