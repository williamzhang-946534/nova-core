# 23. ARS-02 Migration、API、隐私与性能设计

- 阶段：`ARS-02.0：架构设计与数据契约冻结`
- 日期：2026-11-02
- 状态：设计完成，等待用户确认；本文不是已实现行为
- 范围：现有数据库迁移、模块边界、API 草案、只读 Tool、前端展示、保留策略、隐私和 SQLite 性能
- 禁止事项：本文不修改业务代码、数据库迁移、API、依赖或前端页面

## 1. 目标模块依赖图

```text
┌───────────────────────────── Web Console ─────────────────────────────┐
│ Space Tree / Room State / Coverage / Observation Quality / Provenance │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │ HTTPS + existing auth
┌──────────────────────────────────▼───────────────────────────────────┐
│ FastAPI routers                                                     │
│ spaces / entities / observations / state estimates / context v2      │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │ service boundary
┌──────────────────────────────────▼───────────────────────────────────┐
│ Spatial Service │ Observation Pipeline │ Estimation Service │ Context │
└───────┬────────────────┴─────────┬────────────┴────────────┬─────────┘
        │                        │                         │
┌───────▼────────────────────────▼─────────────────────────▼─────────┐
│ Repositories: spaces / entities / observations / estimates          │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ SQLAlchemy / Alembic
                               SQLite DB

Device Adapter（HA / Mock）
  → Observation Pipeline
  → Observation Repository

Observation Pipeline
  → Current Estimate Read Model
  → Environment Context v2

Estimation Service
  → reads Observation Repository + Spatial Repository
  → writes estimate history + current estimate read model

Agent Runtime
  → Tool Executor
  → Tool Registry / Safety Policy
  → Read-only Environment Tool
  → Environment Query Service
```

依赖硬边界：

1. Agent Runtime 不直接访问 Repository、数据库、Adapter 或系统命令。
2. Device Adapter 不写数据库，只输出来源数据。
3. Observation Pipeline 是观测入库唯一入口。
4. Estimation Service 读取 Observation 和 Spatial Model，写估计历史和当前读模型。
5. Environment Context v2 只读当前估计，不计算融合结果。
6. Event Service 只发布重要变化，不是观测或估计事实源。
7. API 和前端不解析 `device_states.attributes` 作为世界模型。

## 2. 现有数据库审查

### 2.1 `devices`

现状：接入设备身份，包含 `adapter_id + external_id`、名称、`device_type`、`area`、在线状态、风险、能力 JSON 和元数据。

目标关系：

- 保留接入身份和设备技术属性。
- 新增 `entity_id` 指向稳定现实对象。
- `area` 保留为兼容字段和迁移辅助，不作为空间外键。

不做的事：

1. 不把协议、单位、采集时间塞进 `devices`。
2. 不把未来机器人、物体都建成 Device。
3. 不用 `devices.area` 做状态估计空间聚合。

### 2.2 `device_states`

现状：`device_id + state + attributes + raw_state + source + observed_at + created_at`，被最新状态、历史、事件链路和上下文共同使用。

目标：

- 迁移期只作为兼容投影或冻结历史。
- Observation Pipeline 接管后不再为每次观测新增历史行。
- 最终由 `observations` 和 `current_state_estimates` 替代。

约束：

1. 先解决 `EnvironmentReconciler` 与 `DeviceEventService` 的重复写路径，再启用 Observation。
2. 不将旧 `observed_at` 全量解释为设备采集时间。
3. 不为兼容 UI 复制完整 Observation JSON。

### 2.3 `device_capabilities`

现状：设备能力、支持动作、参数、风险、确认要求和启用状态。

目标：继续作为设备接入能力和执行安全依据。ARS-02 只读它判断可观测属性，不迁移成第二套实体能力系统。

未来扩展：机器人或视觉能力若不属于 Device，可在 Entity 能力模型扩展时另行设计；本阶段不实现。

### 2.4 `events`

现状：领域事件审计，包含类型、来源、主体、payload、correlation、发生时间和创建时间，已有 180 天 / 诊断 90 天保留。

目标：

- 保留事件职责，新增观测或估计只作为 payload 引用。
- Event 可引用 `observation_id`、`state_estimate_id`，但不复制观测历史。
- 不把 `events` 当作 Observation 表或 State Estimate 表。

### 2.5 `environments`

现状：运行范围和默认范围，只有名称、描述、是否默认、创建时间和快照关系。

目标：新增 `root_space_id`，继续作为运行范围和上下文所有者。

禁止：

1. 禁止把 `environments` 当作根房间。
2. 禁止在 `environments` 上建立楼层 / 房间列表。
3. 禁止空间表再挂 `environment_id` 形成第二条空间树。

### 2.6 `environment_snapshots`

现状：保存 Environment Context JSON、活跃任务 ID、异常数和创建时间。

目标：

- 保存 Context v2 投影。
- 建议新增 `context_version` 和 `state_generated_at`，区分投影生成时间和估计生成时间。
- 保留 14 天默认值。
- 不从 Snapshot 反向推导当前事实。

### 2.7 `memories`

现状：有表结构，未形成完整 Memory Service。

目标：ARS-02 不实现 Memory。只保证未来 `source_type` 可以引用 `state_estimate` 或 `observation`，但本阶段不迁移、不写入。

### 2.8 `user_preferences`

现状：全局键值偏好，含分类、描述、来源、确认和时间。

目标：保留 UI 和用户偏好。观测保留、敏感属性授权、删除策略使用专门表和审计记录，不把合规事实塞进普通 JSON 偏好。

## 3. 目标迁移顺序

所有结构变化必须通过 Alembic 迁移，并使用 SQLite `batch_alter_table`。本文只定义方案，不创建迁移文件。

### ARS-02.1：Spatial Model

新增：

1. `spaces`
2. `space_paths`

修改：

1. `environments.root_space_id`

内容：

1. 创建默认 Environment 的根空间，默认类型 `home`。
2. 建立根、父子、路径和闭包索引。
3. 不自动把 `devices.area` 猜成房间；后续通过导入或用户确认创建房间。

验收：迁移可升级、可回滚、可重建；单环境单根约束生效。

### ARS-02.2：Entity 与 Observation 契约

新增：

1. `entities`
2. `entity_space_assignments`
3. `observation_sources`
4. `observation_attribute_definitions`
5. `observations`
6. `observation_attribute_policies`
7. `observation_consents`

修改：

1. `devices.entity_id`

内容：

1. 为每个现有 Device 创建 Entity 并回填。
2. 只为空间归属明确的设备创建归属区间；无法判断则保持 unknown。
3. 注册 HA 与 Mock 来源。
4. 可选择只回填每个设备最新一条状态为 Observation，用于连续性验证；不得默认全量回填不可靠历史。
5. 旧 `device_states` 保持冻结只读。

### ARS-02.3：Pipeline 与写入治理

新增：

1. `observation_ingestion_batches`
2. `observation_source_heartbeats`

内容：

1. 修复现有重复写路径，Pipeline 成为唯一兼容投影写入者。
2. 建立幂等、采样、去重、质量评估和批处理。
3. 建立保留任务和来源健康状态。

已实现迁移 `b7d4e6c9a210`：

1. `device_states` 增加 `is_current`，默认 `0`。
2. 升级时按 `observed_at DESC, created_at DESC, id DESC` 为每台设备唯一标记最新一行为当前投影，所有历史行保留。
3. 在 SQLite 上创建 `is_current = 1` 的 `device_id` partial unique index，保证一台设备最多一个当前投影。
4. 新增 ingestion batch 与来源心跳表及查询索引；回滚只移除本迁移结构，不删除历史 `device_states`。
5. `privacy_deletion_jobs` 不在本迁移中提前创建；删除任务必须待 State Estimation、Snapshot 和证据链接落地后在 ARS-02.5 一并实现，避免半套不可审计删除。

### ARS-02.4：State Estimation 与 Context v2

新增：

1. `estimation_targets`
2. `state_estimates`
3. `state_estimate_observations`
4. `current_state_estimates`

修改：

1. `environment_snapshots.context_version`
2. `environment_snapshots.state_generated_at`

内容：

1. 从当前 Observation 开始估计，不要求伪造历史状态。
2. 切换 Environment Context 读取源。
3. 完成 `device_states` 读取路径替换。

### ARS-02.5：查询、Tool 与前端

原则上无必须业务表变更。允许新增索引或重建视图，但不新增重复状态事实源。

### ARS-02.6 / ARS-02.7

真实传感器验证和最终验收不新增表；只允许基于实测结果调整配置阈值、索引或迁移 bug 修复。

## 4. 迁移安全规则

1. 迁移前强制数据库备份，并校验备份文件。
2. 每个迁移独立可回滚；回滚不得删除用户已确认的空间、实体和授权记录。
3. 大量回填按主键或时间分页，单批固定行数，可重跑。
4. 先加 nullable 字段和索引，完成数据回填后再收紧约束。
5. SQLite 修改表结构使用 batch mode，避免直接重建失败。
6. 迁移过程写入诊断记录，但不把迁移日志放进 `events` 冒充业务事件。
7. 历史数据无法满足新契约时保留原表，不做猜测填充。
8. 每个迁移提供数据量前后检查：设备数、实体数、空间数、观测数、孤儿记录数。

## 5. 索引与 SQLite 性能

### 5.1 必要索引

| 表 | 索引 |
| --- | --- |
| `spaces` | `parent_id`、`path`、`external_source + external_space_id`、`status` |
| `space_paths` | PK `(ancestor_id, descendant_id)`、`descendant_id` |
| `entities` | `environment_id + entity_type`、`normalized_name` |
| `entity_space_assignments` | `entity_id + valid_from`、`space_id + valid_from`、当前区间部分索引 |
| `observations` | unique `dedupe_key`、`source_id + attribute + received_at`、`entity_id + attribute + received_at`、`space_id + attribute + received_at`、`retention_until` |
| `state_estimates` | `target_id + generated_at`、`environment_id + status + generated_at` |
| `state_estimate_observations` | PK `(estimate_id, observation_id)`、`observation_id` |
| `current_state_estimates` | PK `target_id`、`environment_id + status`、`valid_until` |

索引必须随实测查询调整，不允许为每个 JSON 字段建索引。JSON 查询只用于管理详情，不用于当前状态热路径。

### 5.2 写入策略

1. SQLite 当前启用 `busy_timeout=5000`、WAL、`synchronous=NORMAL` 和 `foreign_keys=ON`。
2. Observation 按轮询批次进入 Pipeline，批处理状态独立持久化；单次保留删除限制行数并循环执行，避免长锁。
3. 保留一个后台写入队列或串行写入器，避免多任务并发写造成锁冲突。
4. UPSERT 依赖 `dedupe_key`，失败重试不得生成重复观测。
5. 迁移期当前 `device_states` 投影与 Observation 入库结果保持一致；估计历史同事务要求从 ARS-02.4 开始生效。
6. 删除任务分批执行，避免长锁和大 WAL 增长。
7. 维护窗口执行 `wal_checkpoint(TRUNCATE)`；是否 `VACUUM` 需在备份和停机策略确认后执行。

### 5.3 容量估算

单条 Observation 估算为 0.6 KB 到 1.2 KB，加索引约为 1.5 到 3 倍存储。示例：

| 场景 | 输入速率 | 每日输入 | 30 天无治理总量估算 | 默认治理后的长期状态 |
| --- | --- | --- | --- | --- |
| 20 个低频传感器，5 分钟轮询 | 4 reads/min | 5,760 | 约 155 到 311 MB | 无变化轮询接近 0 条 Observation，仅更新来源心跳；有变化数据按 30 天上限约 155 到 311 MB |
| 50 个传感器，1 分钟轮询 | 50 reads/min | 72,000 | 约 1.95 到 3.9 GB | 数值类按最小间隔与变化阈值节流；无变化轮询接近 0 条 Observation |
| 200 个传感器，10 秒轮询 | 1,200 reads/min | 1,728,000 | 不允许全量入库 | 60 秒最小间隔的理论接受上限为 288,000 条/日；全部不变时仅保留来源心跳，理论稳态可降到接近心跳表规模 |

估算口径：

1. Observation 行大小按 0.6 到 1.2 KB 计。
2. 表格总量已包含 1.5 到 3 倍索引开销。
3. 输入速率表示 Adapter 看到的候选读数，不等同于 SQLite Observation 写入速率。
4. 来源心跳按来源与轮询批次更新，不是每个传感器各写一条。
5. 清理后的长期规模由各类保留期决定；普通 30 天、motion / occupancy / invalid 7 天、batch 30 天。

默认策略：

1. 普通环境观测 30 天。
2. 运动、占用、存在等敏感短保留观测 7 天。
3. invalid 观测 7 天。
4. `observation_ingestion_batches` 30 天。
5. 状态估计历史 180 天。
6. Environment Snapshot 14 天。
7. `device_states` 迁移期 14 到 30 天，切换后冻结并按计划归档。
8. Event 保留现有 180 天 / 诊断 90 天策略。

删除 Observation 后，对应估计输入链接同步移除；估计历史保留来源摘要。该追溯边界必须向用户和管理界面说明。

## 6. 隐私、授权与删除

### 6.1 `observation_attribute_policies`

| 字段 | 说明 |
| --- | --- |
| `attribute` | 属性 |
| `sensitivity` | `normal`、`sensitive`、`highly_sensitive` |
| `requires_consent` | 是否必须显式授权 |
| `allowed_source_types` | 允许来源 |
| `allowed_spaces` | 空间范围策略 |
| `raw_storage_allowed` | 是否允许保存 raw value |
| `record_retention_days` | 整条 Observation 记录保留期 |
| `normalized_only` | 是否只保存标准化值 |
| `redaction_rule` | 删除或匿名化规则 |
| `version` | 策略版本 |

### 6.2 `observation_consents`

| 字段 | 说明 |
| --- | --- |
| `id` | 授权 ID |
| `subject_type` / `subject_id` | 用户、空间或实体范围 |
| `attribute` / `policy_id` | 授权对象 |
| `status` | `granted`、`revoked`、`expired` |
| `granted_at` / `revoked_at` / `expires_at` | 生效区间 |
| `scope` | 空间、来源和用途限制 |
| `evidence` | 用户确认或声明摘要 |

规则：

1. 授权撤销立即停止采集和读取。
2. 删除范围可按空间、实体、属性、来源或时间选择。
3. 删除任务必须处理 Observation、输入链接、估计、Event payload、快照和日志中的可删除副本。
4. 备份中的数据不能被在线删除操作即时修改；系统必须说明备份过期策略。
5. 删除完成不等于所有历史追溯无限保留；追溯随保留和删除策略终止。
6. ARS-02 的 Observation 行默认 append-only；常规保留到期删除整行，不在同一条记录中局部改写 raw value 来制造不同保留周期。敏感属性使用更短的整行保留期或禁止保存 raw。

## 7. API 草案

沿用现有认证、错误结构和审计边界。空间、实体、观测和删除管理需要更高权限；公开给 Agent 的只有只读 Tool。

### 7.1 Spaces

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/spaces` | 查询空间列表，可按 root、type、status 过滤 |
| `GET` | `/api/spaces/tree` | 返回完整空间树 |
| `POST` | `/api/spaces` | 创建子空间 |
| `GET` | `/api/spaces/{id}` | 空间详情 |
| `PATCH` | `/api/spaces/{id}` | 更新名称、排序、状态和元数据 |
| `POST` | `/api/spaces/{id}/move` | 移动父节点，事务内更新路径 |
| `POST` | `/api/spaces/{id}/archive` | 归档空间 |
| `GET` | `/api/spaces/{id}/state` | 空间状态估计 |
| `GET` | `/api/spaces/{id}/coverage` | 属性覆盖、盲区和丢失情况 |

### 7.2 Entities

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/entities` | 查询实体 |
| `POST` | `/api/entities` | 创建实体 |
| `GET` | `/api/entities/{id}` | 详情 |
| `PATCH` | `/api/entities/{id}` | 更新语义信息 |
| `POST` | `/api/entities/{id}/assignments` | 设置当前或历史空间归属 |
| `GET` | `/api/entities/{id}/assignments` | 查询空间历史 |
| `POST` | `/api/entities/{id}/bind-device` | 绑定接入设备 |

### 7.3 Observations

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/observations` | 分页查询，默认不含 raw |
| `GET` | `/api/observations/{id}` | 详情；raw 需要调试权限 |
| `GET` | `/api/observation-sources` | 来源状态 |
| `GET` | `/api/observation-sources/{id}/health` | 最近成功、失败、延迟和重复率 |

外部设备数据不提供公开 POST 写入口；来源接入必须经过 Adapter 和 Pipeline。

### 7.4 State Estimates

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/state-estimates` | 当前或历史估计 |
| `GET` | `/api/state-estimates/{id}` | 估计详情 |
| `GET` | `/api/state-estimates/{id}/evidence` | 输入观测和冲突候选 |
| `POST` | `/api/state-estimates/rebuild` | 管理员触发投影重建 |

### 7.5 Environment Context v2

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/environment/context-v2` | 当前空间树摘要 |
| `GET` | `/api/environment/snapshots` | 历史投影 |
| `GET` | `/api/environment/snapshots/{id}` | 单时点投影 |

保留 v1 一个过渡周期，响应中标明 `context_version`。前端和 Agent 完成切换后移除 v1。

### 7.6 Privacy Deletion

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/api/privacy/deletion-jobs` | 创建删除或匿名化任务 |
| `GET` | `/api/privacy/deletion-jobs` | 查询任务 |
| `GET` | `/api/privacy/deletion-jobs/{id}` | 任务详情 |
| `POST` | `/api/privacy/deletion-jobs/{id}/cancel` | 取消未执行任务 |

删除是物理删除或按策略匿名化，禁止只隐藏 UI。

## 8. Agent Tool 草案

升级现有 `get_environment_state` 为 v2 只读工具，不新增绕过 Tool Registry 的 Agent API。

输入：

```json
{
  "space_id": "optional",
  "space_path": "optional",
  "attributes": ["temperature", "occupancy"],
  "include_descendants": true,
  "include_evidence": false
}
```

输出：

1. 空间路径。
2. 七种状态和值。
3. 生成时间与有效期。
4. 覆盖情况。
5. 基础来源摘要。
6. 冲突和未知说明。

限制：

1. 默认不返回完整 raw payload、内部主机名、Token 或精确隐私数据。
2. 敏感属性受授权和最小化策略约束。
3. Agent 不能请求写库、重算估计或读取任意 Observation。
4. 工具风险保持只读，但访问日志仍需审计。

## 9. Web Console 设计

ARS-02.5 新增或升级：

1. 空间树管理：创建、重命名、排序、移动和归档。
2. 房间状态页：温度、湿度、占用、门窗等状态卡片。
3. 状态徽章：七种状态必须视觉可区分，unknown 不能显示为空值正常态。
4. 覆盖视图：covered、partial、blind、lost。
5. 来源抽屉：查看估计值、输入来源、规则版本、生成时间、有效期。
6. 质量列表：延迟、冲突、无效、重复率和来源健康。
7. 时间展示：采集时间未知时显示“采集时间未知”，同时显示接收时间。
8. 隐私管理：授权、撤销、保留策略和删除任务。
9. 存储页：行数、估算容量、保留窗口和清理状态。

前端不直接访问数据库或 Adapter，不复制状态计算逻辑。

## 10. 回滚与兼容

1. API v1 在过渡期保留，但返回中标注数据来源版本。
2. 旧设备控制链路必须继续工作。
3. Context v2 切换失败可回读 v1，但不得把 v1 结果写回新估计表。
4. `device_states` 归档前必须确认没有活跃读取方。
5. 任何回滚不得删除用户创建的空间、实体、授权和删除任务记录。
6. 回滚后新 Observation 可停止写入，但不能篡改为旧 `device_states` 语义。

## 11. 未定事项

1. HA `last_changed` / `last_updated` 在目标真实设备上的可靠性需要 ARS-02.6 实测。
2. SQLite WAL、busy timeout 和批大小需按真实写入量压测确定。
3. 是否为运动类观测保留更短默认周期，需用户确认隐私偏好。
4. 贵重物品实体是否默认对 Agent 隐藏，需用户确认。
5. 备份中已撤销授权数据的可用期限需用户确认。

本文冻结后，ARS-02.1 才能开始实现。
