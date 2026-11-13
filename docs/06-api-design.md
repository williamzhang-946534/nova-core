# 06. API 设计

## API 原则

1. 后端 API 以 `/api` 为前缀。
2. REST API 负责查询和命令提交。
3. WebSocket 是事件推送和任务进度的目标设计；Phase 8 Web 控制台先使用认证后的 API 轮询，WebSocket 仍为后续实现。
4. 请求和响应使用 JSON。
5. 列表接口支持分页。
6. 时间使用 UTC ISO-8601。
7. 错误结构统一。
8. OpenAPI 文档由 Pydantic Schema 自动生成。
9. 前端只依赖 API，不直接访问数据库或 Home Assistant。

## 认证

第一阶段使用本地访问控制：

- 后端启动时从环境变量读取 `ARVUNO_API_TOKEN`。
- 除健康检查和登录状态探测外，API 请求必须携带 `Authorization: Bearer <token>`。
- Token 不写入源码。
- 如果服务只绑定 `127.0.0.1`，仍必须启用 Token，避免未来网络配置变化后失去保护。

未来可扩展为多用户和角色权限，但第一阶段只实现单用户。

## 标准响应

### 单对象

```json
{
  "data": {
    "id": "device-uuid",
    "name": "客厅灯"
  }
}
```

### 列表

```json
{
  "data": [
    {
      "id": "device-uuid",
      "name": "客厅灯"
    }
  ],
  "page": 1,
  "page_size": 20,
  "total": 1
}
```

### 错误

```json
{
  "error": {
    "code": "DEVICE_UNAVAILABLE",
    "message": "Device is unavailable.",
    "details": {
      "device_id": "device-uuid"
    },
    "correlation_id": "correlation-uuid"
  }
}
```

不向前端返回堆栈。堆栈和上下文写入服务端日志。

## 常用错误码

| HTTP 状态 | 错误码 | 场景 |
| --- | --- | --- |
| 400 | VALIDATION_ERROR | 请求参数非法 |
| 401 | UNAUTHORIZED | Token 缺失或无效 |
| 403 | PERMISSION_DENIED | 无工具或设备权限 |
| 404 | NOT_FOUND | 资源不存在 |
| 409 | STATE_CONFLICT | 状态不满足执行条件 |
| 422 | TOOL_VALIDATION_ERROR | 工具参数校验失败 |
| 422 | RISK_POLICY_REJECTED | 安全策略拒绝 |
| 428 | CONFIRMATION_REQUIRED | 需要用户确认 |
| 500 | INTERNAL_ERROR | 未分类系统错误 |
| 502 | ADAPTER_ERROR | 设备平台返回错误 |
| 504 | ADAPTER_TIMEOUT | 设备平台超时 |
| 502 | PROVIDER_ERROR | AI 服务错误 |
| 504 | PROVIDER_TIMEOUT | AI 服务超时 |

## 健康检查

### `GET /health`

不需要认证。

响应：

```json
{
  "status": "ok",
  "version": "0.1.0",
  "database": "ok",
  "home_assistant": "connected"
}
```

### `GET /api/system/status`

需要认证。

返回系统概览：

- 后端版本
- 数据库状态
- 当前适配器状态
- 设备数量
- 在线设备数量
- 当前活动任务数量
- 最近错误事件

## 设备 API

Phase 8 已实现设备列表、详情和当前状态查询。设备同步和直接动作提交仍是后续规划，当前 Web 控制台不绕过 `/api/chat` 与 Task System 执行设备控制。

### `GET /api/devices`

查询设备列表。

查询参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| page | integer | 页码 |
| page_size | integer | 每页数量 |
| area | string | 区域过滤 |
| device_type | string | 类型过滤 |
| online | boolean | 在线状态过滤 |
| keyword | string | 名称搜索 |

### `POST /api/devices/sync`

手动触发设备投影同步。同步范围由服务端配置决定，只处理允许 Arvuno 使用的实体类型、区域和实体 ID，不导入 Home Assistant 全部设备、完整配置或历史。

请求：

```json
{
  "adapter_id": "home_assistant"
}
```

响应：

```json
{
  "data": {
    "synced": 24,
    "created": 3,
    "updated": 20,
    "disabled": 1
  }
}
```

### `GET /api/devices/{device_id}`

查询设备详情，包含能力、最近状态和最近事件摘要。

### `GET /api/devices/{device_id}/state`

查询设备当前状态。

响应包含：

- 标准状态
- 标准属性
- 原始状态摘要
- 观察时间
- 是否来自缓存

### `POST /api/devices/{device_id}/actions`

直接从控制台执行设备动作。该接口仍必须经过 Tool System 和 Safety Policy，不允许绕过权限。

请求：

```json
{
  "action": "turn_on",
  "parameters": {},
  "confirm": false
}
```

响应：

```json
{
  "data": {
    "device_id": "device-uuid",
    "action": "turn_on",
    "status": "completed",
    "verified": true,
    "task_id": "task-uuid"
  }
}
```

## 环境状态 API

### `GET /api/environment`

返回当前环境上下文：

- 环境名称
- 区域摘要
- 在线设备数量
- 当前传感器数据
- 异常设备
- 当前活动任务
- 最近事件摘要

### `GET /api/environment/snapshots`

分页查询历史快照。

## 事件 API

### `GET /api/events`

分页查询事件时间线。

查询参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| event_type | string | 事件类型 |
| source | string | 事件来源 |
| subject_id | string | 关联对象 |
| correlation_id | string | 关联 ID |
| start_time | timestamp | 开始时间 |
| end_time | timestamp | 结束时间 |
| page | integer | 页码 |
| page_size | integer | 每页数量 |

### `GET /api/events/{event_id}`

查询事件详情。

## 对话 API

Phase 7 实现最小无状态对话入口；不创建或持久化 Conversation、Message 或 Memory 记录。

### `POST /api/chat`

需要 Bearer Token。

请求：

```json
{
  "message": "打开客厅灯",
  "client_request_id": "client-uuid"
}
```

响应：

```json
{
  "data": {
    "status": "completed",
    "reply": "Device device-uuid is on (verified).",
    "intent": "device_control",
    "task_id": "task-uuid",
    "provider_log_id": "provider-log-uuid",
    "correlation_id": "correlation-uuid",
    "client_request_id": "client-uuid"
  }
}
```

低风险动作被配置为需要确认时，`status` 为 `waiting_confirmation`，响应包含一次性 `confirmation_token` 和确认摘要；后续仍使用任务确认 API。Provider 超时、非法 JSON、非法候选计划、未知工具、非法参数和模型拒绝均返回失败状态，不创建任务或报告成功。

Phase 8 AI 对话页面使用上述最小无状态 `/api/chat` 入口；对话内容不在前端或后端持久化。以下 Conversation API 是后续记忆阶段的规划，尚未实现。

### `GET /api/conversations`

查询对话列表。

### `POST /api/conversations`

创建对话。

### `GET /api/conversations/{conversation_id}/messages`

查询对话消息。

### `POST /api/conversations/{conversation_id}/messages`

发送用户消息。

请求：

```json
{
  "content": "打开客厅灯",
  "client_request_id": "client-uuid"
}
```

响应：

```json
{
  "data": {
    "message_id": "message-uuid",
    "conversation_id": "conversation-uuid",
    "task_id": "task-uuid",
    "status": "completed",
    "reply": "已打开客厅灯，并确认设备状态为开启。"
  }
}
```

如果任务需要确认，返回 `waiting_confirmation` 和确认所需信息。

## 任务 API

### `GET /api/tasks`

分页查询任务。

查询参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| status | string | 任务状态 |
| task_type | string | 任务类型 |
| conversation_id | string | 对话 ID |
| start_time | timestamp | 开始时间 |
| end_time | timestamp | 结束时间 |

### `GET /api/tasks/{task_id}`

查询任务详情，包含步骤、工具调用、验证结果和错误。

### `POST /api/tasks/{task_id}/confirm`

确认等待确认的任务。

请求：

```json
{
  "confirmed": true,
  "confirmation_token": "task-token"
}
```

### `POST /api/tasks/{task_id}/cancel`

取消任务。

## 工具 API

### `GET /api/tools`

查询已启用工具。

响应包含：

- 工具名称
- 描述
- 输入 Schema
- 风险等级
- 是否需要确认

### `POST /api/tools/{tool_name}/execute`

调试执行工具。该接口不得绕过权限，只应作为开发期可控入口。

请求：

```json
{
  "input": {
    "device_id": "device-uuid"
  },
  "confirm": true,
  "task_id": "task-uuid"
}
```

## Robot API

Robot API 受 API Token 认证保护。它只暴露状态、能力、授权、治理、机器人事件和任务历史；当前不提供直接物理动作入口。

### `GET /api/robots`

返回机器人列表。`enabled_only=true` 只返回已启用记录。

### `GET /api/robots/{robot_id}`

返回注册事实、连接状态、运动安全状态、急停 / 人工接管标记、电池、设备状态、位置和最近活动时间。

### `GET /api/robots/{robot_id}/capabilities`

返回按 Robot Profile 过滤后的能力目录。每项包含硬件事实 `discovered`、`supported`、`verification_status` 和安全 Schema，也包含治理状态 `enabled`、`approved`、`consent_granted` 与派生状态 `executable`。`runtime_enabled` 当前作为 `executable` 的兼容字段返回。

`desktop_robot` 只声明 `report_status`、`look_at`、`observe_scene`、`request_safe_stop`、`enter_idle_pose`、`speak` 和 `listen`，不返回 `navigate_to`、`return_to_dock` 或 `charge`。`mobile_robot` 保留未来能力目录，但治理在硬件安全审批前保持拒绝。

### `POST /api/robots/{robot_id}/capabilities/{capability}/governance`

更新用户批准的启用状态。请求：

```json
{"enabled": true}
```

Adapter 发现结果不会覆盖用户批准状态；`executable` 仍然要求 discovered、supported、enabled、approved、有效 Consent 和运行时安全条件同时满足。

### `GET /api/robots/{robot_id}/consents`

查询机器人 Consent。支持 `capability` 和 `active_only` 过滤。授权按 `capability` 与 `data_category` 管理，可绑定 `space_id`，记录授予、过期和撤销时间。

### `POST /api/robots/{robot_id}/consents`

授予单项 Consent。请求至少包含 `capability` 和 `data_category`，可选 `space_id`、`expires_at`、`grant_source` 和 `granted_by`。摄像头、麦克风、扬声器、空间活动和物理运动不共用宽泛授权。

### `POST /api/robots/{robot_id}/consents/{consent_id}/revoke`

撤销指定 Consent，返回带 `revoked_at` 的授权记录。

### `GET /api/robots/{robot_id}/state`

查询最后一次保存的机器人状态投影。

### `GET /api/robots/{robot_id}/runtime-state`

查询运行时状态。响应包含 `online | offline | stale | busy | idle | error | emergency_stopped | unknown`、连接状态、运动安全状态、`is_fresh`、`last_seen_at`、心跳超时和活动任务数。过期状态必须显式暴露为 `stale` 或 `unknown`，不得当作实时空闲状态。

### `POST /api/robots/{robot_id}/heartbeat`

接收机器人心跳和状态报告。该接口更新 freshness、安全状态、电池、设备状态和位置，不是物理动作执行入口。

### `POST /api/robots/{robot_id}/reconnect`

请求重新同步机器人连接和真实状态。该接口只执行连接恢复与状态核对，不创建或恢复物理动作任务。

### `GET /api/robots/{robot_id}/events`

查询机器人事件，支持 `task_request_id` 与 `limit` 过滤。事件类型包含连接、状态、安全和任务状态变化。

### `GET /api/robots/task-requests/{request_id}`

查询单个机器人任务请求及其 `task_id`、`task_step_id`、`tool_execution_id` 和 `correlation_id`。

### `GET /api/robots/{robot_id}/task-requests`

查询机器人任务历史，支持 `status` 与 `limit` 过滤。

### 锁定的机器人执行入口

以下入口临时保留兼容路径，但当前不调用 `RobotApplicationService` 执行物理动作：

- `POST /api/robots/{robot_id}/enable`
- `POST /api/robots/{robot_id}/task-requests`
- `POST /api/robots/task-requests/{request_id}/confirm`
- `POST /api/robots/task-requests/{request_id}/cancel`

它们统一返回 `403` 结构化错误：

```json
{
  "error": {
    "code": "ROBOT_EXECUTION_LOCKED",
    "message": "Robot execution is locked until the unified safety chain is available.",
    "details": {
      "required_boundary": "task_system+tool_registry+safety_policy+tool_executor",
      "temporary_lock": true
    }
  }
}
```

机器人能力启用不是物理执行；真实动作必须进入 Task System、Tool Registry、Safety Policy、用户确认、Tool Executor、Robot Adapter、状态验证和 Execution Record 组成的统一安全链。

## Robot 移动感知 API

### `POST /api/robot-perception/requests/evaluate`

评估一次主动感知候选。该评估不创建机器人物理任务。

### `POST /api/robot-perception/requests/{request_id}/authorize`

记录导航和摄像头授权候选。授权结果本身不触发物理动作。

### `POST /api/robot-perception/requests/{request_id}/execute`

当前直接拒绝，返回 `ROBOT_EXECUTION_LOCKED`。移动观察的真实执行必须等待统一安全链和硬件安全审批。

### `GET /api/robot-perception/requests/{request_id}`

查询感知请求状态、授权作用域和执行追踪。

## Retention API

Retention API 受认证保护，用于运维观察和手动清理；普通用户请求不应触发高频清理。

### `GET /api/retention/policies`

返回六个独立任务策略：`event`、`observation`、`multimodal_media`、`proactive`、`environment_snapshot` 和 `provider_log`。每项包含 `enabled`、`interval_seconds`、`batch_size` 和业务清理规则。

### `GET /api/retention/status`

返回 `single_process_only: true`、每个任务的下次执行时间、最近执行结果和失败信息。当前调度器是应用内单进程调度，不声明多进程分布式协调能力。

### `GET /api/retention/failures`

查询失败记录，`limit` 限制在 1 到 200。

### `POST /api/retention/run`

手动执行已启用任务。请求体可为空；提供 `jobs` 时必须去重且任务必须启用。手动触发有服务端冷却窗口，重复触发返回 `409`；同一任务运行中同样返回 `409`。所有时间计算使用 UTC。

## 自动化 API

以下接口只管理少量需要 Arvuno 上下文的规则，不提供通用自动化编辑器、场景系统或 Home Assistant 自动化迁移功能。

### `GET /api/automations`

查询自动化规则。支持 `enabled`、`page`、`page_size` 参数，返回 `data/page/page_size/total` 分页结构。

### `POST /api/automations`

创建规则。

请求：

```json
{
  "name": "高温提醒",
  "description": "客厅温度超过阈值时提醒",
  "enabled": true,
  "trigger": {
    "event_type": "sensor_updated",
    "subject_id": "device-uuid"
  },
  "conditions": [
    {
      "field": "payload.temperature",
      "operator": "gt",
      "value": 28
    }
  ],
  "action": {
    "type": "notification",
    "title": "温度过高",
    "message": "当前温度过高"
  },
  "cooldown_seconds": 600
}
```

`event_type` 仅允许 `device_state_changed`、`sensor_updated`、`device_unavailable`。条件操作符仅允许 `eq`、`ne`、`gt`、`gte`、`lt`、`lte`、`contains`、`in`，多个条件按 AND 评估。通知动作可包含 `level: info | warning | error`；工具动作必须包含 `tool_name`、`input`、`title` 和 `risk_level`。

### `GET /api/automations/{automation_id}`

查询规则详情。

### `PATCH /api/automations/{automation_id}`

更新规则。支持修改 `name`、`description`、`enabled`、`trigger`、`conditions`、`action` 和 `cooldown_seconds`。

### `POST /api/automations/{automation_id}/enable`

启用规则。

### `POST /api/automations/{automation_id}/disable`

停用规则。

### `GET /api/automations/{automation_id}/runs`

查询规则执行历史。Run 状态为 `running | completed | failed | waiting_confirmation | needs_verification | cancelled | cooldown_skipped | condition_not_met | risk_rejected`，记录包含触发事件、命中上下文、任务 ID、通知 ID 和错误结构。

### `GET /api/notifications`

查询 Web Console 站内通知。支持 `level`、`unread_only`、`page`、`page_size` 参数。

### `POST /api/notifications/{notification_id}/read`

将站内通知标记为已读。

## 设置 API

### `GET /api/settings`

查询非敏感系统配置。Phase 8 返回运行环境摘要、AI Provider 类型、Home Assistant 连接/写开关状态、设备轮询间隔、事件保留策略和 Web Console 偏好；不返回 API Key、Token 或其他敏感值。

### `PATCH /api/settings`

更新非敏感配置。Phase 8 仅允许更新：

```json
{
  "web_console": {
    "event_poll_interval_seconds": 10
  }
}
```

敏感配置只能通过环境变量或本地受保护配置文件修改，不允许通过 API 明文读取。

## WebSocket

Phase 8 未实现 WebSocket。Web 控制台当前通过 TanStack Query 按服务端保存的 `web_console.event_poll_interval_seconds` 轮询事件、任务和概览 API；以下接口保留为后续设计。

### `WS /ws/events`

认证后订阅事件。

连接消息：

```json
{
  "type": "subscribe",
  "filters": {
    "event_types": ["device_state_changed", "task_completed"]
  }
}
```

推送消息：

```json
{
  "type": "event",
  "data": {
    "id": "event-uuid",
    "event_type": "device_state_changed",
    "source": "home_assistant",
    "occurred_at": "2026-10-26T10:00:00Z",
    "payload": {}
  }
}
```

### `WS /ws/tasks`

订阅任务状态和步骤进度。

## 分页规范

| 参数 | 默认 | 最大 |
| --- | --- | --- |
| page | 1 | - |
| page_size | 20 | 100 |

排序默认按时间倒序，必要时提供 `sort` 参数。

## 幂等性

以下操作必须支持幂等：

- 创建对话消息：`client_request_id`
- 执行工具：`execution_request_id`
- 确认任务：`confirmation_token`

幂等键用于避免前端重试造成重复设备控制。

## API 版本

第一阶段路径为 `/api`。如果未来出现破坏性变更，使用 `/api/v2`，旧版本保留过渡期。

## 前端页面与 API 映射

| 页面 | 主要 API |
| --- | --- |
| 系统概览 | `/api/system/status`、`/api/environment` |
| 设备列表 | `/api/devices` |
| 设备详情 | `/api/devices/{id}`、`/api/devices/{id}/state`、`/api/events` |
| 环境状态 | `/api/environment` |
| 事件时间线 | `/api/events`、`/ws/events` |
| AI 对话 | `/api/chat` |
| 任务记录 | `/api/tasks`、`/api/tasks/{id}` |
| 自动化 | `/api/automations`、`/api/automations/{id}/runs` |
| 通知 | `/api/notifications` |
| 机器人管理 | `/api/robots`、`/api/robots/{id}/capabilities`、`/api/robots/{id}/consents`、`/api/robots/{id}/task-requests`、`/api/robots/{id}/events` |
| 系统设置 | `/api/settings` |
| 数据保留运维 | `/api/retention/policies`、`/api/retention/status`、`/api/retention/failures`、`/api/retention/run` |

Phase 8 事件时间线仅使用 `/api/events` 轮询；Phase 9 已提供自动化和站内通知 API。WebSocket 推送与 Conversation API 尚未实现。

## API 安全要求

1. 所有非公开接口必须认证。
2. 写操作必须记录 correlation ID。
3. 高风险操作返回 `CONFIRMATION_REQUIRED` 或拒绝。
4. API 不得暴露 API Key。
5. 设备动作必须通过统一工具执行链路。
6. 机器人物理动作必须通过统一机器人安全执行链路；直接 Robot API 写入口返回 `ROBOT_EXECUTION_LOCKED`。
7. `confirmed=true` 不是机器人确认凭据。确认必须使用服务端签发、绑定 robot/request/能力/参数摘要/空间范围并只能单次使用的 Token。
8. 前端调试工具接口在生产模式下应默认关闭或严格限制。
