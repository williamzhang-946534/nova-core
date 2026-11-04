# 26. ARS-02 Final Acceptance Report

- 日期：2026-11-04
- 分支：`main`
- 基线提交：`a1b96f0`
- 验收范围：ARS-02.1 至 ARS-02.7 的 Spatial Environmental Intelligence 实现
- 最终结论：**未完全通过；软件主体条件可用，ARS-02 不应关闭**
- 阻塞原因：Environment Context v2 未投影空间级状态估计，导致 Context 与 State Estimation 不一致

## 1. Executive Summary

ARS-02 的核心工程链路已经形成：空间层级、实体与设备映射、Observation Schema、HA / Mock 统一观测管道、质量与时间语义、状态估计、空间查询、只读 Tool 和 Web Console 均已实现，并通过后端、前端、迁移和隔离环境回归。

最终验收不能标记为完全通过，原因如下：

1. **Environment Context v2 一致性失败**：当前读模型中有 32 条状态估计，其中 18 条为空间级状态；Context v2 只能看到实体级状态，18 条空间级状态全部缺失。
2. **隐私删除闭环未完全验收**：来源范围、属性策略、raw redaction、保留清理和默认隐藏已实现，但授权撤销后的可审计删除、衍生副本处理和备份边界没有完整执行记录。
3. **目标家庭规模性能压测未执行**：保留和采样策略已有代码与容量设计估算，但没有 20 / 50 / 200 传感器场景的 SQLite 长时间写入、WAL、锁等待和 P95 数据。
4. **真实 ESPHome / ESP32 验收未执行**：Mock 与 HA Demo 通过，不能替代真实 Wi-Fi、真实传感器时钟、真实断线重连和真实设备恢复。
5. **真实 AI Provider 自然语言会话未执行**：隔离进程实际使用 mock provider；确定性环境查询 Tool 路径通过，但真实模型生成质量未验收。

因此本报告采用“软件主体条件可用，最终验收未完全通过”的口径。ARS-02.7 之后应先修复 Context v2 缺陷并复验，再补齐或显式降级处理隐私、性能、真实硬件和真实 AI Provider 事项。

## 2. Acceptance Environment

验收使用独立临时 SQLite 数据库和独立端口，未修改用户日常数据库：

- Backend: `http://127.0.0.1:8001`
- Web Console: `http://127.0.0.1:5173`
- Mock Adapter: healthy
- Home Assistant Demo: healthy
- Home Assistant 写操作：关闭
- 隔离环境设备：7 台在线

隔离空间数据覆盖：

- 一个 Environment root space
- `home → floor → room → zone` 层级
- 两个房间：Living Space、Bedroom
- Living Space 下 Media Zone
- Bedroom 下 Sleep Zone
- HA light 与 6 台 Mock 设备完成空间归属

Alembic 空库完整升级到当前 head 通过。本验收涉及的关键迁移链为：

1. `07b82937bedb`
2. `7c2a9f10d48d`
3. `f3d2c8a67b01`
4. `b7d4e6c9a210`
5. `d41d8acd98a0`

重启恢复验证通过：同一 SQLite 文件重启后，观测、状态估计和当前读模型仍可查询和重建。

## 3. Final Acceptance Matrix

| 验收项 | 结论 | 说明 |
| --- | --- | --- |
| Spatial Model | 通过 | 支持家庭层级、路径、移动、停用、循环阻断和通用类型扩展 |
| Entity / Device 关联 | 通过 | Device 保留接入身份，Entity 表示系统认识对象，外部 ID 与内部 ID 分离 |
| Observation Schema | 通过 | 来源、主体、空间、raw / normalized、时间、质量、有效期、幂等键和外部 ID 语义完整 |
| Observation Pipeline | 通过 | HA / Mock 统一输入，完成校验、标准化、时间处理、去重、采样和质量标记 |
| State Estimation | 通过 | 七状态、输入观测、规则版本、生成时间、有效期和冲突候选可追溯 |
| Environment Context v2 | **失败** | 空间级状态估计未进入 Context 投影 |
| 空间 API 与只读 Tool | 条件通过 | API 与 Tool Registry 路径通过，但返回的 Context 数据受上述缺陷影响 |
| AI 自然语言环境查询 | 条件通过 | 确定性 Tool 查询与证据引用通过；真实 AI Provider 会话未执行 |
| Web Console | 条件通过 | 页面、空态、失败态和证据展示通过；空间状态完整性受 Context 缺陷影响 |
| 隐私与数据保留 | 未完全通过 | 策略、范围、raw 控制和清理已有；完整删除审计未验收 |
| 数据迁移 | 通过 | 空库升级、旧 `devices.area` 迁移和历史保留测试通过 |
| 备份恢复 | 未独立执行 | 备份服务存在，自动化回归通过；本验收未记录生产形态备份恢复演练 |
| SQLite 性能 | 未执行 | 目标规模压测和长期增长数据缺失 |
| 第一阶段安全链路回归 | 通过 | Tool Registry、Safety Policy、Task / Event 语义和 HA 写关闭保持 |
| Mock 验收 | 通过 | 覆盖观测、质量、状态估计、查询和重启恢复 |
| HA Demo 验收 | 通过 | 覆盖 HA Adapter、来源、时间、单位、状态和只读查询 |
| 真实 ESPHome / ESP32 | 未执行 | H1-H11 全部未执行，不能由软件链路替代 |

## 4. Architecture Review

### 4.1 Concept Boundaries

| 概念 | 当前实现结论 |
| --- | --- |
| Environment | Arvuno 运行范围和上下文所有者，通过唯一 `root_space_id` 指向空间树，不再自己承担楼层 / 房间管理 |
| Space | 现实空间层级，使用父子关系、路径闭包和类型字段，支持家庭树和未来工厂树配置 |
| Entity | 被系统认识的对象，当前由设备生成，后续可扩展到机器人、贵重物体等而不改写 Device 语义 |
| Device | 接入设备与外部技术身份，保留 adapter、外部 ID、能力和权限 |
| Observation | 一次实际观测，append-only，保留来源、时间、质量和 raw / normalized 差异 |
| State Estimate | 系统对当前状态的估计，可追溯输入观测和规则，与 Observation 不混用 |
| Event | 重要领域变化或动作，不因每条 Observation 自动产生 |
| Snapshot | 时点 Context 投影，不替代当前状态读模型 |
| Memory | 长期选择和归纳信息；本阶段未实现，也没有把 Observation 塞入 memories |

### 4.2 Module Dependency Graph

```text
Device Adapter
  ├─ Home Assistant Adapter
  └─ Mock Adapter
        ↓
Device Registry
  ├─ Device / external ID identity
  └─ Entity projection
        ↓
Observation Ingestion
  ├─ Schema validation
  ├─ Source / subject resolution
  ├─ Time provenance
  ├─ Unit normalization
  ├─ Deduplication and sampling
  ├─ Quality assessment
  └─ Persistence
        ↓
State Estimation Service
  ├─ Attribute-specific fusion rules
  ├─ Evidence links
  ├─ Current read model
  └─ Append-only history
        ↓
Environment Context v2
  ├─ Space tree projection
  ├─ Entity state projection
  └─ Quality and coverage summary
        ↓
Space / Environment APIs
  ├─ Read-only Tool Registry tools
  └─ Web Console
```
Event、Task、Tool Executor 和 Safety Policy 保持在原执行边界。Observation Pipeline 不直接调用 HA HTTP 客户端，Agent 不直接访问数据库或 Repository。

## 5. Database And Migration Review

### 5.1 Existing Tables

| 表 | ARS-02 后职责 | 结论 |
| --- | --- | --- |
| `devices` | 接入设备、外部身份、能力与权限；关联 Entity | 职责保留，`area` 不再作为空间查询入口 |
| `device_states` | 兼容当前投影；不新增 Observation 之外的状态历史 | 避免历史双写 |
| `device_capabilities` | 设备能力 | 保留 |
| `events` | 领域事件与审计 | Observation 只在符合事件语义时被引用，不自动逐条生成 Event |
| `environments` | 运行范围、root space 关联、Context snapshot 所有者 | 不重复承担空间层级 |
| `environment_snapshots` | v1 / v2 时点投影 | 保存版本和生成时间 |
| `memories` | 长期记忆 | 本阶段未滥用 Observation |
| `user_preferences` | UI / 用户偏好 | 合规事实由专门策略、授权和任务数据承担 |

### 5.2 New ARS-02 Data

新增核心数据覆盖：

- `spaces` 与空间路径 / 层级约束
- `entities`
- `entity_space_assignments`
- Observation source、attribute policy、consent、observation、ingestion batch
- State estimate history、input evidence link 和 current read model
- Context v2 snapshot version

已验证：

1. 旧 `devices.area` 可迁移到空间归属。
2. 设备移动通过归属区间保留历史。
3. 空间改名不重写历史观测。
4. 循环父子移动返回 `400 SPACE_CYCLE`。
5. 迁移不删除既有设备历史。

### 5.3 Backup Boundary

本次没有执行独立的“备份文件 → 新库恢复 → 全链路查询”演练。因此备份恢复只能记录为**未独立执行**，不能作为最终通过项。

后续复验应至少记录：备份时间、数据库大小、备份耗时、恢复耗时、迁移版本、恢复后 `PRAGMA integrity_check`、设备数、空间数、Observation 数和当前估计数。

## 6. Observation Contract Results

### 6.1 Schema

已实现语义：

- `observation_id`
- `source_id` / `source_type`
- Entity 或 Subject 归属
- `space_id`
- `attribute`
- `raw_value` / `normalized_value`
- `raw_unit` / `normalized_unit`
- `observed_at` / `received_at` / `processed_at`
- 采集时间来源与不确定性
- `quality_status` / quality issues
- validity / retention
- `correlation_id`
- `external_id`
- `dedupe_key`

`/api/observations` 默认不返回 raw；仅显式 `include_raw=true` 时返回。该行为符合最小化原则。

### 6.2 Source And Time Semantics

Mock Adapter：

- 无可靠设备采集时间。
- `observed_at = null`
- `observed_at_source = poll_clock`
- `quality_status = warning`
- 未把接收时间伪造成采集时间。

Home Assistant Demo：

- 使用 HA gateway state clock。
- 记录时间来源和不确定性。
- Demo 状态滞后时标记 warning / stale。
- 采集时间、接收时间和处理时间分离。

### 6.3 Quality, Deduplication, Sampling

自动化与隔离运行验证覆盖：

1. 同批次 / 同 payload 幂等。
2. 跨批次无变化数据按属性策略节流。
3. 温度、湿度等连续量使用最小间隔和变化阈值。
4. 延迟、未来时间、越界、类型错误和缺单位被标记或拒绝。
5. 来源缺失或停用不被静默接受。
6. raw 可按策略 redact。
7. 保留清理可分批执行。
8. Observation 不自动生成 Event。

设计容量估算仍以第 23 号文档为准：50 个传感器 1 分钟轮询时，不治理输入为每日 72,000 条、约 1.95 到 3.9 GB；启用采样后无变化轮询接近 0 条长期 Observation。该估算尚未由真实压测证实。

## 7. State Estimation Review

### 7.1 Status Semantics

以下状态均已实现并有测试覆盖：

- `observed`
- `derived`
- `inferred`
- `unknown`
- `stale`
- `unavailable`
- `conflict`

属性策略不是全局平均：

- 温度 / 湿度考虑位置、精度、采集时间和质量。
- 光照考虑测量位置和适用范围。
- 开关状态使用离散状态策略。
- PIR 触发只表示检测到活动，不把 `false` 直接推理为无人。
- 门窗多来源矛盾保留 conflict 和候选。

### 7.2 Traceability

非 unknown 估计可追溯：

- 输入 Observation ID
- source ID
- 属性规则和版本
- 生成时间
- 生效时间
- 有效期
- 被排除证据与原因
- conflict 候选

隔离环境中 Mock 温度 / 湿度保持新鲜时可输出 observed；HA Demo 滞后状态输出 stale，并把 `evidence_expired` 作为排除原因。数据不足时返回 unknown，不伪造确定状态。

## 8. Defect: Context v2 Omits Space States

### 8.1 Observed Result

验收时当前读模型共有 32 条状态估计，其中 18 条目标为 space。Context v2 输出中：

- Entity 状态可见。
- 18 条空间级状态全部缺失。
- Context quality 只统计被投影状态，因此不能作为完整一致性证据。
- 前端空间状态、AI 空间回答和只读环境 Tool 均受影响。

### 8.2 Root Cause

`backend/arvuno_core/environment/context_v2.py` 中状态索引使用三元 key：

```python
("space", space_id, "")
```

但构建空间节点时使用二元 key 查询：

```python
("space", space_id)
```

实体路径使用三元 key，所以实体状态可以显示；空间路径永远匹配失败。

### 8.3 Required Fix And Re-test

修复不得改变 State Estimation 语义，应统一 target key 并补充以下断言：

1. Context 空间状态与 current read model 完全一致。
2. 空间树每个节点的状态数量、状态值和有效期一致。
3. root、floor、room、zone 均可投影。
4. quality 计数包含空间级和实体级状态。
5. Snapshot v2 与即时 Context 一致。
6. 冲突、过期、不可用和未知不被过滤。
7. API、只读 Tool 和前端显示同一结果。

## 9. API, Tool, AI And Web Console

### 9.1 APIs

已实现并验收的主要能力：

- 空间层级查询
- 房间详情
- 房间当前状态
- 有限观测历史查询
- 设备空间归属查询
- 状态来源与证据查询
- 感知盲区 coverage 查询

`/api/devices`、`/api/environment` 和 `/api/system/status` 在隔离环境中保持设备与 Adapter 健康信息一致。

### 9.2 Tool Registry Boundary

以下只读能力均通过 Tool Registry / Tool Executor 执行：

- `list_devices`
- `get_device_state`
- `get_environment_state`

未发现 Agent 绕过 Registry 直接访问数据库、Repository 或 Adapter。

HA light 写尝试被拒绝：

- HTTP 409
- `STATE_CONFLICT`
- `Device write operations are disabled.`
- 设备状态未被写操作改变

### 9.3 Natural Language Query

确定性环境查询路径可以基于空间、观测和状态估计生成证据引用，并区分 observed / stale / unknown / inferred。

限制：

- 隔离验收后端实际使用 mock provider。
- `/api/chat` 返回 completed，但 intent 为 unsupported，回复为 offline mock provider 未配置该请求。
- 真实 DeepSeek / OpenAI-compatible provider 的自然语言组织能力未执行。

因此只能记录为“接口失败路径正常、真实 provider 未执行”，不能标记真实自然语言 AI 验收通过。

### 9.4 Web Console

实际浏览器验证通过：

- 空间树 home → floor → room → zone
- 楼层和房间列表
- 房间详情与空间路径
- 当前状态估计
- 观测来源、规则、时间与有效期
- observed / stale / unknown 标签
- coverage / blind 信息
- 证据抽屉
- Sleep Zone 空设备、空观测、unknown 和 blind 空态
- 后端不可达时的错误与重试状态

未开发 3D 地图、GIS 或数字孪生。页面验收通过，但其空间状态数据完整性受 Context v2 缺陷影响。

## 10. Privacy, Retention And Security

已实现或已有测试证据：

1. Observation source privacy scope。
2. 属性策略与 consent 数据。
3. raw storage 禁止时 redaction。
4. 普通 30 天、敏感 / invalid 7 天、batch 30 天保留策略。
5. 有界清理。
6. API 默认隐藏 raw。
7. Agent 只能通过只读 Tool 获取摘要。
8. HA 写操作保持关闭。
9. 第一阶段 Task、Tool、Safety、审计和事件语义回归通过。

未完全验收：

1. 授权撤销后当前读取、历史 Observation、估计链接、Event payload、Snapshot 和日志的删除完整性。
2. 删除任务分批、重试、取消和审计的端到端流程。
3. raw debug 访问审计完整性。
4. 备份中已删除数据的暴露边界与用户提示。

这些缺口不能被“表结构存在”或“单元测试通过”替代，最终隐私验收必须使用可审计的端到端记录。

## 11. Runtime Evidence By Source

### 11.1 Mock

| 项目 | 结果 |
| --- | --- |
| Adapter 健康 | 通过 |
| Device Registry | 通过 |
| Observation 输入 | 通过 |
| 来源身份 | 通过 |
| 采集时间未知语义 | 通过 |
| 单位标准化 | 通过 |
| warning 标记 | 通过 |
| State Estimation | 通过 |
| 查询与重启恢复 | 通过 |

### 11.2 Home Assistant Demo

| 项目 | 结果 |
| --- | --- |
| Adapter 健康 | 通过 |
| allowlist 同步 | 通过 |
| Entity / external ID 映射 | 通过 |
| gateway state clock | 通过 |
| 时间不确定性 | 通过 |
| 单位标准化 | 通过 |
| 滞后数据 warning / stale | 通过 |
| 只读查询 | 通过 |
| 写操作拒绝 | 通过 |

### 11.3 Real ESPHome / ESP32

以下项目全部**未执行**：

| 序号 | 项目 | 结果 |
| --- | --- | --- |
| H1 | ESP32 / ESPHome 连接 Wi-Fi | 未执行 |
| H2 | HA 发现设备 | 未执行 |
| H3 | HA 读取真实传感器 | 未执行 |
| H4 | Arvuno 获取真实设备与实体 | 未执行 |
| H5 | Observation Pipeline 接收真实观测 | 未执行 |
| H6 | 真实来源正确 | 未执行 |
| H7 | 真实时间戳正确 | 未执行 |
| H8 | 真实单位正确 | 未执行 |
| H9 | 状态估计刷新 | 未执行 |
| H10 | 断线状态 | 未执行 |
| H11 | 恢复重同步 | 未执行 |

## 12. Regression Results

| 检查 | 结果 |
| --- | --- |
| Backend full pytest | `228 passed`，1 个既有 Starlette TestClient deprecation warning |
| Ruff lint | 通过 |
| Ruff format check | 通过，188 个文件符合格式 |
| Frontend typecheck | 通过 |
| Frontend build | 通过，保留既有 Vite chunk size warning |
| Frontend format check | 通过 |
| Alembic empty DB upgrade | 通过 |
| Restart recovery | 通过 |
| Observation query | 通过 |
| State rebuild | 通过 |
| Migration tests | 通过 |
| Tool / Safety / Task / Event regression | 通过 |

ARS-01 的 191 个测试基线没有作为固定数字强行比较；当前代码基线的 228 个后端测试全部通过，并覆盖原有执行、安全、事件、设备控制、空间、观测和估计语义。

## 13. Risks And Open Items

| 编号 | 风险 / 缺口 | 等级 | 处理要求 |
| --- | --- | --- | --- |
| D1 | Context v2 空间状态投影缺失 | 阻塞 | 修复 key 不一致并复验 API / Tool / Console / Snapshot |
| D2 | 不同 `assignment_type` 的重复归属可能同时保留 open interval，导致重复 Context entity 或证据候选 | 高 | 明确唯一当前归属约束或查询收敛规则 |
| D3 | 隐私删除端到端审计未完成 | 高 | 补删除任务、衍生副本、日志和备份边界验收 |
| D4 | 目标家庭规模 SQLite 压测未执行 | 高 | 执行 20 / 50 / 200 传感器场景，记录写入、WAL、锁和 P95 |
| D5 | 真实 ESPHome / ESP32 未执行 | 高 | 有硬件后执行 H1-H11，不得开放无关写权限 |
| D6 | 真实 AI Provider 未执行 | 中 | 使用真实 provider 验证自然语言组织、未知解释和推断标注 |
| D7 | 备份恢复未独立演练 | 中 | 补备份、恢复和完整性检查记录 |
| D8 | 长时间断线重连和真实时钟漂移未验证 | 中 | 由真实硬件验收覆盖 |

## 14. Recommended Closure Sequence

进入 ARS-03 前建议按以下顺序处理：

1. 修复 D1 Context v2 空间状态投影，并运行针对性一致性测试。
2. 修复或明确 D2 当前归属 interval 约束。
3. 补隐私删除端到端验收。
4. 执行目标规模 SQLite 压测和保留清理测量。
5. 补真实 AI Provider 冒烟验收。
6. 补备份恢复演练。
7. 有真实 ESP32 后执行 H1-H11。
8. 复验完整回归、Web Console 和最终报告，确认无阻塞项后再关闭 ARS-02。

## 15. Final Verdict

ARS-02 的实现范围和工程质量已达到软件主体可复验水平，且未破坏第一阶段安全执行链路。但由于 Context v2 与 State Estimation 一致性失败，且隐私删除、目标规模性能、备份恢复、真实硬件和真实 AI Provider 未完全执行，**ARS-02.7 最终验收结论为：未完全通过**。

本报告不阻止针对缺陷的修复工作，但在 D1 修复并复验前，不应将 ARS-02 标记为完成，也不应基于 Context v2 做出空间级自动化决策或进入依赖完整环境记忆的 ARS-03。
