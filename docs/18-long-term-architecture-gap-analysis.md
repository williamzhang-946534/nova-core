# 18. 长期路线与架构差距分析

- 分析日期：2026-11-02
- 分析对象：Arvuno Core 当前仓库，以及《Arvuno 长期技术路线与架构讨论结果》
- 分析性质：架构与产品可行性审查；本文不改变任何业务代码、数据模型、API 或依赖
- 仓库基线：`6fddf1b Complete Phase 10 browser acceptance`

## ARS-02.0 进度记录

- 2026-11-02：`ARS-02.0：架构设计与数据契约冻结`设计已完成，新增第 20 至 24 号设计文档。
- 当前状态：**等待用户检查和确认**；尚未开始任何 ARS-02 业务代码、数据库迁移、API、依赖或前端实现。
- 设计范围：Spatial Model、Entity Model、Observation Model、Observation Pipeline、State Estimation、Environment Context v2、迁移与 API 草案、隐私删除、SQLite 性能、测试策略和验收标准。

## 1. 总体结论

| 问题 | 结论 | 判断 |
| --- | --- | --- |
| 长期路线是否与现行架构兼容 | **兼容** | Phase 1 建立的 Adapter、Tool、Safety、Task、Event、Repository 边界可以继续承载后续扩展，不需要推翻重构或改为微服务 |
| Phase 2 是否可行 | **可行，但属于中等偏高复杂度** | 难点不是接入传感器，而是空间、观测、状态估计、数据质量和来源契约 |
| 未来是否有竞争力 | **有条件成立** | 竞争力不来自 DeepSeek、Home Assistant、React 或某个机器人品牌，而来自持续积累的空间模型、真实观测数据、记忆、推理规划、安全执行和评估体系 |
| 是否有现实存在意义 | **有** | 它定位为“能理解同一个现实空间并在授权范围内安全行动的本地系统”，填补通用 AI 缺少现实上下文、智能家居平台缺少推理记忆、机器人平台缺少跨设备大脑之间的空档 |
| 当前最大风险 | **数据契约延后** | 若继续把 HA 状态、领域事件和 Environment Context 混当作世界模型，Phase 3 Memory 和 Phase 4 Planning 将被迫大规模返工 |

更具体地说：当前系统已经可靠回答“我怎么安全地控制设备”，但还不能可靠回答“这个房间现在是什么状态、依据是什么、哪些信息未知、数据是否可信”。Phase 2 的任务就是把后者补上。

## 2. 分析口径与阶段编号

本文使用长期路线中的 Phase 1-8 编号：

| 编号体系 | 含义 |
| --- | --- |
| 仓库文档 Phase 0-10 | 第一阶段 Core Execution 的内部实施阶段，Phase 10 已完成验收 |
| 长期路线 Phase 1-8 | 跨多年产品阶段；长期路线 Phase 1 大致对应仓库第一阶段的 Phase 10 完成状态 |

本文以实际代码为准判断当前能力，以已确认的长期路线判断目标方向。以下概念不做等同：

1. Home Assistant 是设备接入基础设施，不是 World Model。
2. Environment Context 是当前设备与传感器摘要，不是完整 Spatial World Model。
3. Event / Task History 是可审计历史，不是完整 Memory System。
4. Task System 是任务生命周期与执行管理，不是自主 Planner。
5. AI 输出是候选意图或推断，不能直接变成事实或权限。

## 3. 当前实际能力盘点

| 能力 | 文档状态 | 代码与数据状态 | 结论 |
| --- | --- | --- | --- |
| AI Provider 与自然语言入口 | 已设计并验收 | `agent_runtime/`、`ai/`、`/api/chat`、`provider_logs` 已实现；模型输出经 Pydantic 校验 | 已实现，但当前只支持有限意图和简单候选计划 |
| Device Adapter | 已设计并验收 | `devices/interface.py`、Home Assistant Adapter、Mock Adapter、Device Registry 已实现 | 已实现，可作为 Phase 2 观测来源和未来更多 Adapter 的基础 |
| 设备状态投影 | 已设计并验收 | `devices`、`device_states`、`device_capabilities` 已实现，包含 `area` 字符串和 `observed_at` | 部分满足实体模型；缺少空间外键、单位、质量、来源观测等语义 |
| 事件系统 | 已设计并验收 | `events` 表、进程内 EventBus、事件查询和保留策略已实现 | 已实现领域事件；不应直接扩展为观测主存储 |
| Environment Context | 已设计并验收 | `environments`、`environment_snapshots`、`environment/context.py` 维护设备与传感器当前摘要 | 部分实现；是 Context，不是空间层级或状态估计系统 |
| 安全执行 | 已设计并验收 | Tool Registry、Safety Policy、确认、审计、验证、执行记录已实现 | 已实现，是长期路线中最有价值的资产之一 |
| Task System | 已设计并验收 | Task / TaskStep 状态机、顺序执行、取消、超时、等待确认、事件已实现 | 已实现执行管理；不是 Planner |
| 自动化与通知 | 已设计并验收 | 少量上下文规则、任务失败通知、站内通知已实现 | 部分实现主动智能；不是通用自动化平台 |
| Web Console | 已设计并验收 | 设备、环境、事件、对话、任务、自动化、通知、设置页面已实现 | 已实现第一阶段控制台；缺少空间、观测、未知状态视图 |
| 会话 | 有表结构 | `conversations`、`conversation_messages` 存在，但未发现 Conversation Service 或完整会话生命周期实现 | 仅有数据基础 |
| Memory | 有设计文档 | `memories`、`user_preferences` 表存在；未发现 MemoryStore / Memory Service 实现 | 仅有设计和表结构 |
| Spatial Model | 长期路线已明确 | 设备只有 `area` 字符串，区域靠 `area_summary()` 聚合 | 未实现 |
| Observation Model | 长期路线已明确 | 无独立 Observation 表、单位标准化、采集 / 接收时间分离、质量与来源链 | 未实现 |
| State Estimation | 长期路线已明确 | Environment Context 直接保存最新状态或传感器值；无多源融合、冲突、过期、置信度和来源记录 | 未实现 |
| Reasoning / Planner | 长期路线已明确 | Agent 可提出受约束候选计划；无证据推理、目标编译、资源规划和重规划 | 未实现 |
| 语音、视觉、机器人、工业、分布式 | 长期路线已明确 | 仅有方向与约束，无业务实现 | 未实现，且当前不应提前实现 |

## 4. 长期 Phase 1-8 映射

| 长期阶段 | 当前匹配程度 | 现有基础 | 主要差距 |
| --- | --- | --- | --- |
| Phase 1 Core Execution | 已完成 | 设备接入、AI 入口、候选计划、Task、Tool、Safety、验证、审计、控制台、自动化通知 | 保持稳定，不因新阶段破坏安全链路 |
| Phase 2 Spatial Environmental Intelligence | ARS-02.0 设计完成，待用户确认后进入 ARS-02.1 | Device Registry、事件轮询、Environment Context、HA / Mock、控制台 | 空间层级、实体归属、观测、状态估计、未知状态、数据质量、空间查询和展示仍待实现 |
| Phase 3 World Memory | 仅有准备 | `events`、`device_states`、`environment_snapshots`、`memories`、设计文档 | 观测历史、时间序列、记忆分类、来源、保留、压缩、用户纠正与删除 |
| Phase 4 World Reasoning & Orchestration | 少量基础 | Agent 候选计划、Task 状态机、上下文自动化、安全执行 | 证据推理、不确定性、目标编译、规划引擎、主动建议排序、主动感知决策、重规划 |
| Phase 5 Multimodal Perception | 未开始 | AI Provider 与 Event 模型可提供部分扩展点 | 图像、语音、音频事件、多模态关联、敏感能力授权和数据保留 |
| Phase 6 Embodied Intelligence | 未开始 | Adapter 思想与安全执行链路可复用 | Robot Capability Model、独立 Robot Adapter、位置 / 地图 / 定位、任务状态、急停和人工接管 |
| Phase 7 Industrial Intelligence | 未开始 | 空间 / 实体 / 观测若保持通用，可做领域扩展 | 工业资产层级、工艺上下文、OPC UA / Modbus / MQTT 等接入、只读诊断和安全边界 |
| Phase 8 Distributed World Intelligence | 未开始 | 模块化单体与本地数据库适合先单环境运行 | 多实例身份、信任、授权、断网自治、同步、冲突处理和任务委派 |

## 5. 八个核心能力边界

| 能力域 | 当前状态 | 边界判断 |
| --- | --- | --- |
| Perception | 部分实现 | 已有 Adapter、轮询、事件和状态记录，但缺少独立 Observation Pipeline 与质量管理 |
| World Model | 部分实现 | Environment Context 只描述当前设备 / 传感器摘要；需要空间、实体、关系、状态估计和未知状态 |
| Memory | 仅有设计 | 表结构不能替代记忆服务；Phase 2 必须保住可追溯观测，Phase 3 再建完整记忆体系 |
| Reasoning | 未实现 | 应输出证据、假设、置信度和未知项；不能把相关性写成因果，更不能把模型输出写成事实 |
| Planning | 少量基础 | 当前 Agent 的候选计划是模型建议；未来 Planner 应生成可检查、可重规划的目标计划，仍交给 Task System 执行 |
| Proactive Intelligence | 部分实现 | 已有少量事件规则与通知，但缺少优先级、频率控制、静默策略和主动建议质量评估 |
| Active Perception | 未实现 | 需要能识别信息缺口并选择观测来源；Phase 2 可先表达盲区，Phase 4 再决策“是否值得补充观测” |
| Action & Governance | 已实现第一阶段 | 安全权限、确认、执行验证、审计和人工取消是现有系统最强边界，应继续保持唯一物理执行入口 |

这些能力域应继续保持模块化单体中的清晰包 / 端口边界，不应拆成八个微服务。

## 6. 横向基础能力缺口

| 横向能力 | 当前程度 | Phase 2 前后必须补的内容 |
| --- | --- | --- |
| Reliability & Operations | 较好 | 健康检查、轮询、断线重连、备份、迁移和错误契约已有验收；需评估观测写入量、后台任务资源和长期存储增长 |
| Security & Privacy | 第一阶段较好，未来不足 | 现有 API Token、工具权限、设备白名单和确认链路可靠；空间、传感器、摄像头、麦克风、机器人、工业数据需要分级授权和生命周期 |
| Data Quality & Provenance | 最弱 | 必须补采集时间、接收时间、来源、单位、精度、校准、新鲜度、重复、延迟、异常和冲突语义 |
| Evaluation / Simulation / Replay | 后端基础较好 | Mock Adapter 与测试充分；需新增传感器冲突、漂移、离线、异常值、空间迁移和状态估计回归场景 |
| Human-in-the-loop | 较好 | 已有确认、拒绝、取消和任务审计；未来需增加自主范围、静默时段、建议频率和人工接管 |
| Compatibility & Lifecycle | 部分实现 | 设备发现、同步和替换已有基础；空间迁移、实体替换、观测 Schema 版本和 Adapter 契约版本需补 |
| Observability & Cost | 部分实现 | 有结构化日志、correlation ID、Provider 日志和执行审计；需增加观测量、存储量、模型成本、任务成功率和状态质量指标 |

## 7. 关键概念与数据模型差距

### 7.1 现有表职责

| 现有对象 | 当前职责 | Phase 2 判断 |
| --- | --- | --- |
| `devices` | Device Adapter 投影出的可用设备实体 | 可复用，但需要与空间实体建立明确关系；`area` 字符串不能长期作为空间模型 |
| `device_states` | 设备 / 传感器状态快照历史 | 可保留为设备投影历史；缺少 Observation 的来源、质量、单位和采集 / 接收时间语义，不应直接当作唯一观测史 |
| `events` | 领域事件和审计时间线 | 可保留；事件表示“系统识别到的变化或动作”，不应承担原始观测记录职责 |
| `environments` / `environment_snapshots` | 默认环境和 Context JSON 快照 | 可复用为运行时 Context 快照，但 JSON 大快照不适合细粒度观测历史和状态估计溯源 |
| `memories` | 未来长期记忆表结构 | 保留给 Phase 3；不要把 Phase 2 原始观测直接塞入 memories |

### 7.2 必须新增的空间模型

Phase 2 应引入通用空间层级，而不是把家庭类型硬编码进核心：

1. `space`：home / building / floor / room / zone 等类型与父子层级。
2. 空间元数据：名称、类型、路径、排序、状态、创建 / 更新时间。
3. 实体归属：设备、传感器、执行器、未来机器人或少量有价值对象与空间的关联。
4. 迁移策略：现有 `devices.area` 可先保留为显示名或迁移辅助字段，再逐步映射到空间实体。
5. 生命周期：空间改名、合并、移动、停用和设备重新归属不能破坏历史观测来源。

不建议把普通家居物品全部登记为实体。Phase 2 只管理已接入设备、传感器，以及用户明确指定或对环境理解有实际价值的对象。

### 7.3 必须新增 Observation 契约

独立 Observation 至少要能表达：

1. 来源：adapter、设备、传感器、模型、人工输入或未来机器人。
2. 主体：实体、属性、空间或关系。
3. 数值 / 状态：原始值和标准化值。
4. 单位：原始单位与标准单位。
5. 时间：采集时间、接收时间、处理时间；不能只保存一个 `updated_at`。
6. 质量：精度、校准、异常标记、重复、延迟、可用性和来源可信度。
7. 有效期：新鲜度阈值、过期时间或按属性类型的失效规则。
8. 关联：correlation ID、事件 ID、适配器外部 ID、批次或观测会话。

观测与领域事件的职责应区分：

```text
Adapter / Sensor / Future Perception Provider
→ Observation Pipeline（标准化、去重、质量标记）
→ State Estimation（当前状态、冲突、未知、来源）
→ Environment Context / Agent / API / UI
→ Event System（记录值得通知、审计或响应的变化）
```

不是每个观测都必须成为领域事件，也不是每个领域事件都足以还原原始观测。

### 7.4 必须新增 State Estimation 语义

建议状态估计至少区分：

| 语义 | 含义 |
| --- | --- |
| observed | 有可用直接观测支撑 |
| derived | 由规则或多个观测计算得到 |
| inferred | AI 或模型推断，必须与事实分离 |
| unknown | 没有足够观测 |
| stale | 有历史观测但已超过有效期 |
| unavailable | 来源明确不可用 |
| conflict | 多个来源或观测结果冲突 |

每个空间级状态应保留：

1. 使用了哪些 Observation。
2. 使用了什么规则或算法。
3. 计算时间和有效期。
4. 冲突来源和差异。
5. 置信度或可信度字段的使用条件。

简单平均不应作为通用融合规则。某些二态、presence、开闭或异常类状态平均后没有物理意义。

## 8. 修改建议分级

### P0：进入 Phase 2 功能开发前必须确定

1. 明确 `space`、`environment`、`device`、`entity`、`observation`、`state_estimate`、`event`、`memory` 的职责边界。
2. 设计空间层级表和设备 / 传感器归属迁移方案，决定 `environments` 与未来空间根节点的关系。
3. 设计 Observation Schema，至少覆盖来源、时间、单位、质量、有效期和外部 ID。
4. 设计 State Estimation Schema，固定 observed / derived / inferred / unknown / stale / unavailable / conflict 等语义。
5. 明确 `device_states`、`events`、`environment_snapshots`、未来 `observations` 的表职责，避免双写语义漂移。
6. 明确单位标准化和时间处理规则，统一使用 UTC 并区分采集与接收时间。
7. 明确观测保留策略、隐私默认值和删除边界；Phase 2 不做完整 Memory，但不得丢失 Phase 3 需要的来源。
8. 建立传感器冲突、过期、离线、异常值、单位转换、空间迁移和设备替换的测试场景。

这些 P0 是 Phase 2 的第一批工程任务，不是可以跳过的文档工作。

### P1：Phase 2 内应完成

1. 空间创建、编辑、层级查询和设备归属 API。
2. Observation Pipeline 的 Mock / HA Demo 接入。
3. 房间级状态估计和 Context 重建。
4. 未知、过期、冲突和感知盲区展示。
5. 空间结构与观测详情的 Web Console 页面。
6. `get_environment_state` 或新增空间查询工具返回来源、状态和数据质量。
7. 自然语言房间查询能引用实际观测，并说明未知项。
8. 一个 ESPHome / ESP32 真实传感器节点的最小验证。

### P2：后续阶段再做

1. 长周期时间序列压缩和完整趋势分析。
2. 完整 Memory Agent 和语义记忆检索。
3. 向量数据库或 PostgreSQL 迁移。
4. 3D 数字孪生、物理仿真、摄像头全天候感知。
5. 机器人导航、抓取和工业协议。
6. 微服务、消息队列、多租户或分布式实例。

## 9. 可直接复用的模块

| 模块 | 复用方式 |
| --- | --- |
| FastAPI + React + SQLite 模块化单体 | 继续承载 Phase 2；当前规模不需要基础设施升级 |
| Device Adapter Interface | HA / Mock / 未来 MQTT 或 ESPHome 都可作为观测来源接入 |
| Device Registry | 作为设备投影和能力来源，再补充空间关系与观测属性 |
| EventBus | 继续负责领域事件分发；不承担 Observation Pipeline |
| Environment Context | 升级为空间状态估计的消费者和当前摘要，而不是状态来源本身 |
| Tool Registry / Tool Executor | 空间查询可作为 read-only 工具；未来主动观测仍经统一执行入口 |
| Safety Policy / Confirmation / Audit | 未来机器人、工业和多模态动作继续复用此治理链路 |
| Task System | 继续管理任务生命周期；未来 Planner 生成计划后仍交给它执行 |
| Agent Runtime 边界 | 继续让模型输出停留在候选意图和候选计划，不能直接获得设备或权限 |
| 测试与 Mock 体系 | 扩展为观测质量、空间层级和状态估计回归测试 |

无需修改的决策包括：继续本地优先、继续单用户、继续模块化单体、继续使用 Repository 隔离数据库、继续禁止 Agent 直接调用适配器、继续默认拒绝高风险、继续不引入向量数据库和消息队列。

## 10. 机器人与工业兼容性

### 10.1 机器人

长期方向与现有架构兼容，但 Robot Adapter 必须与普通 Device Adapter 分开：

1. Arvuno Core 负责世界模型、记忆、目标理解、规划、权限和任务协调。
2. Robot Adapter 负责把高层任务映射为机器人能力，如导航到房间、移动观察、语音交互或受限抓取。
3. 机器人本体控制系统负责实时运动、驱动、碰撞保护、急停和硬件安全。
4. Arvuno 不直接控制关节、电机或绕过厂商安全系统。
5. 机器人只是可替换的感知与执行终端，不是 Arvuno 大脑的唯一载体。
6. 机器人位置、地图、坐标和定位状态应进入 Observation / State Estimation，而不是塞入 Agent Runtime。

当前架构测试禁止顶层 `adapters/` 和 `agents/` 目录，现有设备适配器放在 `devices/` 下。未来实现机器人时应先决定包边界并同步更新架构测试；这只是放置与命名问题，不是架构冲突。

### 10.2 工业

工业扩展可以成立的前提是 Phase 2 保持通用空间 / 实体 / 观测模型：

```text
工厂 → 车间 → 生产线 → 工位 → 设备 / 传感器 / 机器人
```

不应从家庭模型复制一套完全独立的核心系统。工业新增的是领域空间类型、资产层级、工艺上下文、协议 Adapter 和安全治理规则。初期应只读接入、可视化和诊断建议；Arvuno 不替代 PLC、SCADA、安全联锁或急停系统。

## 11. 主要风险与技术债

| 风险 | 影响 | 控制方式 |
| --- | --- | --- |
| 把 HA 状态当世界模型 | Phase 3 / 4 数据来源不足，无法解释状态可信度 | 独立 Observation 契约，HA 只是来源之一 |
| 把 Event History 当 Memory | 无法做时间序列、状态差异和连续环境认知 | 区分事件、观测、状态估计和记忆 |
| 空间模型过度抽象 | Phase 2 变成通用 GIS / ERP 建模项目 | 先满足 home / floor / room / zone 和设备归属，不做全量物品登记 |
| 观测表高频写入 | SQLite 存储和写入压力增长 | 先量化采样频率，设计批量写入、索引和保留策略，不提前引入消息队列 |
| Environment Snapshot 双写 | 同一状态多处表达且不一致 | 明确 snapshot 是 Context 投影，不是权威观测历史 |
| 语义漂移 | AI 推断被包装成事实 | `inferred` 与 observed / derived 分离，并保留证据来源 |
| 简单融合误导用户 | 多传感器冲突被平均值掩盖 | 冲突必须显式展示；融合规则按属性类型定义 |
| 隐私能力后补 | 摄像头、麦克风、位置和机器人带来不可逆风险 | 感知能力分级授权、采集状态可见、保留和删除在功能前设计 |
| 阶段范围扩张 | Phase 2 混入 Memory / Planner / 机器人 | 每次开发只落地一个可验收增量 |
| 机器人安全低估 | 物理动作风险远高于设备开关 | 独立 Robot Capability Model、急停、禁入区、人工接管和仿真分级测试 |

## 12. Phase 2 建议开发顺序与验收

### 12.1 开发顺序

1. **契约冻结**：完成空间、观测、状态估计、事件与记忆边界的 P0 设计。
2. **Spatial Model**：空间层级、设备归属、迁移和基础 API。
3. **Observation Schema**：来源、时间、单位、质量、有效期和外部关联。
4. **Observation Pipeline**：从 HA / Mock 状态生成观测，处理重复、延迟和过期。
5. **State Estimation**：形成房间级状态、冲突和未知状态，并保留来源。
6. **Environment Context v2**：从状态估计重建当前上下文和感知盲区。
7. **查询与展示**：API、Web Console 和 Agent 查询工具。
8. **真实传感器验证**：先 HA Demo，再一个 ESPHome / ESP32 节点。
9. **回归与验收**：保留 Phase 1 安全链路，新增 Phase 2 数据质量测试。

### 12.2 可验证验收标准

1. 可以创建家庭、楼层、房间和区域，并将设备 / 传感器归属到空间。
2. 每个房间状态能展示当前值、状态语义、更新时间和观测来源。
3. 同一房间多个温湿度传感器不一致时，系统展示差异或不确定性，不伪造单一确定结论。
4. 设备离线、数据过期、缺传感器或来源冲突时，状态显示 unavailable / stale / unknown / conflict 等明确语义。
5. 用户询问“现在工作室怎么样”，回答引用实际观测，并说明无法确定的信息。
6. 观测包含采集时间、接收时间、来源、单位、原始值和标准化值。
7. 设备移动到其他房间后，当前归属正确，历史观测仍可追溯。
8. AI 推断结果若出现，必须标记为 inferred，并能区分证据和结论。
9. 空间查询工具为 read-only，不绕过 Tool Registry 和 Safety Policy。
10. Phase 1 的 191 个后端测试语义不回退，架构边界测试继续通过。
11. 新增测试覆盖单位转换、时钟偏差、重复观测、异常值、冲突、过期、离线、空间迁移和重启恢复。
12. HA Demo / Mock 自动化验收与真实传感器验收分开记录，不用 Mock 冒充实体硬件结果。

## 13. 产品竞争力与现实意义判断

### 13.1 竞争力来源

短期看，Arvuno 不是一个比 Home Assistant 更好的设备面板，也不应复制 HA Dashboard 或通用自动化编辑器。它的差异化位置是：

1. **同一现实空间的连续认知**：不是孤立设备状态，而是空间、实体、观测、历史和关系。
2. **可解释的环境状态**：知道来源、时间、质量、冲突和未知，而不是给出看似确定的平均值。
3. **模型可替换**：DeepSeek、本地模型或其他 Provider 都只是智能引擎，核心资产在 Arvuno 自己的数据与执行体系。
4. **跨生态执行入口**：HA、MQTT、机器人和未来工业系统通过 Adapter 进入同一能力与治理模型。
5. **安全可信的现实行动**：权限、风险、确认、验证、审计、取消和人工接管已经先行。
6. **真实数据积累**：观测、异常场景、用户纠正、任务结果和回放基准会随时间形成迁移成本与质量壁垒。

如果只完成 Phase 1，它更像一个安全封装的智能设备控制入口；完成 Phase 2-4 后，才会形成“理解环境并追求环境目标”的明显差异。

### 13.2 现实意义

这个方向有现实意义，但应按个人系统和小场景验证：

1. 解决用户反复遇到的问题：房间状态要跨设备理解，异常要解释，目标要转成安全动作。
2. 本地优先和来源可追溯，比纯云端助手更适合家庭与工业现实数据。
3. 不锁定模型、设备平台或机器人品牌，长期迁移成本低于厂商封闭方案。
4. 对开发者本人也是可持续资产：架构、数据、测试和评估体系可以逐步复用到工作室和工业场景。

它当前的意义不是“马上替代成熟智能家居平台”或“立即进入工业市场”，而是先在一个真实房间里验证：能否把传感器与设备数据变成可信、可查询、可解释、可行动的环境智能。

## 14. 最终建议

1. **保留长期 Phase 1-8 路线**，不因短期硬件不足而删除机器人或工业方向。
2. **当前只进入 Phase 2**，不同时开发完整 Memory、Planner、语音视觉、机器人或工业协议。
3. **先做 P0 数据契约**，再写空间页面和 AI 查询；否则后续会为观测来源和状态语义返工。
4. **保持模块化单体和安全执行边界**，不引入微服务、消息队列、向量数据库或 3D 数字孪生。
5. **把 Phase 2 验收定义为“能解释一个房间的状态和未知”**，而不是传感器数量或页面数量。

最终判断：长期路线可行，现实意义明确，竞争力有条件成立。当前架构不是障碍；真正的分水岭是 Phase 2 能否把设备状态升级为有来源、有质量、有空间语义、能承认未知的环境认知。
