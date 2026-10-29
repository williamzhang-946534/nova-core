# 08. 事件系统设计

## 目标

Event System 为 Arvuno 提供统一的事件表示、分发、持久化和查询能力。它连接配置范围内的设备状态、环境上下文、任务执行、自动化规则和 Web 控制台，不复制 Home Assistant 完整事件历史。

第一阶段使用应用内事件总线，不引入 Kafka、RabbitMQ 或云消息服务。

## Event Schema

```json
{
  "id": "event-uuid",
  "event_type": "device_state_changed",
  "source": "home_assistant",
  "subject_type": "device",
  "subject_id": "device-uuid",
  "payload": {
    "previous_state": "off",
    "current_state": "on",
    "attributes": {
      "brightness": 80
    }
  },
  "correlation_id": "correlation-uuid",
  "occurred_at": "2026-10-26T10:00:00Z",
  "created_at": "2026-10-26T10:00:01Z"
}
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| id | 是 | UUID，由 Arvuno 生成 |
| event_type | 是 | 标准事件类型 |
| source | 是 | 事件来源 |
| subject_type | 否 | 关联对象类型 |
| subject_id | 否 | 关联对象 ID |
| payload | 是 | 事件内容，结构由 event_type 决定 |
| correlation_id | 否 | 贯穿请求、任务和工具执行的关联 ID |
| occurred_at | 是 | 事件发生时间，UTC |
| created_at | 是 | Arvuno 写入时间，UTC |

## 标准事件类型

### `device_state_changed`

设备状态发生明显变化。

Payload：

| 字段 | 说明 |
| --- | --- |
| device_id | Arvuno 设备 ID |
| previous_state | 前状态 |
| current_state | 当前状态 |
| attributes | 标准化属性 |

### `sensor_updated`

传感器读数更新。

Payload：

| 字段 | 说明 |
| --- | --- |
| device_id | 传感器 ID |
| sensor_type | 温度、湿度、人体、门窗等 |
| value | 当前值 |
| unit | 单位 |
| previous_value | 前值 |

### `device_unavailable`

设备不可用或离线。

Payload：

| 字段 | 说明 |
| --- | --- |
| device_id | 设备 ID |
| reason | 原因摘要 |
| observed_state | 平台观察状态 |

### `automation_triggered`

自动化规则命中。

Payload：

| 字段 | 说明 |
| --- | --- |
| automation_id | 规则 ID |
| trigger_event_id | 触发事件 ID |
| matched_conditions | 命中条件 |

### `task_started`

任务开始执行。

Payload：

| 字段 | 说明 |
| --- | --- |
| task_id | 任务 ID |
| task_type | 任务类型 |
| origin | 任务来源 |

### `task_completed`

任务完成。

Payload：

| 字段 | 说明 |
| --- | --- |
| task_id | 任务 ID |
| result_summary | 结果摘要 |
| completed_at | 完成时间 |

### `task_failed`

任务失败。

Payload：

| 字段 | 说明 |
| --- | --- |
| task_id | 任务 ID |
| error_code | 错误码 |
| error_message | 错误说明 |
| failed_step_id | 失败步骤 |

### `tool_executed`

工具执行完成，无论成功失败。

Payload：

| 字段 | 说明 |
| --- | --- |
| tool_name | 工具名 |
| tool_execution_id | 执行 ID |
| status | 成功或失败 |
| risk_level | 风险等级 |
| verified | 是否验证通过 |

### `user_confirmed`

用户确认高风险或需确认操作。

Payload：

| 字段 | 说明 |
| --- | --- |
| task_id | 任务 ID |
| confirmed | 是否确认 |
| confirmation_token_hash | 确认令牌摘要 |

## 事件来源

| Source | 说明 |
| --- | --- |
| `home_assistant` | Home Assistant Adapter |
| `mock_adapter` | Mock Device Adapter |
| `agent` | Agent Runtime |
| `task` | Task System |
| `tool` | Tool System |
| `automation` | Automation Engine |
| `api` | API Layer |
| `system` | 系统组件 |

## 应用内事件总线

### 接口

```python
class EventBus(Protocol):
    async def publish(self, event: ArvunoEvent) -> None: ...

    def subscribe(
        self,
        handler: EventHandler,
        event_types: set[str] | None = None,
    ) -> SubscriptionHandle: ...
```

### 处理原则

1. 外部设备事件先持久化，再分发给订阅者。
2. 单个订阅者异常不影响其他订阅者。
3. 订阅者异常必须记录日志，并保留事件。
4. 事件处理不能无限递归，必须设置递归深度限制。
5. 事件总线不做业务决策，只负责分发。
6. 同步订阅者用于更新 Environment Context，异步订阅者用于通知、自动化和日志扩展。

## 事件写入流程

```text
Device Adapter / Task / Tool / Automation
→ 构造 ArvunoEvent
→ Pydantic 校验
→ 写入 events 表
→ Event Bus 分发
→ Environment Context / Automation / WebSocket / Notification
```

如果数据库写入失败：

- 对外部输入事件记录错误日志。
- 不执行依赖该事件的自动化。
- API 或任务调用返回存储失败错误。
- 系统不得假装事件已成功记录。

## 事件订阅

### Environment Context

订阅：

- `device_state_changed`
- `sensor_updated`
- `device_unavailable`
- `task_started`
- `task_completed`
- `task_failed`

职责是更新当前环境摘要。

### Automation Engine

订阅：

- `device_state_changed`
- `sensor_updated`
- `device_unavailable`

职责是评估规则。

### WebSocket Gateway

订阅：

- 前端指定的事件类型。

职责是推送实时时间线。

### Notification

订阅：

- `task_failed`

职责是生成任务失败通知。自动化规则中的普通通知动作由 Automation Service 在规则执行时直接写入 Web Console 通知记录；`device_unavailable` 提醒仍需要显式配置对应自动化规则，不会默认给每个离线事件发送通知。

## Correlation ID

correlation ID 用于串起完整执行链：

```text
用户消息
→ conversation message
→ task
→ task step
→ tool execution
→ adapter action
→ state verification
→ task result event
```

规则：

1. API 收到用户请求后生成或继承 correlation ID。
2. Task 创建时保存。
3. Tool Execution 保存。
4. Adapter 调用日志保存。
5. 相关事件尽量携带。
6. 错误响应返回。

## 时间语义

| 时间 | 含义 |
| --- | --- |
| occurred_at | 事件在现实世界或来源系统发生的时间 |
| created_at | Arvuno 写入事件的时间 |

两者都必须使用 UTC。排序默认使用 `occurred_at`，必要时可用 `created_at` 排查处理延迟。

## 事件与状态快照

事件表示变化，状态快照表示观察结果。

```text
Event：客厅灯从 off 变为 on
Snapshot：客厅灯在 10:00:01 状态为 on，亮度 80
```

Environment Context 使用最新状态，历史查询使用事件和快照。

## 事件查询

支持：

- 按事件类型
- 按来源
- 按设备或对象
- 按时间范围
- 按任务 correlation ID
- 分页和排序

## 事件保留与清理

默认策略：

| 事件 | 保留 |
| --- | --- |
| 设备和传感器事件 | 180 天 |
| 任务事件 | 长期保留 |
| 工具执行事件 | 长期保留 |
| 自动化触发事件 | 180 天 |
| 系统诊断事件 | 90 天 |

清理任务必须在低负载时间执行，并记录清理结果。

## 可靠性边界

第一阶段应用内总线不提供跨进程持久队列。因此：

- 进程崩溃时，尚未写入数据库的事件可能丢失。
- 已写入数据库的事件不会因为订阅者失败而丢失。
- Home Assistant Adapter 重连后应对配置范围内实体做当前状态对账，减少事件丢失影响，不回放完整历史。

这是第一阶段可接受的取舍。未来如需严格事件投递，再评估持久队列或事件回放机制。

## 测试要求

1. Event Schema 字段校验。
2. payload 按 event_type 校验。
3. 事件持久化成功。
4. 数据库失败时不误报成功。
5. 单个订阅者异常不影响其他订阅者。
6. 事件过滤正确。
7. correlation ID 正确传播。
8. 时间排序正确。
9. 自动化触发和事件记录一致。
10. WebSocket 收到推送。

## 未来扩展

1. 事件回放服务。
2. 更复杂的订阅过滤表达式。
3. 事件归档到独立存储。
4. 外部消息队列适配。
5. 语音、视觉和机器人事件类型。

这些能力第一阶段只保留事件类型和 payload 校验的可扩展性，不预留语音、视觉或机器人事件类型，也不提前实现基础设施。
