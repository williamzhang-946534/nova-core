# 05. 数据模型

## 设计原则

1. 数据库模型服务于 Arvuno 领域，不复制 Home Assistant 内部结构。
2. `devices` 是 Home Assistant 实体的轻量投影，不是完整设备注册表。只保存 Arvuno 需要的名称、区域、类型、能力摘要、别名和权限等信息。
3. 不复制 Home Assistant 的完整设备配置、协议元数据、设备发现结果或完整历史。
4. `events` 只保存 Arvuno 上下文、任务、工具、审计和自动化所需事件，不是 Home Assistant 历史库的副本。
5. `automations` 只建模少量需要 Arvuno 上下文的规则，不是通用自动化平台模型。
6. API Schema、领域模型和数据库模型分离。
7. 所有主键使用 UUID 字符串，便于未来分布式或迁移。
8. 时间统一使用 UTC ISO-8601 字符串。
9. 变化快的数据使用快照表，当前状态使用摘要表。
10. 事件 payload 和工具参数使用 JSON 字段，但必须由 Pydantic 校验。
11. 不引入向量数据库，长期记忆先用结构化字段和关键词/时间查询。
12. 业务逻辑不直接依赖 SQLite 特有能力。

## ER 总览

```mermaid
erDiagram
    DEVICE ||--o{ DEVICE_STATE : has
    DEVICE ||--o{ DEVICE_CAPABILITY : has
    DEVICE ||--o{ EVENT : produces
    ENVIRONMENT ||--o{ ENVIRONMENT_SNAPSHOT : snapshots
    CONVERSATION ||--o{ CONVERSATION_MESSAGE : contains
    CONVERSATION ||--o{ TASK : creates
    TASK ||--o{ TASK_STEP : contains
    TASK_STEP ||--o{ TOOL_EXECUTION : executes
    TOOL ||--o{ TOOL_EXECUTION : invoked_by
    AUTOMATION ||--o{ AUTOMATION_RUN : triggers
    EVENT ||--o{ AUTOMATION_RUN : evaluates
```

## 表结构

### 1. `devices`

设备投影表，保存 Arvuno 需要的稳定设备信息。设备发现、完整注册信息、协议配置和完整历史仍由 Home Assistant 管理。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID PK | Arvuno 设备 ID |
| adapter_id | string | 适配器 ID，例如 `home_assistant`、`mock` |
| external_id | string | 平台内实体或设备 ID |
| name | string | 展示名称 |
| normalized_name | string | 标准化名称，用于匹配 |
| device_type | string | Arvuno 标准设备类型 |
| area | string nullable | 区域，例如客厅 |
| manufacturer | string nullable | 厂商 |
| model | string nullable | 型号 |
| is_online | boolean | 最近一次已知在线状态 |
| is_enabled | boolean | 是否允许 Arvuno 使用 |
| risk_level | string | 默认风险等级 |
| capabilities | JSON | 能力描述 |
| metadata | JSON | 适配器原始元数据摘要 |
| last_seen_at | timestamp nullable | 最近更新时间 |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

唯一约束：`(adapter_id, external_id)`。

### 2. `device_states`

设备状态快照，用于 Arvuno 的短期上下文、任务验证和问题排查。只保存已配置纳入 Arvuno 的实体，不替代 Home Assistant 历史记录。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID PK | 快照 ID |
| device_id | UUID FK | 设备 ID |
| state | string | 标准状态 |
| attributes | JSON | 标准化属性 |
| raw_state | string nullable | 平台原始状态 |
| source | string | 来源 |
| observed_at | timestamp | 状态观察时间 |
| created_at | timestamp | 写入时间 |

### 3. `device_capabilities`

设备能力描述。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID PK | 能力 ID |
| device_id | UUID FK | 设备 ID |
| capability | string | 能力类型，例如 `switch`、`light`、`sensor` |
| supported_actions | JSON | 支持动作 |
| parameters | JSON | 参数 Schema |
| risk_level | string | 动作风险 |
| requires_confirmation | boolean | 是否需要确认 |
| enabled | boolean | 是否启用 |
| created_at | timestamp | 创建时间 |

### 4. `environments`

环境定义，第一阶段可以是默认环境 `home`。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID PK | 环境 ID |
| name | string | 环境名称 |
| description | string nullable | 描述 |
| is_default | boolean | 是否默认环境 |
| created_at | timestamp | 创建时间 |

### 5. `environment_snapshots`

环境上下文快照。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID PK | 快照 ID |
| environment_id | UUID FK | 环境 ID |
| context | JSON | 设备、传感器、区域和任务摘要 |
| active_task_ids | JSON | 当前活动任务 |
| anomaly_count | integer | 异常数量 |
| created_at | timestamp | 快照时间 |

当前状态可以由最新快照或缓存对象提供，历史快照用于回放和排查。

### 6. `events`

Arvuno 领域事件表，只保存上下文、任务、工具、审计和自动化所需事件。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID PK | Event ID |
| event_type | string | 事件类型 |
| source | string | 事件来源 |
| subject_type | string nullable | 关联对象类型 |
| subject_id | string nullable | 关联对象 ID |
| payload | JSON | 事件内容 |
| correlation_id | string nullable | 关联 ID |
| occurred_at | timestamp | 事件发生时间 |
| created_at | timestamp | 写入时间 |

索引：

- `(event_type, occurred_at)`
- `(subject_type, subject_id, occurred_at)`
- `(correlation_id)`

### 7. `conversations`

AI 对话。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID PK | 对话 ID |
| title | string | 对话标题 |
| status | string | active / archived |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

### 8. `conversation_messages`

对话消息。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID PK | 消息 ID |
| conversation_id | UUID FK | 对话 ID |
| role | string | user / assistant / system / tool |
| content | text | 文本内容 |
| structured_data | JSON nullable | 结构化输出 |
| provider_log_id | UUID nullable | 模型调用日志 |
| correlation_id | string nullable | 关联 ID |
| created_at | timestamp | 创建时间 |

### 9. `tasks`

任务记录。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID PK | 任务 ID |
| task_type | string | 任务类型 |
| title | string | 标题 |
| description | string nullable | 描述 |
| status | string | 任务状态 |
| origin | string | 用户 / Agent / Automation / System |
| conversation_id | UUID nullable | 对话 ID |
| plan | JSON | 任务计划 |
| result | JSON nullable | 任务结果 |
| error | JSON nullable | 错误信息 |
| correlation_id | string nullable | 关联 ID |
| created_at | timestamp | 创建时间 |
| started_at | timestamp nullable | 开始时间 |
| completed_at | timestamp nullable | 完成时间 |

### 10. `task_steps`

任务步骤。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID PK | 步骤 ID |
| task_id | UUID FK | 任务 ID |
| step_index | integer | 步骤序号 |
| name | string | 步骤名称 |
| description | string nullable | 描述 |
| tool_name | string nullable | 工具名称 |
| status | string | 步骤状态 |
| input | JSON nullable | 输入 |
| output | JSON nullable | 输出 |
| error | JSON nullable | 错误 |
| started_at | timestamp nullable | 开始时间 |
| completed_at | timestamp nullable | 完成时间 |

### 11. `tools`

工具注册表。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID PK | 工具 ID |
| name | string unique | 工具名 |
| version | string | 工具版本 |
| description | string | 描述 |
| category | string | 类别 |
| input_schema | JSON | 输入 Schema |
| output_schema | JSON | 输出 Schema |
| risk_level | string | 风险等级 |
| default_permission | string | 默认权限 |
| requires_confirmation | boolean | 是否需要确认 |
| enabled | boolean | 是否启用 |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

### 12. `tool_executions`

工具执行记录。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID PK | 执行 ID |
| tool_id | UUID FK | 工具 ID |
| task_id | UUID nullable | 任务 ID |
| task_step_id | UUID nullable | 步骤 ID |
| status | string | 执行状态 |
| input | JSON | 已验证输入 |
| output | JSON nullable | 输出 |
| validation | JSON nullable | 结果验证 |
| risk_level | string | 风险等级 |
| permission_result | string | 权限结果 |
| error | JSON nullable | 错误 |
| correlation_id | string nullable | 关联 ID |
| started_at | timestamp | 开始时间 |
| completed_at | timestamp nullable | 完成时间 |
| duration_ms | integer nullable | 耗时 |

### 13. `provider_logs`

AI 模型调用日志。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID PK | 调用 ID |
| provider | string | Provider 名称 |
| model | string | 模型名 |
| request_kind | string | chat / structured / tools |
| input_summary | JSON | 脱敏输入摘要 |
| output_summary | JSON | 脱敏输出摘要 |
| status | string | 成功或失败 |
| error | JSON nullable | 错误 |
| latency_ms | integer nullable | 耗时 |
| prompt_tokens | integer nullable | 输入 Token |
| completion_tokens | integer nullable | 输出 Token |
| created_at | timestamp | 创建时间 |

### 14. `user_preferences`

用户偏好。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID PK | 偏好 ID |
| key | string unique | 偏好键 |
| value | JSON | 偏好值 |
| category | string | 类别 |
| description | string nullable | 描述 |
| source | string | 来源 |
| confirmed | boolean | 用户是否确认 |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

### 15. `memories`

长期记忆与任务经验。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID PK | 记忆 ID |
| memory_type | string | preference / task / event / fact |
| title | string | 标题 |
| content | text | 内容 |
| summary | text nullable | 摘要 |
| keywords | JSON | 关键词 |
| importance | integer | 重要性 |
| source_type | string | 来源类型 |
| source_id | string nullable | 来源 ID |
| user_confirmed | boolean | 用户确认 |
| expires_at | timestamp nullable | 过期时间 |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

### 16. `automations`

Arvuno 上下文自动化规则。普通定时、状态触发和场景自动化优先由 Home Assistant 提供，本表不做通用自动化平台模型。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID PK | 规则 ID |
| name | string | 规则名 |
| description | string nullable | 描述 |
| enabled | boolean | 是否启用 |
| trigger | JSON | 触发条件 |
| condition | JSON | 附加条件列表，API 模型名为 `conditions`，应用层按 AND 评估 |
| action | JSON | 执行动作 |
| cooldown_seconds | integer | 冷却时间 |
| risk_level | string | 动作风险等级，通知动作固定为 `read_only`，工具动作来自配置 |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

### 17. `automation_runs`

自动化执行记录。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID PK | 执行 ID |
| automation_id | UUID FK | 规则 ID |
| event_id | UUID nullable | 触发事件 |
| status | string | 执行状态 |
| matched_context | JSON | 命中上下文 |
| task_id | UUID nullable | 创建的任务 |
| notification_id | string nullable | 通知动作生成的通知 ID；当前从 `matched_context.notification_id` 还原，不单独建列 |
| error | JSON nullable | 错误 |
| started_at | timestamp | 开始时间 |
| completed_at | timestamp nullable | 完成时间 |

### 18. `system_settings`

系统配置。敏感信息只保存引用或本地加密值，不保存明文 API Key。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID PK | 配置 ID |
| key | string unique | 配置键 |
| value | JSON | 配置值 |
| value_type | string | 类型 |
| is_secret | boolean | 是否敏感 |
| description | string nullable | 描述 |
| updated_at | timestamp | 更新时间 |

API Key、Home Assistant Token 等优先从环境变量读取，数据库中只保存配置状态或脱敏摘要。

### 19. `notifications`

通知记录。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | UUID PK | 通知 ID |
| channel | string | 通知渠道 |
| title | string | 标题 |
| content | text | 内容 |
| level | string | 级别 |
| status | string | 发送状态 |
| related_event_id | UUID nullable | 关联事件 |
| related_task_id | UUID nullable | 关联任务 |
| created_at | timestamp | 创建时间 |
| sent_at | timestamp nullable | 发送时间 |

## 任务状态机

```text
pending
  → planning
  → waiting_confirmation
  → running
  → completed

planning → failed
running → failed
waiting_confirmation → cancelled
running → cancelled
```

状态说明：

| 状态 | 含义 |
| --- | --- |
| pending | 已创建，尚未规划 |
| planning | 正在生成计划 |
| waiting_confirmation | 等待用户确认 |
| running | 正在执行 |
| completed | 成功完成 |
| failed | 执行失败 |
| cancelled | 已取消 |

## 自动化执行状态机

```text
condition_not_met
cooldown_skipped
risk_rejected

running → completed
running → failed
```

状态说明：

| 状态 | 含义 |
| --- | --- |
| running | 条件与风险检查通过，动作正在执行 |
| completed | 通知已生成，或自动化任务成功完成 |
| failed | 动作或任务执行失败 |
| cooldown_skipped | 规则命中但处于冷却期 |
| condition_not_met | 触发事件匹配但附加条件不满足 |
| risk_rejected | 工具动作风险高于 `low_risk`，在任务创建前拒绝 |

## 事件类型

| 事件类型 | 说明 |
| --- | --- |
| device_state_changed | 设备状态变化 |
| sensor_updated | 传感器数据更新 |
| device_unavailable | 设备不可用 |
| automation_triggered | 自动化触发 |
| task_started | 任务开始 |
| task_completed | 任务完成 |
| task_failed | 任务失败 |
| tool_executed | 工具执行完成 |
| user_confirmed | 用户确认 |

## 数据保留策略

| 数据 | 保留策略 |
| --- | --- |
| 当前设备状态 | 保留最新状态 |
| 设备状态快照 | 默认保留 30 天，可配置 |
| 事件记录 | 默认保留 180 天，可配置 |
| 对话记录 | 用户可选择保留或归档 |
| 任务记录 | 长期保留 |
| 工具执行记录 | 长期保留 |
| Provider 日志 | 默认保留 90 天，内容脱敏 |
| 用户偏好 | 长期保留，可编辑和删除 |
| 长期记忆 | 用户确认后保留，可删除 |

## 备份方案

第一阶段使用 SQLite 文件备份：

1. 停止或短暂暂停写入。
2. 使用 SQLite backup API 或导出快照。
3. 备份文件写入 `backups/`。
4. 保留最近 N 份备份。
5. 每次数据库迁移前强制备份。

备份目录不提交到 Git。

## 迁移原则

1. 所有表结构变更通过 Alembic 管理。
2. 迁移前自动备份数据库。
3. 破坏性迁移必须提供回滚说明。
4. 迁移脚本不得包含业务逻辑。
5. 每次迁移必须有对应测试。

## PostgreSQL 迁移预留

为保持迁移能力：

- 使用 UUID 字符串，不使用 SQLite 自增整数作为业务 ID。
- JSON 字段结构在应用层严格校验。
- 时间统一 UTC。
- 不使用 SQLite 专属函数。
- 不依赖大小写不敏感的隐式行为。

第一阶段不部署 PostgreSQL。
