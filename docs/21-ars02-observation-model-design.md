# 21. ARS-02 Observation Model 设计

- 阶段：`ARS-02.0：架构设计与数据契约冻结`
- 日期：2026-11-02
- 状态：设计完成，等待用户确认；本文不是已实现行为
- 范围：观测来源、观测数据结构、标准化、去重、质量标记和接收管线
- 禁止事项：本文不修改业务代码、数据库迁移、API、依赖或前端页面

## 1. 设计结论

Observation 是“一次实际观测”的不可变记录。它回答：谁看到、看到什么、在哪个空间、原始值是什么、标准化值是什么、什么时候被现实世界观测、什么时候进入 Arvuno、质量如何、能否用于估计。

Observation 不直接回答“当前房间状态是什么”。当前状态由 State Estimate 计算；重要变化由 Event 发布；Environment Context v2 只是状态估计的只读投影。

## 2. 当前代码问题

当前实现已有设备轮询、Device Registry、EventBus 和 `device_states`，但没有独立 Observation Model：

1. `device_states` 混合承担设备状态历史、最新状态缓存、事件载荷和 Environment Context 输入。
2. Home Assistant `_state_from_entity()` 使用 `_now()` 填充 `observed_at`。这是 Arvuno 读取时间，不是设备采集时间。
3. `EnvironmentReconciler.reconcile()` 先调用 `record_observed_state()`，随后发布差异事件时 `DeviceEventService.publish()` 可能再次记录同一状态。
4. `device_states.attributes` 没有单位、质量、时间来源、去重键和观测主体语义。
5. 传感器数值变化、属性字典变化和设备可用性变化被压成一行业务事件，无法作为可追溯观测。

ARS-02 不能继续向 `device_states` 添加字段来弥补这些缺口。必须建立独立 Observation 契约，并将 `device_states` 降级为兼容投影或迁移期过渡数据。

## 3. 核心概念

| 概念 | 定义 |
| --- | --- |
| Observation Source | 数据进入 Arvuno 的来源，例如 Home Assistant Adapter、Mock Adapter、用户报告、未来视觉任务 |
| Subject | 被观测的对象，可以是 Entity、Space、User 或未来其他主体 |
| Attribute | 标准化属性，例如 `temperature`、`humidity`、`motion`、`contact`、`occupancy` |
| Raw Value | 来源原始值和原始单位，不做解释 |
| Normalized Value | 按规则版本转换后的标准值和标准单位 |
| Quality | 管线对完整性、时间、范围、重复、异常和来源可信度的标记 |
| Validity | 观测语义适用的时间区间 |
| Freshness | 查询或估计时相对属性时效策略计算的新鲜度 |

Freshness 是动态属性，不能只在入库时写死。管线可以保存评估依据和过期时间；API 和估计器必须基于当前时间重新评估。

## 4. Observation Source 契约

### 4.1 `observation_sources`

| 字段 | 类型 / 约束 | 说明 |
| --- | --- | --- |
| `id` | UUID / PK | 来源 ID |
| `source_type` | string | `adapter`、`user_report`、`derived_job`、`vision`、`future_external` |
| `adapter_id` | string，nullable | 对应现有 Adapter ID；非 Adapter 来源为空 |
| `name` | string | 用户可见来源名 |
| `status` | string | `active`、`paused`、`unavailable`、`revoked` |
| `trust_level` | numeric | 0 到 1 的来源基础可信度，只能作为策略输入 |
| `time_trust` | string | `device_clock`、`gateway_clock`、`poll_clock`、`user_asserted`、`unknown` |
| `config` | JSON | 采样率、允许属性、外部系统说明 |
| `privacy_scope` | JSON | 允许空间、允许主体、敏感属性边界 |
| `created_at` | UTC datetime | 创建时间 |
| `updated_at` | UTC datetime | 更新时间 |

规则：

1. 来源凭证和 API Token 不进入 Observation 数据，继续由现有配置和脱敏日志管理。
2. `trust_level` 不表示真值概率，不得让高信任来源覆盖所有冲突证据。
3. 来源撤销后停止采集，已有数据按属性策略和删除任务处理。
4. Home Assistant 和 Mock Adapter 必须分别注册为可区分来源。

## 5. Observation Schema

### 5.1 `observations`

目标表为 append-only。以下字段构成完整 Observation 契约。

| 字段 | 类型 / 约束 | 语义 |
| --- | --- | --- |
| `observation_id` | UUID / PK | 一次观测记录 |
| `source_id` | FK → `observation_sources.id` | 数据进入 Arvuno 的来源 |
| `source_type` | string | 来源类型冗余，便于查询和审计 |
| `entity_id` | FK → `entities.id`，nullable | 被观测实体 |
| `subject_type` | string，nullable if `entity_id` | `space`、`user`、`environment`、`future_subject` |
| `subject_id` | string，nullable if `entity_id` | 非实体主体 ID |
| `space_id` | FK → `spaces.id`，nullable | 观测发生或适用的空间 |
| `attribute` | string | 标准属性名 |
| `raw_value` | JSON | 原始值，保留来源形态 |
| `raw_unit` | string，nullable | 原始单位 |
| `normalized_value` | JSON | 标准值；无法标准化时为空 |
| `normalized_unit` | string，nullable | 标准单位 |
| `value_type` | string | `number`、`boolean`、`enum`、`string`、`json` |
| `observed_at` | UTC datetime，nullable | 现实观测时间；不可靠时必须为空 |
| `observed_at_source` | string，nullable | `device_clock`、`gateway_state_clock`、`user_asserted`、`derived`、`unknown` |
| `observed_at_uncertainty_ms` | integer，nullable | 时间不确定性 |
| `received_at` | UTC datetime，非空 | Arvuno 收到时间 |
| `processed_at` | UTC datetime，nullable | 管线完成处理时间 |
| `quality_status` | string | `valid`、`warning`、`invalid`、`pending` |
| `quality_issues` | JSON | 机器可读问题列表和阈值 |
| `valid_from` | UTC datetime，nullable | 观测语义开始适用时间 |
| `valid_until` | UTC datetime，nullable | 观测语义结束适用时间 |
| `freshness_policy` | string，nullable | 使用的属性时效策略 ID 或版本 |
| `freshness_evaluated_at` | UTC datetime，nullable | 上次评估时间 |
| `correlation_id` | string，nullable | 轮询批次、任务、事件或用户操作关联 |
| `external_id` | string，nullable | 来源内部事件 ID或实体状态 ID |
| `dedupe_key` | string，unique | 幂等键 |
| `payload_hash` | string | 原始相关字段的稳定哈希 |
| `normalization_rule_version` | string，nullable | 标准化规则版本 |
| `retention_class` | string | 普通、短保留、敏感短保留 |
| `retention_until` | UTC datetime，nullable | 允许清理的时间 |
| `created_at` | UTC datetime | 数据库写入时间 |

约束：

1. `entity_id` 和 `subject_type + subject_id` 必须至少有一组，不允许无主体观测。
2. 同一条观测内不得同时把 Entity 和其他 Subject 声明为同一主对象；相关对象可放入 `quality_issues` 或未来关联表。
3. `observed_at_source` 有值时必须解释时间来源；`observed_at` 为空时不得推断成 `received_at`。
4. `processed_at` 为空表示尚未完成标准化或质量评估；有效观测必须在事务完成后非空。
5. `raw_value` 可以包含最小必要上下文，不得包含凭证、完整原图或超出授权的原始数据。
6. `dedupe_key` 是唯一索引，重复写入使用 UPSERT 或丢弃策略，并记录计数。

### 5.2 Dedupe Key 规则

优先级依次为：

1. 来源提供全局唯一事件 ID：哈希 `source_id + external_id + attribute`。
2. 来源提供实体状态版本或更新序号：加入版本字段。
3. 无来源 ID，但有可靠 `observed_at`：哈希 `source_id + subject + space_id + attribute + observed_at + raw_value + raw_unit`。
4. 只有轮询读取时间：哈希 `source_id + subject + attribute + payload_hash + poll_window`。

同一轮询批次内相同键只保留一次；跨批次相同原始值是否保留由属性采样策略决定。丢弃重复不表示数据不存在，管线应输出重复计数供质量监控使用。

## 6. Attribute 定义契约

新增 `observation_attribute_definitions`：

| 字段 | 说明 |
| --- | --- |
| `attribute` | 唯一标准属性名 |
| `display_name` | 展示名 |
| `value_type` | 标准值类型 |
| `canonical_unit` | 标准单位 |
| `normalization_rule_version` | 标准化规则版本 |
| `valid_range` | 数值或枚举范围 |
| `quality_policy` | 缺失、异常、跳变、延迟阈值 |
| `freshness_policy` | 不同空间或用途的时效阈值 |
| `sampling_policy` | 最小间隔、变化阈值、只记录变化 |
| `retention_policy` | 默认保留等级 |
| `sensitivity` | `normal`、`sensitive`、`highly_sensitive` |

初始属性至少包括：

| 属性 | 标准单位 / 值 | 说明 |
| --- | --- | --- |
| `temperature` | `°C` | 温度 |
| `humidity` | `%RH` | 相对湿度 |
| `motion` | `true/false/unknown` | 检测到运动，不等于有人或无人 |
| `contact` | `open/closed/unknown` | 门磁等接触状态 |
| `occupancy` | `occupied/unoccupied/unknown` | 占用估计，不直接来自单一 PIR |
| `illumination` | `lux` | 照度 |
| `co2` | `ppm` | 二氧化碳 |
| `device_availability` | `online/offline/unknown` | 接入可用性 |
| `actuator_state` | JSON / enum | 执行器反馈状态 |

属性名使用受控词汇表，禁止每个 Adapter 自造同义词。Adapter 只负责提供原始 domain、device class、state 和 attributes；映射到标准属性必须由带版本的规则完成。

## 7. 时间语义

### 7.1 时间决策表

| 场景 | `observed_at` | `observed_at_source` | 质量处理 |
| --- | --- | --- | --- |
| 设备报文带可信 UTC 或带时区的时间 | 保存 | `device_clock` | 可给出时间不确定性 |
| HA 提供 `last_updated` / `last_changed` | 仅在语义匹配时保存 | `gateway_state_clock` | 标记为 HA 状态更新时间，不宣称设备采集时间 |
| 仅轮询到当前状态 | `null` | `poll_clock` 或 `unknown` | 不得复制为采集时间 |
| 用户手动报告 | 用户选择时间 | `user_asserted` | 未来时间或过早时间标 warning |
| 派生观测 | 计算基准时间 | `derived` | 必须引用来源估计或观测 |
| 时钟明显漂移或早于收到前超阈值 | 保存原值或置空 | 对应来源 | 标记 warning/invalid 并记录阈值 |

### 7.2 Home Assistant 约束

HA `last_updated` 表示 HA 状态对象更新时间，`last_changed` 表示 state 值变化时间，属性变化不一定更新 `last_changed`。工程实现必须：

1. 不把 `_now()` 写成采集时间。
2. 轮询无状态版本时允许 `observed_at = null`。
3. 使用 `last_changed` / `last_updated` 时保留原语义和质量标记。
4. 对同一实体同时产生 state 和多个 attribute 观测时，每个 Observation 单独记录时间语义。
5. 时区和无时区字符串必须显式转换规则，不能依赖运行机器本地时区。

## 8. Observation Pipeline

目标管线属于独立的 Perception / Observation 模块，Device Adapter 不直接写数据库。

```text
Device Adapter / User Report / Future Source
  → Source Adapter Normalizer
  → Contract Validation
  → Time Resolution
  → Attribute Mapping
  → Unit and Value Normalization
  → Sampling and Dedupe
  → Quality Evaluation
  → Observation Persistence
  → Estimation Trigger
  → Compatibility Projection（迁移期）
```

### 8.1 阶段职责

1. 接收：只接受来源已授权、主体可解析、属性允许的数据。
2. 契约校验：检查必填字段、类型、主体、空间和单位。
3. 时间解析：区分采集、网关、轮询、接收和处理时间。
4. 标准化：按属性规则转换单位和枚举，不改变 raw value。
5. 采样：高频属性按最小间隔或变化阈值节流；控制和安全相关状态不得因采样丢失关键变化。
6. 去重：以 `dedupe_key` 幂等写入。
7. 质量标记：标记延迟、缺失、超范围、类型错误、跳变、来源离线、时间不可靠。
8. 持久化：一次事务写入 Observation 和必要投影；失败重试必须保持幂等。
9. 触发估计：只发送轻量事件或调用端口，不把完整观测塞进 EventBus 作为第二事实源。
10. 兼容投影：迁移期维护旧 `device_states` 读取需要的最小状态。

### 8.2 质量状态

| 状态 | 含义 |
| --- | --- |
| `pending` | 已接收，尚未完成处理 |
| `valid` | 满足契约和质量阈值 |
| `warning` | 可用但存在延迟、时间不可靠、轻度异常或来源可信度下降 |
| `invalid` | 不应参与正常估计，例如类型错误、超范围、主体不匹配、时间严重矛盾 |

质量问题必须结构化，例如：

```json
{
  "code": "delayed_observation",
  "severity": "warning",
  "observed_delay_seconds": 420,
  "threshold_seconds": 300
}
```

## 9. 与现有 `device_states` 的关系

目标状态：

1. `observations` 是原始观测时间序列唯一事实源。
2. `current_state_estimates` 是当前语义状态唯一事实源。
3. `events` 只保存重要变化和动作审计。
4. `device_states` 最终成为废弃兼容表，或只保留无法迁移的历史数据。

迁移期规则：

1. Observation Pipeline 是唯一写入 `device_states` 新数据的入口。
2. 每个外部状态最多产生一条 Observation；兼容投影最多保留一个当前状态，不得把 Observation、`device_states` 和 Event payload 各写一遍历史。
3. 现有 UI 和工具完成切换后，停止新增 `device_states` 历史。
4. 历史回填必须限量、可重跑、可中断，并按 `device_states.id` 或时间分页。
5. 无法判断采集时间的旧数据，回填为 `observed_at = null`，`received_at` 使用旧行 `created_at`，不得把旧 `observed_at` 继续解释为设备采集时间。

## 10. 采样和写入量控制

1. 每个属性必须有最小采样间隔和变化阈值，禁止把 HA 轮询结果全量入库。
2. 状态跳变、安全问题、用户动作和控制反馈不能被普通采样策略吞掉。
3. 无变化的轮询可更新来源心跳，但不得生成 Observation。
4. 原始观测默认保留 30 天；运动、占用等敏感短保留数据默认 7 天。
5. 保留策略和存储设计详见第 23 号文档。
6. 管线必须有每秒入库、丢弃、重复、延迟和错误指标，并暴露健康状态。

## 11. 隐私边界

1. 高敏感属性必须有明确授权，未授权时在来源层拒绝，而不是入库后再隐藏。
2. 用户报告、摄像头、麦克风、精确位置相关观测未来必须绑定 consent 记录；本阶段仅实现普通环境传感器和用户手动报告。
3. raw value 保留最小必要信息，不保存无关属性字典。
4. API 默认不返回 raw payload；调试访问必须授权、审计并脱敏。
5. 删除任务必须处理 observations、状态估计输入链接、事件 payload、日志和控制台缓存；备份处理策略必须显式记录。

## 12. 验收边界

Observation Model 的 ARS-02.2 / ARS-02.3 验收要求：

1. 所有必需语义字段存在，且 nullable 规则与本文一致。
2. 不可靠采集时间保持为空，未出现用接收时间伪造采集时间。
3. HA 和 Mock 能产生标准化、去重、带质量的 Observation。
4. 同一状态不再造成多处历史写入。
5. 延迟、重复、超范围、类型错误和缺失主体有可测试质量结果。
6. 采样不会吞掉关键状态变化。
7. 授权撤销和删除任务能阻止后续采集并处理既有数据。

本文冻结后，才能进入 ARS-02.2 工程实现。
