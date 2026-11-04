# 27. ARS-03.2 环境时间理解与历史关联

- 阶段：`ARS-03.2：环境时间理解与历史关联`
- 日期：2026-11-04
- 状态：工程实现完成，待用户验收
- 范围：只读历史查询、时间语义、空间 / 实体 / 设备历史、环境快照对比、趋势统计、历史关联和确定性自然语言历史问答
- 不做：不新增历史数据库表、不修改 Observation 写入链路、不引入向量数据库、不提供物理世界时光回滚、不开发通用自然语言理解引擎

## 1. 阶段结论

ARS-03.2 在 ARS-02 的空间、实体、观测、事件、任务和环境快照数据之上增加一个只读 History 层。历史查询不复制原始记录，也不维护第二份事实源；它负责把已有历史按时间、空间、实体、任务和 correlation ID 组织成可引用、可审计的回答。

核心模块：

| 模块 | 职责 |
| --- | --- |
| `HistoryRepository` | 通过 SQLAlchemy 执行只读查询，并把 aware 时间统一转成 SQLite 存储使用的 naive UTC 边界 |
| `HistoryStore` | 只读持久化边界协议；Service 不接触 SQLAlchemy Session |
| `HistoryService` | 校验时间范围、组装记录、计算统计与缺口、执行快照对比和确定性历史问答 |
| `/api/history/*` | FastAPI 协议转换；全部路由要求 API Token |
| `schemas/history.py` | API、领域响应和 Pydantic 校验契约 |

新增运行依赖只有 `tzdata`，用于 Windows 和容器环境下可靠的 IANA 时区解析。历史查询能力本身仍只使用 SQLite 关系查询，没有引入全文索引、向量数据库或额外历史表。

## 2. 数据边界

History 层复用以下既有记录，不创建重复副本：

| 既有数据 | History 层用途 |
| --- | --- |
| `spaces`、`space_paths`、`entity_space_assignments` | 解析当前与历史空间归属和后代空间 |
| `entities`、`devices` | 提供设备、传感器和执行器的稳定现实对象身份 |
| `observations` | 温度、湿度等真实采集记录，是趋势和缺失分析的事实源 |
| `events` | 设备动作和领域事件，是动作识别和历史关联的事实源 |
| `tasks` | 任务执行过程，可按 correlation ID 与观测和事件关联 |
| `environment_snapshots` | 某个时点的环境状态投影，用于快照查询和有限差异 |
| `environments` | 提供默认查询范围和快照归属 |

边界规则：

1. Observation History 继续保存可追溯观测；History Service 只读。
2. Event History 继续保存重要事件；查询中的事件关联不写回事件表。
3. Task History 继续保存执行过程；任务与环境变化关联只返回引用和关系依据。
4. Memory 不在本阶段自动形成；确定性历史答案也不写入 Memory。
5. Conversation History 不复制到历史响应，自然语言问答只返回问题解释、记录、统计和警告。
6. `environment_snapshots` 是投影，不是权威状态源；权威来源仍要回到 Observation、Event、Task 和当时的状态估计。

## 3. 时间语义

数据库层延续现有 UTC 存储。SQLite 中的 datetime 没有时区后缀，因此 History Repository 在过滤前把所有 aware 输入转换成 naive UTC；响应中的 UTC datetime 和用户本地展示时间都带偏移量。

每个查询必须携带 IANA 时区，例如 `Asia/Shanghai`。`start_time` 和 `end_time` 使用 Pydantic `AwareDatetime`，naive 时间直接返回 `400 / HISTORY_VALIDATION_ERROR`。本地日期边界先在用户时区构造，再转换到 UTC。

响应中的 `TimeSemantics` 包含：

1. 存储时区 UTC 和展示时区。
2. 查询时间基准。Observation 使用 `received_at`；Event 使用 `occurred_at`；Task 和 Snapshot 使用创建时间。
3. 可用的采集、接收和处理时间计数。
4. 迟到观测阈值 60 秒、未来时钟偏差阈值 30 秒，以及对应 record ID。
5. 缺少采集时间的 record ID；这类记录不伪造 `observed_at`。
6. 查询 warnings，包括完全未来范围、早于最早记录的范围和空结果范围。

缺失时间用 `TimeGap` 显式表示。调用方可传 `expected_interval_seconds`，系统按区间内已知观测推导缺口；不提供该值时不猜测采样周期。迟到数据保留原始采集时间并标记迟到；未来偏差数据保留并标记，不静默改时间。范围必须满足 `start < end`。

## 4. 查询能力

| API | 能力 |
| --- | --- |
| `GET /api/history/time-range` | 按时间范围聚合 Observation、Event、Task、Snapshot，并返回数量、时间语义、缺口和警告 |
| `GET /api/history/spaces/{space_id}` | 查询空间历史；`include_descendants=true` 时包含严格后代，不把请求空间重复加入后代列表 |
| `GET /api/history/entities/{entity_id}` | 查询实体 / 设备历史和空间归属区间 |
| `GET /api/history/trends` | 按空间或实体统计有效数值，输出 min、max、avg、首末值、变化量和每小时变化率 |
| `GET /api/history/environment/snapshot` | 查询指定时间 `at_or_before` 或最近的快照 |
| `POST /api/history/environment/snapshots/diff` | 按 ID 或按时间定位两个快照并比较 |
| `GET /api/history/correlations/{record_type}/{record_id}` | 以 observation、event 或 task 为入口返回关联记录 |
| `POST /api/history/ask` | 执行受限的确定性中文历史问答 |

查询上限由 API 限制：time-range / spatial / entity 最多 2000 条，趋势最多 5000 条。趋势只统计 `quality_status=valid` 的数值；无效、缺失或非数值记录不进入平均值。排序优先使用真实采集时间，采集时间缺失时退回接收或创建时间，并在语义中暴露该限制。

事件、任务和观测关联规则是保守的：

1. 有相同 `correlation_id` 时作为强关联。
2. Event 到 Observation 可用相同主体或五分钟窗口补齐，但会标明这是推断。
3. Task 到 Observation 优先 correlation ID，再受任务时间窗口约束。
4. Snapshot 使用最近的保留投影，并在关系依据中说明。
5. 没有关联依据时返回空结果或警告，不虚构历史。

## 5. 自然语言历史接口

`/api/history/ask` 只实现确定性模板，不调用模型，不把自由文本当作已理解的意图。当前支持四类问题：

1. `昨天客厅发生了什么？`：解析本地日期和已知空间，返回范围内记录预览。
2. `过去七天哪个房间最潮湿？`：按空间统计保留的有效湿度记录，回答必须说明“保留的有效记录”范围。
3. `昨天下午关闭空调之后，温度变化如何？`：解析动作事件，从动作前 10 分钟保留基线，再统计目标实体的属性变化。
4. `昨天晚上离开家时，有哪些设备还在运行？`：使用该时间 `at_or_before` 的环境快照解释运行状态。

响应始终包含问题解释、时间范围、记录引用、统计、快照、缺失范围和警告。没有记录时明确说“没有可用的保留记录”，不能据此声称现实中没有发生任何事情。未知模板返回 `422 / HISTORY_QUERY_UNSUPPORTED`，而不是低置信度猜测。

动作趋势中的 10 分钟基线是有意约束：设备动作事件通常发生在前后两个读数之间，只从事件时刻开始会把动作前读数排除，导致“变化”退化为单一值。该行为和限制已写入测试。

## 6. Reality Git 的有限能力

本阶段把所谓 Reality Git 限定为“保留快照的对比和可恢复性标注”，不是物理世界时光回滚。

`snapshot_diff` 返回：

1. baseline 和 target 的完整快照视图、本地时间和 `state_generated_at`。
2. 逐路径 `added`、`removed`、`changed` 差异。
3. `device_command_candidate`：可通过设备命令尝试恢复的状态投影候选。
4. `physical_observation`：温度、湿度等物理环境观测，只能新命令影响未来条件，不能真正回滚旧物理状态。
5. `system_projection`、`metadata_only` 和 `unknown`：系统投影、元数据或无法判定的差异不承诺可恢复。
6. `missing_data_paths` 和 `unchanged_count`。

所有 `physical_rollback_possible` 固定为 false。执行任何设备恢复都必须继续经过 Task System、Tool Registry、Safety Policy、确认和结果验证；快照 diff 本身不触发动作。

快照恢复性判断保持保守：只有路径附近存在 `sensor_type` 等相邻元数据时才归类为物理观测；未知值保持 `unknown`。这样不会把温度读数误当成灯状态，也不会把无法解释的投影宣传为设备可恢复。

## 7. 错误与安全

| 场景 | 行为 |
| --- | --- |
| 缺少或错误 API Token | `401` |
| naive datetime、空时区、非法时区或逆序范围 | `400 / HISTORY_VALIDATION_ERROR` |
| 不存在空间、实体、观测、事件、任务或快照 | `404 / HISTORY_NOT_FOUND` |
| 不支持的自然语言模板 | `422 / HISTORY_QUERY_UNSUPPORTED` |
| 两个 diff 快照同一条或不同环境 | `400` |
| Repository 数据库异常 | 包装为统一 Repository / History 错误，不泄露 SQL |

History API 只读，不提供 DELETE、PUT 或 POST 写入历史记录的入口。自然语言接口不能访问 Repository，也不能直接访问 Device Adapter；它只通过 HistoryService 的只读边界获取数据。

## 8. 测试与验收

`backend/tests/test_history_time_understanding.py` 覆盖：

1. API 缺失 Token 和错误 Token 拒绝。
2. Asia/Shanghai 本地日边界转换为 UTC，并识别区间内观测和缺失段。
3. 迟到、未来偏差和缺少采集时间的语义标记。
4. 空间严格后代查询和实体历史。
5. 空间趋势排序以及无效数值排除。
6. 快照查找警告、快照差异、设备可恢复候选和物理不可回滚分类。
7. Observation、Event、Task correlation 关联。
8. 四类自然语言示例基于保留记录回答。
9. 未知自然语言模板拒绝和 naive 时间校验。

工程验收要求：

1. 后端全量测试通过。
2. Ruff lint 和格式检查通过。
3. 不产生 Alembic 迁移；现有空库升级结果不受影响。
4. 所有回答能给出原始记录 ID 或聚合统计引用。
5. 数据缺失时响应包含缺口或警告。
6. 物理差异不输出可真正回滚的承诺。

## 9. 后续边界

本阶段不把历史答案自动写入 Memory，不生成永久事实，不总结用户偏好。未来如果要把历史结论纳入 ARS-03 Memory，必须重新走 Memory 的来源追踪、置信状态、用户确认、有效期、修订和授权规则。也不在本阶段扩展复杂意图解析、多语言查询或自由对话式历史分析。
