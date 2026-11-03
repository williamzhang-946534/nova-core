import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Descriptions,
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
  HistoryOutlined,
  LinkOutlined,
  PlusOutlined,
  ReloadOutlined,
  StopOutlined,
  SwapOutlined,
} from "@ant-design/icons";
import type { DataNode } from "antd/es/tree";

import ApiErrorAlert from "@/components/ApiErrorAlert";
import PageLoading from "@/components/PageLoading";
import StatusTag from "@/components/StatusTag";
import { listDevices } from "@/api/devices";
import {
  archiveSpace,
  assignDeviceSpace,
  createSpace,
  getDeviceSpaceHistory,
  getSpaceTree,
  listSpaceDevices,
  moveSpace,
  updateSpace,
} from "@/api/spaces";
import type { Device } from "@/types/console";
import type {
  AssignedDevice,
  AssignmentHistoryItem,
  AssignmentType,
  Space,
  SpaceTreeNode,
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

export default function SpacesPage() {
  const queryClient = useQueryClient();
  const [selectedSpaceId, setSelectedSpaceId] = useState<string | null>(null);
  const [expandedKeys, setExpandedKeys] = useState<string[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [createOpen, setCreateOpen] = useState(false);
  const [editingSpace, setEditingSpace] = useState<Space | null>(null);
  const [movingSpace, setMovingSpace] = useState<SpaceTreeNode | null>(null);
  const [assignmentDevice, setAssignmentDevice] = useState<Device | null>(null);
  const [historyDeviceId, setHistoryDeviceId] = useState<string | null>(null);

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
