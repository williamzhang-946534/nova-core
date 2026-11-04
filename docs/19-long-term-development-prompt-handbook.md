# Arvuno 长期工程开发提示词手册（编号修正版）

版本：1.1  
当前基线：仓库 `Phase 10` 已完成验收；长期路线处于 `ARS-02.0 设计完成、待用户确认`。  
用途：作为 Codex 后续分阶段开发的提示词库。

---

# 0. 编号规则

项目采用两套独立编号体系，禁止混用。

## 0.1 仓库历史工程阶段

- `Phase 0` 至 `Phase 10`：指此前仓库内部的工程实施阶段。
- `Phase 10` 已完成验收。
- 所有历史报告、Git 记录和历史文档中的 `Phase 0–10` 编号必须保留，不得重新编号。

## 0.2 长期产品与技术路线

长期路线统一使用 `ARS`（Arvuno Roadmap Stage）：

| 编号     | 阶段                                         | 状态                |
| ------ | ------------------------------------------ | ----------------- |
| ARS-01 | Core Execution（基础智能控制）                     | 已完成               |
| ARS-02 | Spatial Environmental Intelligence（空间环境智能） | ARS-02.0 设计完成，待确认 |
| ARS-03 | World Memory（世界记忆）                         | 待开发               |
| ARS-04 | World Reasoning & Orchestration（世界推理与任务编排） | 待开发               |
| ARS-05 | Multimodal Perception（多模态感知）               | 待开发               |
| ARS-06 | Embodied Intelligence（具身智能）                | 待开发               |
| ARS-07 | Industrial Intelligence（工业智能）              | 待开发               |
| ARS-08 | Distributed World Intelligence（分布式世界智能）    | 远期规划              |

阶段内里程碑使用完整编号，例如 `ARS-02.0`、`ARS-02.1`。

## 0.3 跨阶段能力

不属于单一长期阶段的工作使用 `CROSS` 编号：

- `CROSS-01`：通用知识与工具路由。
- `CROSS-02`：外部数据源接入与治理。

## 0.4 文档与提示词规则

1. 不得把 `ARS-02` 称为仓库 `Phase 2`。
2. 不得修改历史 `Phase 0–10` 编号。
3. 阶段验收报告使用完整编号，例如 `ARS-02 Acceptance Report`。
4. 开发提示词使用完整里程碑编号，例如 `ARS-02.1`。
5. 新建文档前检查现有编号，禁止覆盖历史文件。
6. 更新路线图时分别记录仓库历史工程状态和 ARS 长期路线状态。
7. 下文出现的 `Phase 10`、`docs/16-phase10-acceptance-report.md` 等均指历史仓库记录，不得改名为 ARS。

---

# 第一部分：所有阶段通用的工程约束

以下约束适用于 ARS-02 至 ARS-08。每次开始新阶段或新里程碑时都必须遵守。

## 1. 架构约束

1. 以当前仓库代码、`AGENTS.md`、已确认的架构文档、第 18 号长期路线与架构差距分析为依据。
2. 不得为了实现未来功能而推翻现有架构。
3. 继续采用模块化单体，不提前拆分微服务。
4. 保留现有 FastAPI、React、TypeScript、SQLite、SQLAlchemy、Alembic 技术体系，除非有充分证据证明必须调整并获得用户确认。
5. 不提前引入消息队列、向量数据库、复杂多 Agent 框架或不必要的基础设施。
6. 所有业务模块必须遵循已确认的依赖边界。
7. Agent Runtime 不允许直接访问数据库、Device Adapter 或执行底层系统命令。
8. 所有现实设备和物理动作都必须经过 Tool Registry、Safety Policy、Tool Executor 和实际状态验证。
9. 新增功能优先复用现有设备、事件、任务、工具和安全体系。
10. 不将 Home Assistant 当作 Arvuno 的世界模型；它只是设备接入基础设施之一。

## 2. 开发约束

1. 开始前检查 Git 状态、项目结构和实际代码，不假设仓库仍然处于某个旧版本。
2. 不覆盖用户已有代码和未提交修改。
3. 不擅自删除现有数据表、接口、模块或测试。
4. 涉及数据库结构变化必须通过 Alembic 迁移。
5. 涉及现有数据必须提供兼容和迁移方案。
6. 不允许通过修改测试断言、跳过测试或降低安全要求来获得通过结果。
7. 每个里程碑必须实际运行测试，并提供执行命令和真实结果。
8. 测试无法执行时标记为未执行，不能标记为通过。
9. 不得把 Mock 测试结果当作真实硬件验收结果。
10. 不得将模型推断写成确定事实。
11. 不得把 API Key、Token、密码写入源码、日志或前端代码。
12. 不得擅自创建 Git 提交。

## 3. 架构与产品原则

Arvuno 长期定位：一个能够持续感知、理解、记忆、推理、规划和影响现实世界的智能系统。

长期技术资产包括：

- Reality Ontology：现实世界语义模型。
- Perception Engine：现实世界感知和观测处理。
- World Model：空间、实体、状态和关系。
- Memory System：现实世界与用户的长期记忆。
- Reasoning Engine：环境推理与预测。
- Planning Engine：目标规划和任务编排。
- Proactive Intelligence：主动智能。
- Active Perception：主动感知。
- Reality Adapter：设备、传感器、机器人和工业系统接入。
- Safety & Governance：安全、权限和人机协同治理。

当前以家庭为第一个实际环境，未来扩展到智元机器人和工业环境。

不强制登记家庭中的每件普通物品。优先管理已接入设备、传感器，以及对环境理解有实际价值的对象。

涉及摄像头、麦克风、精确位置等敏感感知能力，必须进行明确授权。普通非敏感环境数据可以在用户知情、可查看和可管理的前提下无感采集。

## 4. 阶段执行规则

每个阶段必须遵循：

检查当前工程 → 读取相关文档 → 分析依赖 → 提出实施计划 → 完成一个里程碑 → 自动化测试 → 人工验收 → 更新文档 → 停止。

不要一次性实现整个阶段。

每个里程碑结束后输出：

- 修改和新增文件。
- 数据库变化。
- API 变化。
- 模块依赖变化。
- 运行和测试命令。
- 测试实际结果。
- 已知问题。
- 下一里程碑建议。

完成一个里程碑后停止，等待用户确认。

---

# 第二部分：ARS-02 — Spatial Environmental Intelligence

目标：让 Arvuno 从认识设备，进化到认识一个真实空间。

本阶段的核心结果是：能够建立一个家庭的空间结构，接入环境观测数据，形成房间级状态，并明确说明状态来源、可信度、过期和未知信息。

本阶段不开发完整记忆系统、复杂任务规划、视觉、机器人或工业协议。

## ARS-02.0：架构设计与数据契约冻结

**本提示词必须首先执行，禁止直接写业务代码。**

当前状态：设计文档第 20 至 24 号已创建，等待用户检查和确认；确认前禁止进入 ARS-02.1 工程实现。

你现在开始 Arvuno 长期路线 `ARS-02：Spatial Environmental Intelligence`。

请先阅读并分析：

- `AGENTS.md`
- `README.md`
- `docs/00-project-overview.md`
- `docs/02-system-architecture.md`
- `docs/03-module-responsibilities.md`
- `docs/05-data-model.md`
- `docs/06-api-design.md`
- `docs/07-device-adapter-design.md`
- `docs/08-event-system-design.md`
- `docs/09-agent-and-tool-design.md`
- `docs/10-memory-system-design.md`
- `docs/11-security-and-permissions.md`
- `docs/12-testing-strategy.md`
- `docs/13-development-roadmap.md`
- `docs/14-decisions-and-tradeoffs.md`
- `docs/16-phase10-acceptance-report.md`（如果存在）
- `docs/18-long-term-architecture-gap-analysis.md`（如果存在）
- 项目中的长期技术路线和架构讨论文档（如果存在）。

必须检查当前实际代码，不允许只根据文档设计。

### 一、当前架构现状

已经实现：

- Device Adapter。
- Home Assistant Adapter。
- Mock Adapter。
- Device Registry。
- EventBus。
- Environment Context。
- Task System。
- Tool Registry。
- Tool Executor。
- Safety Policy。
- AI Provider。
- Agent Runtime。
- Web Console。
- 自动化与通知。

尚未实现完整的：

- Spatial Model。
- Observation Model。
- Observation Pipeline。
- State Estimation。
- 可信度和数据质量管理。
- 感知盲区与未知状态管理。

### 二、本次必须完成的设计

1. Spatial Model：家庭、楼层、房间、区域及父子空间关系。
2. Entity Model：设备、传感器、执行器，以及未来机器人和有价值物体的统一表示。
3. Observation Model：标准化观测数据结构。
4. Observation Pipeline：数据接收、标准化、去重、质量标记。
5. State Estimation：当前环境状态计算、来源追踪、冲突和未知状态。
6. Environment Context v2：基于状态估计生成环境摘要。
7. 环境查询 API、只读 Tool 和前端空间展示设计。
8. 传感器数据保留策略、存储量和 SQLite 性能设计。
9. 隐私、授权、数据删除和来源追踪设计。
10. ARS-02 测试策略和验收标准。

### 三、必须明确的概念边界

不能混淆以下对象：

- Environment：Arvuno 运行环境或环境上下文。
- Space：现实空间层级。
- Entity：被系统认识的对象。
- Device：接入的设备。
- Observation：一次实际观测。
- State Estimate：系统对当前现实状态的估计。
- Event：系统识别到的重要变化或动作。
- Snapshot：某个时点的状态投影。
- Memory：经过选择、归纳和管理的长期信息。

必须重点解决 `environments` 与未来 `space` 根节点之间的关系，不能让两者重复承担空间管理职责。

### 四、Observation Schema 必须包含

- observation_id
- source_id
- source_type
- entity_id 或 subject_id
- space_id（如适用）
- attribute
- raw_value
- normalized_value
- raw_unit
- normalized_unit
- observed_at
- received_at
- processed_at
- quality_status
- freshness / validity
- correlation_id
- external_id（如适用）

字段名称可以根据现有项目规范调整，但语义不能缺失。

如果设备本身不能提供可靠的采集时间，不允许伪造采集时间。必须明确记录时间来源和不确定性。

### 五、State Estimation 必须支持

- observed
- derived
- inferred
- unknown
- stale
- unavailable
- conflict

每个状态估计应能够追溯输入观测、计算规则、生成时间和有效期。

不同属性使用不同的融合策略。禁止将简单平均作为所有传感器的通用融合规则。

### 六、数据库设计要求

重点检查现有：

- devices
- device_states
- device_capabilities
- events
- environments
- environment_snapshots
- memories
- user_preferences

明确它们与新模型的关系。

不要因为新增 Observation 表就重复保存现有所有状态。

必须分析数据重复、双写不一致、SQLite 高频写入、索引设计、观测数据保留、历史迁移和空间移动后的历史追溯。

### 七、家庭和工业扩展要求

本阶段只实现家庭场景，但底层空间模型不要写死为家庭专用。

未来需要支持：

`home → floor → room → zone`

以及：

`factory → workshop → production_line → workstation`

不要现在开发工业模块，只保证通用模型可以扩展。

### 八、输出文件

建议新增：

- `docs/20-ars02-spatial-model-design.md`
- `docs/21-ars02-observation-model-design.md`
- `docs/22-ars02-state-estimation-design.md`
- `docs/23-ars02-migration-and-api-design.md`
- `docs/24-ars02-testing-and-acceptance.md`

如果当前编号已被占用，先检查编号，不得覆盖已有文档。

同时更新长期路线中的 ARS-02 进度说明。

### 九、本次禁止事项

本次只做架构与数据契约设计。

不得修改任何业务代码、数据库、API、依赖和前端页面。

不得提前开发 Memory、Planner、Active Agent、视觉、机器人和工业功能。

完成后输出：

1. 当前架构审查结果。
2. 每项数据模型的定义。
3. 现有数据库的迁移方案。
4. 模块依赖图。
5. API 草案。
6. 风险和未确定事项。
7. ARS-02 开发顺序。
8. 验收标准。

等待用户检查和确认，不要继续写代码。

---

## ARS-02.1：Spatial Model 工程实现

ARS-02 数据契约已经确认，现在开始实现 Spatial Model。

先阅读已确认的 ARS-02 设计文档、`AGENTS.md`、现有数据库模型和 Device Registry。

### 实现目标

建立家庭空间模型：

`Environment → Building / Home → Floor → Room → Zone`

允许根据已经确认的数据模型调整类型命名，但必须保留完整的父子关系和扩展能力。

完成：

1. 空间数据模型。
2. 空间 Repository。
3. 空间 Service。
4. 空间层级查询。
5. 空间创建、编辑、移动和停用 API。
6. 设备、传感器与空间的关联。
7. 原有 `devices.area` 数据迁移。
8. 空间路径和层级约束。
9. 防止循环父子关系。
10. 设备从一个空间迁移到另一个空间的处理。
11. 基础空间管理页面。
12. 空间相关测试。

### 重要限制

- 不登记所有普通家居物品。
- 不开发 GIS、3D 地图或数字孪生。
- 不允许删除已有设备历史。
- 空间改名和设备迁移不能破坏历史观测的来源。
- 不修改 Tool Executor 和 Safety Policy 的执行语义。
- 不提前开发 Observation Pipeline。

必须使用 Alembic 迁移，不允许直接重建已有数据库。

### 验收

可以建立家庭、楼层、房间和区域。

可以将现有设备正确分配到空间。

设备更换空间后，当前归属正确，历史数据仍然保留其原始空间关联或可追溯的归属历史。

运行数据库迁移测试、空间层级测试、数据迁移测试和原有回归测试。

完成后停止。

---

## ARS-02.2：Entity 与 Observation 数据模型

现在实现 ARS-02 的 Entity Model 和 Observation Model。

先检查已确认的 ARS-02 数据契约，不得重新定义已经确认的 Schema。

### 实现目标

1. 建立 Observation 数据模型。
2. 建立 Observation Repository。
3. 建立统一的实体与观测来源关联。
4. 将设备、传感器、执行器与空间模型建立关系。
5. 明确外部设备 ID 与 Arvuno 内部 ID 的对应关系。
6. 建立单位标准化机制。
7. 实现采集时间、接收时间和处理时间的区分。
8. 建立观测质量标记和有效期规则。
9. 提供基础观测查询能力。
10. 增加必要的 Alembic 迁移。

### 观测数据规则

必须区分原始数值、标准化数值、原始单位、标准单位、数据来源、数据采集时间、数据接收时间和数据处理时间。

对于没有可靠采集时间的来源，必须明确标记时间不确定性。

对于重复、延迟、异常或过期数据，不能静默当成正常数据。

不同传感器可以使用相同的标准属性，但必须保留其来源身份。

### 与现有系统集成

复用现有 Device Registry 和 Adapter。

不要直接让 Observation Repository 依赖 Home Assistant HTTP 客户端。

不要把原始 Observation 塞进 memories 或 events 表。

### 测试

覆盖正常观测、单位转换、不同时间来源、重复观测、延迟观测、异常数据、缺少单位、来源缺失、空间关联、数据持久化、迁移和重启恢复。

不要提前开发状态融合和 AI 推理。

完成后停止。

---

## ARS-02.3：Observation Pipeline

现在实现 Observation Pipeline。

目标是将 Home Assistant 和 Mock Adapter 的设备状态转换成统一的 Observation，并进入 Arvuno 自己的数据处理流程。

### 管道流程

Adapter / Sensor → Observation Ingestion → Schema Validation → Normalization → Deduplication → Quality Assessment → Observation Persistence → State Estimation Input。

### 实现要求

1. 定义统一的观测输入接口。
2. 支持 Home Assistant 作为数据来源。
3. 支持 Mock Adapter。
4. 实现观测字段校验。
5. 实现单位转换。
6. 实现时间处理。
7. 实现重复观测识别。
8. 实现过期和延迟观测处理。
9. 实现异常值标记。
10. 实现来源追踪。
11. 明确数据写入失败后的处理方式。
12. 限制轮询造成的无意义重复写入。
13. 对不同传感器属性配置合理的采样和保存策略。

### 数据量要求

不要将每一次设备轮询都无条件保存为长期原始记录。

需要根据传感器类型、采样频率、变化幅度和保留策略制定规则。

必须量化估算每分钟写入量、每日数据量、索引开销、预计数据库增长和数据清理后的存储规模。

继续使用 SQLite，不引入消息队列或时序数据库。

### 事件边界

Observation 不等于 Event。

不是每条观测都应该产生事件。

只有符合现有事件语义的重要变化才产生领域事件。

不得破坏原有 `task_started`、`tool_executed`、`task_completed` 和 `device_state_changed` 事件行为。

完成测试并停止。

---

## ARS-02.4：State Estimation 与 Environment Context v2

现在实现 Arvuno 的基础状态估计能力。

### 一、实现目标

1. 基于 Observation 生成当前状态。
2. 支持空间级状态。
3. 支持设备级状态。
4. 支持传感器级状态。
5. 支持多来源冲突。
6. 支持数据过期。
7. 支持来源不可用。
8. 支持未知状态。
9. 保存状态来源及计算规则。
10. 重建 Environment Context v2。

### 二、状态语义

必须支持：

`observed`、`derived`、`inferred`、`unknown`、`stale`、`unavailable`、`conflict`。

不能把 inferred 当成 observed。

没有足够数据时，宁可返回 unknown，也不能伪造确定状态。

### 三、状态融合

必须根据属性类型决定融合策略：

- 温度和湿度：考虑传感器位置、精度、采集时间和质量。
- 光照：考虑测量位置和实际观测范围。
- 开关状态：不能直接使用数值平均。
- 人体活动：PIR 触发只能说明检测到活动，不能直接代表持续有人。
- 门窗状态：多个来源冲突时必须明确标记。

第一版不需要机器学习模型或复杂贝叶斯框架。

先使用可解释、可测试的确定性规则。

### 四、Environment Context

现有 Environment Context 继续保留，但必须从 State Estimation 获取状态，而不是直接把设备状态当作完整环境事实。

生成房间级摘要：当前环境参数、相关设备状态、观测来源、状态质量、最近更新时间、未知信息、冲突信息和过期信息。

### 五、测试

必须覆盖多传感器冲突、数据过期、设备离线、异常读数、数据缺失、单位转换、状态重建和重启恢复。

验证 `/api/devices`、`/api/environment` 和 `/api/system/status` 的数据一致性。

不要提前开发完整 Memory 或 Reasoning。

完成后停止。

---

## ARS-02.5：空间查询、AI 环境理解与 Web Console

现在开始 ARS-02 的用户功能集成。

### 一、后端 API

按已确认的 API 设计实现：



- 空间层级查询。
- 房间详情。
- 房间当前状态。
- 房间观测历史的有限查询。
- 设备空间归属查询。
- 状态来源查询。
- 感知盲区查询。


只读查询必须使用 Tool Registry 中的只读工具。

不能允许 Agent 直接访问数据库或空间 Repository。

### 二、AI 自然语言查询

支持用户询问：

- 家里有几个房间？
- 客厅有哪些传感器？
- 现在客厅是什么情况？
- 哪个房间温度较高？
- 哪些房间缺少温度观测？
- 当前有哪些数据已经过期？
- 为什么系统无法确认窗户状态？

回答必须引用实际观测和状态估计结果。

AI 只能解释和组织数据，不得凭空编造房间状态。

对未知信息明确说明原因。

推断必须标记为推断。

### 三、Web Console

新增或扩展：

1. 家庭空间结构。
2. 楼层和房间列表。
3. 房间详情。
4. 当前环境状态。
5. 观测来源。
6. 数据质量。
7. unknown / stale / conflict / unavailable 状态。
8. 感知盲区。

不要开发完整 3D 地图。

不要重复实现 Home Assistant Dashboard。

### 四、验收

使用 Mock 和 HA Demo 完成自然语言查询。

检查前端正常、空数据、请求失败和未知状态显示。

验证没有绕过 Tool Registry。

运行完整前后端测试。

完成后停止。

---

## ARS-02.6：真实 ESPHome / ESP32 传感器验证

本里程碑仅在用户已经准备好 ESP32 和相关传感器时执行。

不要擅自购买设备。

### 目标

通过 ESPHome 将一台真实传感器节点接入 Home Assistant，再由 Arvuno 获取数据。

优先选择 ESP32 和温湿度传感器，可选光照传感器。

### 验证内容

1. ESPHome 设备能够连接 Wi-Fi。
2. Home Assistant 能够发现设备。
3. HA 能够读取真实传感器状态。
4. Arvuno 能够获取对应设备及实体。
5. Observation Pipeline 能够接收真实观测。
6. 数据来源正确。
7. 时间戳正确。
8. 单位正确。
9. 数据更新后 State Estimation 能够刷新。
10. 设备断线能够产生正确状态。
11. 设备恢复后可以重新同步。

真实设备写操作保持关闭。

不得为了验证传感器而开放无关控制权限。

### 验收

Mock、HA Demo 和真实 ESPHome 结果必须分别记录。

如果没有物理硬件，只完成软件接口验收，并将真实硬件验收标记为未执行。

完成后停止。

---

## ARS-02.7：ARS-02 完整验收

现在进行 Spatial Environmental Intelligence 最终验收。

检查：空间模型、实体关联、Observation Schema、Observation Pipeline、State Estimation、Environment Context v2、未知状态、数据质量、空间 API、AI 环境查询、Web Console、隐私和数据保留、数据迁移、第一阶段安全链路回归。

必须确认：

- 每条观测能够追溯来源。
- 采集时间和接收时间分离。
- 数据过期不会显示为实时状态。
- 多传感器冲突不会被隐藏。
- AI 推断不会变成真实观测。
- 房间设备迁移不会破坏历史。
- Environment Context 与 State Estimation 一致。
- 第一阶段 191 个后端测试的原有语义不回退；如果当前测试数量因后续正常变更而不同，以当前基线为准，比较测试覆盖和行为，不强行要求数量不变。

运行完整回归测试，生成 ARS-02 验收报告。

报告分别记录 Mock、HA Demo 和真实传感器结果。

未执行项目不得标记通过。

完成后停止，等待进入 ARS-03。

---

# 第三部分：跨阶段能力 CROSS

## CROSS-01：通用知识与工具路由

现在增强 Arvuno 的统一对话入口。

先检查现有 `/api/chat`、Agent Runtime、AI Provider、Tool Registry 和 Tool Executor。

当前行为包括：家庭查询和控制走工具；smalltalk 可能直接返回模型回答；unsupported 返回不支持，不创建任务，也不执行操作。

本次要保留这些安全边界，同时改善不同请求的路由能力。

### 一、请求分类

至少识别：

1. 通用知识问答。
2. 数学和计算。
3. 实时外部信息。
4. 家庭环境查询。
5. 家庭设备控制。
6. 复杂现实世界任务。
7. 不支持的请求。



### 二、处理方式

普通数学、历史、科学和日常知识问题可以由模型直接回答。

精确计算优先使用计算工具。

天气、新闻和其他实时信息只能通过真实外部数据源获取。

没有数据源时必须明确说明不可用，不能编造实时结果。

家庭问题继续调用 World Model 和相关工具。

设备控制继续经过原有安全链路。

### 三、外部只读工具

可逐步增加：

- Calculator。
- Weather Provider。
- Web Search Provider。
- Time Provider。
- 其他经过评估的只读数据工具。

所有外部工具必须进入 Tool Registry。

必须定义工具参数、数据来源、数据时间、错误处理、超时、权限范围、日志和审计。

天气工具不得擅自获取或使用未经授权的精确位置。

### 四、重要边界

普通知识问答不需要创建 Task。

只读外部查询不需要进入设备执行任务状态机，但需要有必要的调用记录。

物理设备操作必须保留 Safety Policy 和 Tool Executor。

模型输出仍然是不可信的候选请求。

### 五、测试

覆盖数学、通用知识、实时天气缺少数据源、外部数据源超时、家庭查询、设备控制、混合意图和 unsupported。

真实天气数据源测试与 Mock 测试分开。

不要为了通用问答破坏当前家庭设备控制链路。

完成后停止。

## CROSS-02：外部数据源接入与治理

现在建立 Arvuno 的外部只读数据源接入规范。

本任务可以在 CROSS-01 之后逐项实施，也可以根据实际需求选择某个 Provider，不要求一次接入所有数据源。

### 实现目标

1. 定义统一 External Data Provider 接口。
2. 定义数据源身份、提供方、更新时间和有效期。
3. 支持请求超时、有限重试和错误分类。
4. 支持缓存和缓存有效期。
5. 支持数据来源和引用信息保存。
6. 支持调用成本和频率限制。
7. 支持用户授权的地区或位置上下文。
8. 支持 Provider 不可用时的明确降级行为。
9. 支持用户查看和撤销相关数据权限。
10. 将外部数据返回结果与模型生成内容区分。

### 安全和事实性要求

- 不得把模型训练知识当作实时 API 数据。
- 不得伪造来源和更新时间。
- 不得擅自使用精确位置。
- 外部数据过期时必须明确标记。
- 搜索结果和天气结果必须保留来源。
- 外部数据不能直接触发现实设备控制，必须重新经过现有安全链路。

### 测试

覆盖 Provider 成功、超时、错误响应、缓存过期、来源缺失、位置未授权、频率限制和降级行为。

完成后停止。

---

# 第四部分：ARS-03 — World Memory

目标：让 Arvuno 理解现实世界的过去，并能利用历史积累知识。

Observation History 是现实数据记录，Memory 是经过筛选和组织的长期信息。不能把每条传感器读数都保存为长期记忆。

## ARS-03.0：记忆系统架构设计

现在开始长期路线 ARS-03：World Memory。

先检查 ARS-02 实际验收结果和当前数据库。

重点阅读：

- `AGENTS.md`。
- ARS-02 全部设计和验收文档。
- `docs/05-data-model.md`。
- `docs/08-event-system-design.md`。
- `docs/10-memory-system-design.md`。
- `docs/12-testing-strategy.md`。
- `docs/13-development-roadmap.md`。

本次先进行设计，不立即大规模写业务代码。

### 一、设计五类记忆

1. Working Memory：当前对话、环境和任务的短期工作上下文。
2. Episodic Memory：过去发生的事件、环境变化、任务和执行过程。
3. Semantic Memory：稳定的现实世界事实、空间关系和设备知识。
4. User Memory：用户明确表达并允许保存的偏好和长期信息。
5. Procedural Memory：经过验证的操作流程和可复用技能。

### 二、必须明确的边界

- Observation History 负责保存可追溯观测。
- Event History 负责保存重要事件。
- Task History 负责保存任务执行过程。


- Memory 负责形成有价值的长期知识。
- Conversation History 负责保存对话过程。

不能将这些表重复保存同一份信息而不明确职责。



### 三、记忆生命周期

设计创建、分类、来源追踪、检索、更新、纠正、过期、压缩、删除和用户授权。

AI 推断不得自动成为永久事实。

用户偏好必须有明确来源，允许用户查看、修改和删除。

程序记忆必须在流程经过测试和验证后才能成为可复用技能。

### 四、历史查询

支持按时间、空间、实体查询历史，关联设备事件和任务，查询环境快照，比较不同时间的空间状态和趋势统计。

### 五、技术约束

继续使用 SQLite 和关系查询。

不要提前引入向量数据库。

可评估 SQLite FTS 作为文本检索补充，但不得把全文搜索当成完整语义记忆能力。

### 六、输出

形成记忆分类、数据库关系、Memory Service、Repository、API、隐私和测试设计。

说明如何复用现有 memories、user_preferences、conversations、conversation_messages。

完成设计后停止，等待确认。

---

## ARS-03.1：Memory Service 实现

按照已经确认的 ARS-03 设计，实现 Memory Service。

### 实现内容

1. Memory 数据模型。
2. MemoryStore 接口。
3. Memory Service。
4. 记忆分类。
5. 来源追踪。
6. 记忆创建和查询。
7. 记忆更新与纠正。
8. 用户偏好管理。
9. 记忆生命周期。
10. 记忆删除。
11. 记忆有效期和清理。
12. 相关历史数据查询。
13. 记忆检索 API。
14. 必要的前端管理能力。

### 记忆来源规则

每条记忆应记录来源类型、来源记录 ID、创建时间、更新时间、置信状态、是否经过用户确认、有效期和适用范围。

推断、观测和用户明确陈述必须区分。

不得自动把一次临时对话升级为长期用户偏好。

不得自动把未验证的模型结论保存为现实世界事实。

### 记忆检索

根据问题类型检索用户偏好、空间事实、历史事件、任务记录和已验证程序。

检索结果必须提供原始来源引用。

### 测试

覆盖创建、检索、更新、冲突、用户纠正、过期、删除、来源追踪和权限。

完成后停止。

---

## ARS-03.2：环境时间理解与历史关联

现在增强 Arvuno 的时间理解能力。

在 Memory Service 和 Observation History 基础上实现：

1. 时间范围查询。
2. 空间历史查询。
3. 设备历史查询。
4. 环境快照。
5. 快照差异。


6. 趋势统计。
7. 历史事件关联。
8. 任务与环境变化关联。
9. 历史查询自然语言接口。

### 时间语义

必须正确处理 UTC 存储、用户本地时区展示、采集时间、接收时间、处理时间、时钟偏差、缺失时间和迟到数据。

### 回答示例

- 昨天客厅发生了什么？
- 过去七天哪个房间最潮湿？
- 昨天下午关闭空调之后，温度变化如何？
- 昨天晚上离开家时，有哪些设备还在运行？

回答必须基于真实记录。

如果历史数据缺失，要说明缺失范围。

### Reality Git 能力

在此基础上实现有限的环境快照对比：某个时刻的环境状态、当前与过去的差异、哪些状态发生变化、哪些变化可以通过设备恢复、哪些物理变化无法真正回滚。

不要把物理世界的状态恢复描述成真正的时光回滚。

完成后停止。

---

## ARS-03.3：ARS-03 最终验收

验证五类记忆的职责和实现、来源可追溯、事实与推断分离、用户记忆可管理、记忆删除真实生效、环境历史连续、时间查询正确、快照差异准确、历史查询可被 AI 正确使用、Memory 不破坏现有数据库和环境状态。

运行完整回归测试，生成 ARS-03 验收报告。

未实现的记忆能力必须如实标记。

完成后停止。

---

# 第五部分：ARS-04 — World Reasoning & Orchestration

目标：让 Arvuno 能够分析环境、理解目标、制定计划、主动发现值得处理的问题。

Reasoning、Planning、Proactive Intelligence 和 Active Perception 必须保持不同职责。

## ARS-04.0：架构设计

现在开始 ARS-04：World Reasoning & Orchestration。

阅读 ARS-02 空间和观测设计、ARS-03 Memory 设计，以及 `AGENTS.md`、`docs/09-agent-and-tool-design.md`、`docs/11-security-and-permissions.md`、`docs/12-testing-strategy.md`、`docs/13-development-roadmap.md`。

本次先设计，不直接实现全部功能。

分别设计：

1. Reasoning Engine。
2. Evidence Model。
3. Hypothesis Model。
4. Planning Engine。
5. Goal Model。
6. Plan Model。
7. Replanning。
8. Proactive Intelligence。
9. Active Perception Decision。
10. 用户授权和自主执行范围。

明确与现有 Agent Runtime、Task System、Tool Executor 的边界。

必须区分：

- Reasoning：分析现实情况。
- Planning：决定实现目标需要什么步骤。
- Task System：管理实际执行任务。
- Proactive Intelligence：判断什么时候应该主动提出建议或创建候选任务。
- Active Perception：判断当前信息不足时应从哪里获取更多观测。

输出完整模块边界、数据模型、流程图、API 和测试方案。

设计完成后停止。

---

## ARS-04.1：Evidence-based Reasoning Engine

现在实现基础环境推理能力。

### 实现目标

1. 读取 World Model。
2. 读取 Observation。
3. 读取环境历史和 Memory。
4. 建立 Evidence Bundle。
5. 生成候选原因。
6. 区分事实和假设。
7. 表示推断可信度。
8. 表示未知信息。
9. 形成结构化诊断结果。
10. 保存必要的诊断记录。

### 推理规则

必须区分直接观测到的事实、根据确定性规则得到的结果、AI 产生的假设、已经过验证的原因和仍然未知的信息。

不能把时间相关性直接描述成因果关系。

第一版可以采用规则和模型组合，不训练复杂预测模型。

不让 AI 直接修改 World Model 中的 observed 状态。

### 测试

使用历史数据回放、已知原因的 Mock 场景和错误数据测试推理质量。

完成后停止。

---

## ARS-04.2：Planning Engine 与 Goal Compiler

现在实现目标理解和任务规划。

### 一、目标模型

支持将自然语言目标转换为结构化目标：目标空间、期望环境状态、约束、可用资源、不允许发生的事情、目标优先级和预期完成条件。

### 二、规划系统

实现当前状态读取、目标状态计算、差异分析、可用工具和设备能力查询、前置条件验证、候选计划生成、执行步骤排序、依赖关系、风险估计、执行后条件、失败后的重新规划。

### 三、与 Task System 的边界

Planner 只生成和验证计划。

Task System 管理计划执行。

Tool Executor 是唯一设备操作入口。

禁止 Planner 直接操作设备。

### 四、运行模式

支持仅分析、生成建议、生成待确认计划、确认后执行、明确授权范围内的有限自动执行。

初始状态默认需要用户确认。

不能因为用户过去执行过相似任务，就自动扩大授权范围。

### 五、测试

覆盖目标理解、工具不可用、设备离线、任务依赖失败、执行失败、结果不满足目标和重新规划。

完成后停止。

---

## ARS-04.3：Proactive Intelligence

现在实现 Arvuno 主动智能系统。

主动智能不是定时聊天，而是识别值得用户关注或处理的现实情况。

### 实现内容

1. 主动事件触发。
2. 环境异常候选识别。
3. 建议优先级。
4. 建议去重。
5. 冷却时间。
6. 静默时间。
7. 通知频率限制。
8. 用户偏好管理。
9. 建议接受、拒绝和忽略反馈。
10. 主动建议质量评估。

### 主动行为分级

- Level 1：发现问题并记录。
- Level 2：主动向用户提出建议。
- Level 3：等待用户批准后生成任务。
- Level 4：在明确授权范围内有限自主执行。

不得默认开放 Level 4。

### 重要约束

不能因一次传感器触发就断言用户离开房间。

不能因一个异常读数就反复通知。

不能出现自动化规则互相触发的无限循环。

不能因用户忽略一次建议，就无限增加提醒频率。

### 测试

模拟异常、重复触发、静默时间、设备离线、错误推断、用户拒绝、授权到期等场景。

完成后停止。

---

## ARS-04.4：主动感知决策系统

现在实现 Active Perception Decision。

本阶段只实现主动感知的决策与观测请求机制，不实现机器人导航或持续摄像头采集。

### 实现目标

Arvuno 必须能够判断当前问题还缺少哪些信息、确定需要补充观测的对象和属性、查找已有观测来源、查询可用的感知能力、比较不同信息来源的成本和可信度、检查隐私授权、判断补充观测是否值得、生成观测请求、等待观测结果，并在获得结果后更新 World Model 和重新推理。

### 观测请求

需要包含观测目标、所属空间、需要获取的信息、期望来源、时间限制、隐私等级、用户授权要求和请求原因。

### 重要边界

当前没有摄像头或机器人时，不能伪造主动观察结果。

可使用 Mock Observer 验证决策流程。

涉及敏感观测必须经过明确授权。

本阶段不控制真实机器人。

完成后停止。

---

## ARS-04.5：ARS-04 最终验收

验证 Reasoning 的事实和假设分离、证据来源可追溯、Planning 与 Task System 边界清楚、Goal Compiler 能生成可验证目标、任务执行失败后能安全停止或重新规划、主动建议支持静默/去重/频率控制、用户授权不会被扩大、Active Perception 能发现信息缺口、敏感观测不会绕过权限，以及第一阶段安全体系没有回退。

形成 ARS-04 验收报告。

完成后停止。

---

# 第六部分：ARS-05 — Multimodal Perception

目标：让 Arvuno 获得图像、视觉、语音和音频等感知能力。本阶段不开发机器人本体导航和物理控制。

## ARS-05.0：多模态架构设计

现在开始 ARS-05：Multimodal Perception。

阅读现有 World Model、Observation、Memory、Reasoning 和 Active Perception 设计。

设计：

1. Image Observation。
2. Video Frame Observation。
3. Voice Input。
4. Speech-to-Text。
5. Text-to-Speech。
6. Audio Event Detection。
7. Multimodal Fusion。
8. Permission & Consent。
9. 数据保存与删除。
10. 视觉和语音模型 Provider。

所有模态都应该通过统一观测来源接口进入系统。

必须区分原始媒体、模型识别结果、结构化观测和最终推断。

敏感媒体默认不长期保存。

摄像头和麦克风访问需要明确授权和可见状态。

本次只出设计文档，不写功能代码。

---

## ARS-05.1：多模态观测接入

按照已确认的设计实现：

1. 图像上传与处理接口。
2. 视觉 Provider Adapter。
3. 图像内容结构化提取。
4. OCR 或视觉文字提取能力（仅在实际场景需要时）。
5. 语音输入接口。
6. Speech-to-Text Provider。
7. Text-to-Speech Provider。
8. 音频事件识别接口。
9. 多模态观测统一 Schema。
10. 来源和模型版本追踪。

### 要求

视觉模型识别出的对象必须标记来源和可信度。

不能将一次视觉识别结果自动变成永久物品身份。

不能默认对家庭进行全天候视觉监控。

语音和麦克风能力默认关闭或处于明确授权状态。

不得把敏感媒体写入普通日志。

涉及第三方云模型时，明确数据发送范围和保留策略。

先支持按需拍照、按需语音交互，不默认实现持续视频分析。

完成后停止。

---

## ARS-05.2：多模态融合与隐私治理

实现图像、语音、传感器和设备数据之间的关联。

例如：传感器检测到活动；用户拍摄一张照片；视觉模型识别到桌面存在物体；Arvuno 将这些信息关联到同一空间和时间范围。

要求：

1. 保留各模态的独立来源。
2. 保留模型版本。
3. 保留采集时间和处理时间。
4. 不直接把模型输出当成事实。
5. 处理重复或冲突观测。
6. 支持数据访问授权。
7. 支持敏感数据删除。
8. 支持用户查看当前启用的感知能力。
9. 支持撤销授权。
10. 支持敏感功能的审计记录。

完成后停止。

---

## ARS-05.3：语音交互体验

在多模态基础设施完成后，增加语音交互。

支持语音输入、语音识别、意图路由、通用问题回答、家庭环境查询、任务创建、执行确认和语音播报。

唤醒词可以作为独立模块。

不要因为实现语音，就默认打开持续麦克风采集。

必须区分待机、监听唤醒、语音输入、识别处理中、正在执行和正在播报。

对用户清晰展示麦克风状态。

完成后停止。

---

## ARS-05.4：ARS-05 最终验收

验证图像输入和识别、语音输入和输出、多模态来源关联、视觉识别结果不会伪装成事实、隐私授权、授权撤销、数据删除、云端与本地处理边界、故障和超时，以及与 ARS-02 世界模型兼容。

真实摄像头和麦克风测试独立记录。

完成后停止。

---

# 第七部分：ARS-06 — Embodied Intelligence

目标：将智元机器人接入 Arvuno，使它成为移动感知、语音交互和现实任务执行终端。



智元机器人是 Arvuno 的身体和重要入口，不是唯一的大脑。Arvuno Core 应该能够独立运行，即使机器人离线也不能影响家庭环境模型和其他设备管理。

## ARS-06.0：智元机器人接入架构设计

现在开始 ARS-06：Embodied Intelligence。

用户未来计划使用智元机器人作为 Arvuno 的移动感知与交互终端。

本次先进行架构设计，不要求实现真实机器人控制。

### 一、必须明确的系统边界

Arvuno Core 负责世界模型、记忆、推理、规划、权限和任务管理。

Robot Adapter 负责机器人连接、状态获取、高层能力调用、感知数据传输和任务反馈。

机器人本体控制系统负责实时运动控制、关节和电机控制、碰撞保护、急停和厂商安全机制。

Arvuno 不允许绕过机器人本体安全系统。

### 二、设计 Robot Capability Model


至少研究：

- navigate_to。
- observe。
- inspect。
- speak。
- listen。
- return_to_dock。
- charge。
- report_status。

只有目标型号实际支持的能力才能注册。

### 三、研究接入方式

根据最终机器人型号，研究智元官方 SDK、AimDK、ROS 2、HTTP RPC、语音接口、相机和深度数据、IMU、激光雷达和其他传感器。

不得凭空假设某个型号支持某项能力。

必须以对应型号的官方开发文档为依据。

### 四、设计安全机制

急停、禁入区域、导航边界、位置可信度、人工接管、任务中断、故障和离线处理、电量管理、运动权限、机械臂权限（如果型号具备）。

### 五、输出

Robot Adapter 架构、Capability Schema、API、状态模型、权限设计和仿真测试方案。

本次不写真实机器人控制代码。

---

## ARS-06.1：Robot Adapter 与 Mock Robot

在机器人硬件到位之前，实现统一 Robot Adapter 和 Mock Robot。

### 实现内容

1. Robot 接口。
2. Robot Registry。
3. Robot Capability Model。
4. Robot State Model。
5. Robot Location / Pose Model。
6. Robot Task Request。
7. Robot Event。
8. Mock Robot。
9. 连接和断线处理。
10. 任务状态同步。

### 重要边界

机器人与普通智能设备的行为不同，必须使用独立 Robot Adapter。

可以复用基础 Adapter 设计理念，但不能把导航、运动和急停当成普通开关动作。

Mock Robot 必须支持移动成功、导航失败、定位丢失、低电量、任务取消、设备离线、人工接管和急停状态。

Arvuno Core 只能调用高层能力，不能直接控制关节或电机。

完成后停止。

---

## ARS-06.2：智元真实机器人接入

只有在用户明确提供或确认具体智元机器人型号和开发环境后才能执行。

首先阅读该型号的官方开发文档。

不得将其他型号的 SDK 接口直接套用。

### 实现目标

1. 实现对应型号的 Robot Adapter。
2. 连接机器人。
3. 获取机器人状态。
4. 获取位置和定位信息。
5. 注册实际可用的能力。
6. 支持高层导航任务。
7. 支持移动观察。
8. 支持感知数据传回 Arvuno。
9. 支持任务反馈。
10. 支持人工接管。
11. 支持急停和故障状态同步。

### 安全要求

实时运动控制由机器人本体和厂商安全系统负责。

Arvuno 不直接控制关节、电机。

所有任务都必须经过授权和风险判断。

任何故障、定位异常、通信中断或安全停止都必须终止相关高风险任务。

第一阶段先实现只读状态和低风险导航。

机械臂抓取等能力单独审批、单独设计、单独验证。

### 验收

Mock Robot 和真实机器人测试分开记录。

没有实际机器人时不能宣称真实接入完成。

完成后停止。

---

## ARS-06.3：移动主动感知

现在让 Arvuno 使用机器人完成主动感知任务。

场景示例：用户说“帮我看看客厅现在是什么情况”。

Arvuno：

1. 判断是否缺少必要信息。
2. 检查机器人是否可用。
3. 查询机器人感知能力。
4. 生成移动观察计划。
5. 检查隐私和空间权限。
6. 获取用户确认（必要时）。
7. 请求机器人导航到目标位置。
8. 收集图像和传感器信息。
9. 生成 Observation。
10. 更新 World Model。
11. 返回有证据支持的环境报告。

机器人不能因为收到观察任务，就擅自进入未经授权的房间。

完成后停止。

---

## ARS-06.4：ARS-06 最终验收

验证机器人独立 Adapter、Robot Capability 注册、定位和状态同步、导航任务、主动观察、感知数据来源、用户授权、急停、人工接管、离线恢复，以及 Arvuno Core 在机器人离线时仍能正常运行。

完成后停止。

---

# 第八部分：ARS-07 — Industrial Intelligence

目标：让 Arvuno 从家庭环境扩展到工厂环境。

本阶段复用 Reality Ontology、World Model、Observation、Memory、Reasoning、Planning 和 Safety。不复制一套完全独立的工业 AI 系统。

工业环境第一阶段以只读接入、生产环境理解、可视化和诊断建议为主。

## ARS-07.0：工业架构设计

现在开始 ARS-07：Industrial Intelligence。

请基于家庭环境已经验证的 Reality Model，设计工业领域扩展。

### 一、空间层级

支持：

`Factory → Building → Workshop → Production Line → Work Cell → Equipment`

允许根据实际工业场景增加子类型。

### 二、工业实体

设计 Equipment、Sensor、Controller、Robot、Workstation、Production Line、Material、Batch、Order、Process。

不要要求所有工业对象都在第一阶段实现。

### 三、技术接入

研究 OPC UA、Modbus TCP / RTU、MQTT、PLC、SCADA、MES、ERP，说明不同系统的接入职责和限制。

### 四、工业观测

设计工业数值单位、采集频率、数据质量、设备状态、报警、运行模式、产量、能耗和生产批次上下文。

### 五、安全边界

Arvuno 不替代 PLC、SCADA、安全联锁或急停系统。

初期禁止直接控制生产设备。

所有工业 Adapter 默认只读。

输出领域模型、Adapter 设计、数据契约、安全方案和测试设计。

本次只做设计，不写生产控制代码。

---

## ARS-07.1：工业 Adapter 与数据读取

在经过架构确认后，实现工业只读接入基础。

优先使用 Mock 工业数据源。

如果已有真实设备或测试环境，只允许经过用户批准的只读接入。

### 实现内容

1. Industrial Adapter Interface。
2. 统一工业设备实体。
3. 工业 Observation 映射。
4. 单位标准化。
5. 工业设备状态映射。
6. 设备层级关联。
7. 报警事件。
8. 数据来源追踪。
9. 连接异常处理。
10. 工业数据质量检查。

不得将 PLC 或工业控制器当成普通 Home Assistant 设备直接操作。

不得将未经确认的工业语义硬编码到家庭设备模型中。

完成后停止。

---

## ARS-07.2：工业环境理解与诊断

在工业数据接入基础上，增强工业 World Model。

支持工厂空间状态、生产线设备状态、设备运行趋势、能耗统计、设备异常分析、报警关联、维护建议和生产过程上下文查询。

初期只做只读诊断、运行状态理解、异常分析、趋势统计和维护建议。

禁止 AI 直接改变生产控制参数。

任何工业写操作都需要独立工业安全方案、人工审批和受控接口。

完成后停止。

---

## ARS-07.3：ARS-07 最终验收

验证工业空间模型、设备层级、实际实现的 OPC UA / Modbus / MQTT Adapter、数据标准化、工业 Observation、报警、设备状态、生产上下文查询、能耗统计、异常诊断、只读权限、网络隔离和安全审计。

真实工业环境与 Mock 环境必须分开报告。

完成后停止。

---

# 第九部分：ARS-08 — Distributed World Intelligence

目标：让多个独立现实环境之间能够在明确授权下共享必要的信息和任务。

例如家庭 Arvuno、工作室 Arvuno、工厂 Arvuno、移动机器人和独立边缘设备节点。

它们拥有独立的 World Model，但能够在必要时进行安全协作。

本阶段非常远期，不应在当前个人单机项目中提前建设。

## ARS-08.0：分布式架构设计

现在开始 ARS-08：Distributed World Intelligence。

本阶段先进行可行性与架构设计。

### 一、设计每个环境的独立身份

包括 Environment ID、Node ID、Identity、Capability、Trust Level、Permission Scope、Owner 和 Version。

### 二、节点协作

研究多环境注册、节点发现、能力查询、状态同步、事件同步、任务委派、任务状态反馈、离线运行、重新连接和数据冲突处理。

### 三、安全

设计节点认证、端到端加密、密钥轮换、访问范围、最小权限、撤销授权、审计和数据最小化。

不同环境之间不能默认共享全部记忆、家庭数据和设备权限。

### 四、分布式任务

任务需要明确委派者、执行节点、权限范围、任务有效期、取消机制、结果回传、超时、重试和故障处理。

### 五、输出

只生成架构评估和原型方案。

不要直接将现有模块化单体拆成微服务。

不要现在实现复杂同步协议。

完成后停止。

---

## ARS-08.1：分布式节点原型

只有多个独立环境确实存在，并且用户确认进入实施阶段后执行。

先建立两个隔离的 Mock World Node。

实现节点身份、节点认证、能力描述、有权限的状态查询、有权限的任务委派、任务回执、节点离线、数据同步、冲突处理、审计和授权撤销。

先使用 Mock Node，不连接真实家庭或工业环境。

完成安全测试后停止。

---

## ARS-08.2：ARS-08 最终验收

验证节点身份和信任、权限隔离、数据加密、状态同步、事件去重、任务委派、节点离线、断线重连、任务取消、授权撤销、数据冲突、审计和兼容性。

完成后输出 ARS-08 验收报告。

不得将未实现的分布式能力标记为通过。

完成后停止。

---

# 第十部分：通用开发模板

## TEMPLATE-NEXT：继续当前阶段

当前里程碑已经完成并经过检查。

请重新读取：

- `AGENTS.md`。
- 当前 ARS 阶段设计文档。
- 当前 ARS 阶段开发路线。
- 最新验收报告。
- 当前 Git 状态。

确认当前里程碑没有遗留的阻塞问题。

然后只实施当前 ARS 阶段的下一个未完成里程碑。

要求：

1. 不重做已经通过验收的功能。
2. 不改变已经确认的架构契约。
3. 不提前进入下一 ARS 阶段。
4. 不引入未批准的依赖和基础设施。
5. 不覆盖用户未提交修改。
6. 不降低现有安全要求。
7. 完成后运行相关测试和必要的全量回归。
8. 更新开发文档和阶段进度。
9. 输出实际修改、测试和剩余问题。
10. 完成后停止等待用户验收。

如果发现前一里程碑存在实质性缺陷，先报告并修复，不允许在有阻塞问题的基础上继续堆功能。

---

## TEMPLATE-ACCEPTANCE：当前 ARS 阶段最终验收

现在对当前 ARS 阶段进行最终验收。

请先读取：

- `AGENTS.md`。
- `README.md`。
- 当前 ARS 阶段所有设计文档。
- 当前 ARS 阶段所有开发文档。
- 当前 ARS 阶段测试策略。
- 所有历史验收报告。

以实际代码和可重复测试结果为依据进行验收。

### 自动化检查

运行：

1. 后端全量测试。
2. 前端全量测试。
3. Python 格式检查和静态检查。
4. TypeScript 类型检查。
5. 前端构建。
6. 架构边界测试。
7. 数据库迁移测试。
8. 数据完整性测试。
9. 安全测试。
10. 当前 ARS 阶段新增能力专项测试。

### 真实环境检查

真实 HA、ESPHome、视觉、机器人或工业环境测试，必须说明实际接入了什么设备、运行了什么操作以及获得了什么结果。

Mock 不能冒充真实环境。

### 报告要求

必须分别列出：

- 已通过。
- 未通过。
- 未执行。
- 需要人工操作。

明确说明当前 ARS 阶段是否正式完成、哪些核心能力已经实现、哪些只是接口或设计、哪些依赖真实硬件、哪些技术债仍然存在、是否影响下一阶段，以及是否需要修改长期路线。

不得通过降低测试标准或修改测试断言掩盖问题。

生成正式 ARS 阶段验收报告。

完成后停止。

---

# 第十一部分：长期路线总表

| 编号     | 阶段                                 | 主要能力       | 核心资产                                                                               |
| ------ | ---------------------------------- | ---------- | ---------------------------------------------------------------------------------- |
| ARS-01 | Core Execution                     | 基础智能控制     | Device Adapter、Tool、Task、Safety                                                    |
| ARS-02 | Spatial Environmental Intelligence | 空间环境感知     | Reality Ontology、Perception Engine、World Model                                     |
| ARS-03 | World Memory                       | 环境记忆       | Memory System、Temporal Model                                                       |
| ARS-04 | World Reasoning & Orchestration    | 推理、规划、主动智能 | Reasoning Engine、Planning Engine、Proactive Intelligence、Active Perception Decision |
| ARS-05 | Multimodal Perception              | 多模态感知      | Vision、Speech、Multimodal Observation                                               |
| ARS-06 | Embodied Intelligence              | 具身智能       | Robot Adapter、Robot Capability Model、Mobile Perception                             |
| ARS-07 | Industrial Intelligence            | 工业智能       | Industrial Ontology、Industrial Adapter、Industrial Reasoning                        |
| ARS-08 | Distributed World Intelligence     | 分布式世界智能    | Node Identity、Trust、Synchronization、Delegation                                     |

跨阶段能力：

- CROSS-01：通用知识与工具路由。
- CROSS-02：外部数据源接入与治理。

贯穿所有阶段的基础资产：

- Safety & Governance。
- Data Quality & Provenance。
- Evaluation & Simulation。
- Human-in-the-loop。
- Reliability & Operations。
- Observability & Cost。
- Device / Entity Lifecycle。

最终目标：

Arvuno 能够持续感知现实世界，建立空间和实体模型，记住过去发生的事情，理解环境变化，推理和预测现实状态，主动发现问题，主动获取缺失信息，制定并执行任务，在授权范围内控制不同设备、机器人和工业系统。

它不依赖某一个大模型、某一个智能家居平台或某一个机器人品牌。

它积累的是对现实世界的持续认知能力、安全执行能力和跨设备协作能力。
