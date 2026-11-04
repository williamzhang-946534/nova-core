# 13. 开发路线图

## 总体原则

1. 架构确认后才进入工程初始化。
2. 每个阶段先做最小可用版本。
3. 真实设备写操作必须在安全链路测试通过后开放。
4. 每个阶段都有明确验收标准。
5. 不引入当前阶段用不到的复杂依赖。

## 阶段总览

| 阶段 | 名称 | 目标 | 是否必须 |
| --- | --- | --- | --- |
| Phase 0 | 架构确认 | 确认文档和边界 | 是 |
| Phase 1 | 工程初始化 | 建立可运行工程骨架 | 是 |
| Phase 2 | 数据与配置 | 建立数据库、配置和日志 | 是 |
| Phase 3 | 设备接入 | 打通 Home Assistant 和 Mock | 是 |
| Phase 4 | 环境与事件 | 建立上下文和事件系统 | 是 |
| Phase 5 | 安全工具执行 | 实现工具、权限和验证 | 是 |
| Phase 6 | 任务系统 | 支持多步骤任务和状态机 | 是 |
| Phase 7 | AI Agent | 接入模型并实现意图与规划 | 是 |
| Phase 8 | Web 控制台 | 提供核心页面 | 是 |
| Phase 9 | 自动化与通知 | 提供 Arvuno 上下文通知和少量低风险自动化 | 是 |
| Phase 10 | 稳定化验收 | 完成第一阶段验收 | 是 |

## Phase 0：架构确认

### 目标

用户确认架构文档、模块边界、数据模型、安全策略和第一阶段范围。

### 交付物

- 当前架构文档
- AGENTS.md
- README.md

### 验收标准

1. 用户确认技术栈。
2. 用户确认 Home Assistant 边界。
3. 用户确认第一阶段不开发内容。
4. 用户确认安全策略。
5. 用户确认开发顺序。

### 不做

- 不初始化代码。
- 不安装依赖。
- 不实现业务功能。

## Phase 1：工程初始化

当前进度：已完成（2026-10-26，用户已继续进入 Phase 2）。

### 目标

建立后端、前端和测试基础骨架。

### 任务

1. 初始化 Git 仓库。
2. 创建后端目录结构。
3. 创建前端目录结构。
4. 创建 `.env.example`。
5. 创建 Windows 启动脚本设计。
6. 配置代码格式化。
7. 配置测试框架。
8. 建立基础错误模型。
9. 建立日志框架。

### 验收标准

1. 后端可以启动。
2. `/health` 可以访问。
3. 前端可以启动。
4. 前端可以请求后端健康检查。
5. 单元测试可以运行。
6. OpenAPI 文档可以生成。
7. 敏感信息不入库。

## Phase 2：数据与配置

当前进度：已完成（2026-10-26，待用户验收）。

### 目标

完成配置、数据库模型、迁移和基础仓储。

### 任务

1. 实现 Pydantic Settings。
2. 定义数据库表。
3. 创建 Alembic 迁移。
4. 实现 Repository 边界。
5. 实现日志目录。
6. 实现数据库初始化。
7. 实现基础备份方案。

### 验收标准

1. 首次启动可以自动迁移或按脚本迁移。
2. 核心表结构创建成功。
3. 配置缺失时报错明确。
4. API Key 不出现在日志。
5. 数据库可以备份和恢复。

## Phase 3：设备接入

当前进度：已完成（2026-10-26，待用户验收）。

### 目标

建立统一设备接口，并实现 Home Assistant 与 Mock 两个适配器。

### 任务

1. 定义 Device Adapter Interface。
2. 定义 Device、State、Capability、Action 模型。
3. 实现 Home Assistant 健康检查。
4. 实现轻量 Device Registry 投影同步，仅同步配置范围内允许 Arvuno 使用的实体。
5. 实现状态查询。
6. 实现低风险动作调用。
7. 实现状态变化订阅或轮询。
8. 实现轻量 Device Registry。
9. 实现 Mock Device Adapter。

### 验收标准

1. 能连接 Home Assistant。
2. 能只同步配置范围内的有限设备，不同步 Home Assistant 全部实体和完整配置。
3. 能读取状态。
4. 能识别 unavailable。
5. 能控制一个低风险设备。
6. Mock Adapter 可以模拟离线和超时。
7. 适配器错误统一。

### 风险控制

真实设备写操作只能在 Safety Policy 和 Tool Executor 完成后开放。此阶段可以先提供开发模式开关，默认关闭。

## Phase 4：环境与事件

当前进度：已完成（2026-10-27，待用户验收）。

### 目标

建立 Arvuno 自己的环境上下文和事件系统。

### 任务

1. 定义 Event Schema。
2. 实现应用内事件总线。
3. 实现过滤后的 Arvuno 领域事件持久化。
4. 实现事件查询 API。
5. 实现环境状态快照。
6. 将设备状态更新写入 Environment Context。
7. 支持 correlation ID。

### 验收标准

1. 配置范围内与 Arvuno 相关的设备状态变化生成事件。
2. 事件入库。
3. Environment Context 更新。
4. 事件时间线可查询。
5. 事件保留策略可配置。
6. 订阅者异常不影响主流程。

## Phase 5：安全工具执行

当前进度：已完成（2026-10-27，待用户验收）。

### 目标

让所有设备操作都通过统一、可审计、可验证的工具链路。

### 任务

1. 定义 Tool Schema。
2. 实现 Tool Registry。
3. 实现 Safety Policy。
4. 实现 Tool Executor。
5. 实现参数校验。
6. 实现设备权限。
7. 实现风险等级。
8. 实现用户确认。
9. 实现执行结果验证。
10. 实现 ToolExecutionRecord。

### 验收标准

1. 只读工具可用。
2. low_risk 设备控制可用。
3. medium_risk 需要确认。
4. high_risk 默认拒绝。
5. 非法参数拒绝。
6. 设备离线拒绝。
7. 状态验证失败时任务不成功。
8. 每次执行有日志。

## Phase 6：任务系统

### 目标

将用户目标或自动化触发转化为可管理任务。

### 任务

1. 实现 Task 和 TaskStep 模型。
2. 实现任务状态机。
3. 实现计划存储。
4. 实现步骤执行。
5. 实现失败、取消和超时。
6. 实现任务历史查询。
7. 实现任务事件。

### 验收标准

1. 单步任务可执行。
2. 多步任务可执行。
3. 失败状态正确。
4. 取消状态正确。
5. 超时状态正确。
6. 任务历史完整。
7. correlation ID 可追踪。

### 当前完成情况

Phase 6 已按最小可用范围完成并等待用户验收。实现包含 Task/TaskStep Repository、任务和步骤状态机、显式计划保存、顺序步骤执行、失败传播、取消、执行超时、等待确认超时、历史分页查询、任务事件和 correlation ID 贯穿。TaskStep 统一通过既有 Tool Executor 调用工具，未复制设备执行逻辑，也未绕过 Safety Policy。测试使用显式任务输入、Mock Device Adapter 和真实 Tool Executor 闭环。

## Phase 7：AI Agent

### 目标

接入统一 AI Provider，实现自然语言查询和低风险控制。

### 任务

1. 实现 Provider Interface。
2. 实现 OpenAI-compatible Provider。
3. 实现结构化输出校验。
4. 实现意图识别。
5. 实现工具定义下发。
6. 实现候选计划生成。
7. 实现 Agent 与 Task System 集成。
8. 实现工具结果处理。
9. 实现模型调用日志。

### 验收标准

1. 可用自然语言查询设备。
2. 可用自然语言查询环境。
3. 可执行低风险设备控制。
4. 不支持意图不误执行。
5. 模型输出非法时拒绝执行。
6. Provider 超时不导致任务假成功。
7. 可更换模型配置。

### 当前完成情况

Phase 7 已按最小可用范围完成并等待用户验收。实现包含统一 AI Provider Interface、OpenAI-compatible HTTP Provider、Base URL/模型/API Key/超时/有限重试配置、结构化输出模式与 400/422 降级、严格 JSON 解析、脱敏 Provider 日志、确定性 Mock Provider、意图与候选计划 Pydantic 校验、只读 Tool Catalog 投影、Task System 集成、工具结果摘要和明确失败处理。Agent 不导入 Repository、SQLAlchemy、数据库会话、Home Assistant 客户端或 Device Adapter；候选任务仍通过 TaskStep 和 Tool Executor 执行。自动化测试使用 Mock Provider，不依赖真实模型调用。本阶段不实现 Memory、会话持久化、Agent 自主规划、自动化引擎、通知系统或前端业务页面。

## Phase 8：Web 控制台

### 目标

提供 Arvuno 的运行与观测界面。

### 任务

1. 系统概览。
2. 设备列表。
3. 设备详情。
4. 环境状态。
5. 事件时间线。
6. AI 对话。
7. 任务记录。
8. 工具调用详情。
9. 系统设置。

### 验收标准

1. 页面可正常访问。
2. API 类型一致。
3. 加载、错误和空状态清晰。
4. 事件时间线可自动更新。
5. 任务详情可追踪。
6. 不直接调用 Home Assistant。

### 当前完成情况

Phase 8 已按最小可用范围完成并等待用户验收。实现包含系统概览、设备列表与详情、环境状态、事件时间线、AI 对话、任务列表与详情、任务确认/取消和系统设置页面。前端统一使用类型化 API 封装和 TanStack Query，明确处理加载、错误、空数据、后端未配置和认证失败状态；页面只访问 Arvuno API，不直接请求 Home Assistant。设备操作仍从 `/api/chat` 进入候选计划，再通过 Task System、Tool Executor 和 Safety Policy 执行。控制台新增系统状态、设备查询、环境快照和非敏感设置 API；事件时间线使用可配置轮询，不实现 WebSocket 推送。设置页仅保存浏览器本地的 Arvuno API 地址和 Token，敏感后端配置仍只能来自受保护环境变量。

## Phase 9：自动化与通知

### 目标

普通定时、状态触发和场景自动化继续留在 Home Assistant。Arvuno 只实现需要自身上下文的少量通知规则、任务失败提醒和由用户明确启用的低风险动作规则。

### 任务

1. 少量 Arvuno 上下文自动化规则模型。
2. 条件评估。
3. 事件触发。
4. 冷却时间。
5. 自动化执行记录。
6. Web 控制台通知。
7. 任务失败通知。

### 验收标准

1. 少量明确启用的通知规则可用。
2. 任务失败通知可用。
3. 用户明确启用的低风险动作规则可用，执行时仍受现有确认策略约束。
4. 设备状态规则仅覆盖 Arvuno 实际需要的场景，不做通用自动化平台。
5. 冷却时间生效。
6. 自动化执行有记录。
7. 失败可追踪。
8. 高风险自动化不自动执行。

### 当前完成情况

Phase 9 已按最小可用范围完成，并在 Phase 10 稳定化验收中复核。实现包含自动化规则与执行记录 Repository、Web Console 通知 Repository、规则启用/禁用、显式条件评估、三类设备上下文事件触发、冷却时间、并发串行化、`notification` 与 `tool` 两类动作、自动化 API、通知 API 和控制台页面。工具动作统一通过 Task System、TaskStep 和 Tool Executor 进入 Safety Policy；仅 `read_only` 与 `low_risk` 允许自动执行，`medium_risk` 与 `high_risk` 在创建任务前记录 `risk_rejected`。任务失败会生成错误级站内通知，correlation ID 从触发事件延续到自动化事件、任务和工具执行。普通定时、状态触发和场景自动化继续由 Home Assistant 管理，本阶段不提供通用自动化编辑器或多渠道通知。

## Phase 10：稳定化验收

### 目标

完成第一阶段闭环和稳定性验证。

### 任务

1. 补齐安全测试。
2. 补齐验收测试。
3. 检查日志和脱敏。
4. 验证备份恢复。
5. 验证断线重连。
6. 验证 Mock 全流程。
7. 验证真实 Home Assistant 全流程。
8. 更新文档。

### 验收标准

Arvuno 能完成：

```text
真实环境信息
→ 自然语言目标
→ 任务计划
→ 安全工具执行
→ 设备状态验证
→ 任务历史记录
→ Web 控制台展示
```

设备异常、超时、模型错误和权限错误均有明确处理。

### 当前完成情况

Phase 10 稳定化验收已于 2026-10-30 执行，并于 2026-11-02 补充真实 HA 断线/重连、Web Console 终验和安全态恢复验收，完整结果见 [16-phase10-acceptance-report.md](16-phase10-acceptance-report.md)。F1 环境上下文问题已补充修复并复验，真实 DeepSeek 8 条冒烟通过；真实 Home Assistant demo 的读取、低风险写链路和断线/重连已通过；Web Console 逐页、设备详情、完整确认控制链路和移动端宽度复核也已通过。当前结论为**Phase 10 / 第一阶段验收已完成**：33 项通过、0 项未通过、1 项未执行、0 项需要用户手动操作。

已通过：191 个后端测试、Ruff 格式与静态检查、前端类型检查/构建/格式、9 项架构边界测试、API 认证与错误契约探测（两轮均通过）、日志脱敏、5 项配置安全护栏、10 项迁移与备份恢复、15 项任务链路端到端、Mock 与失败场景测试、Windows 启动脚本实跑、F1 环境一致性场景（14 项隔离实例探测）、真实 DeepSeek 8 条查询与控制冒烟、真实 HA demo 断线/重连验收。

未通过：无。默认 Mock Provider 仍返回 `unsupported`，这是未配置真实 Provider 时的安全默认。

未执行：前端自动化测试（项目暂无前端测试框架）。

已修复：F1 环境上下文为空（启动从 Device Registry 投影、验证成功后同步、自身控制不发布设备状态事件）、后台轮询从未启动、Windows 启动脚本编码导致解析失败、`.env.example` 误用 `ARVUNO_ENV`、复制示例配置后因空 URL 无法启动、配置错误信息变量名不一致、模型校验错误明细无法序列化导致 `/api/chat` 500、HA 上游 5xx 被误分类且直达 API 缺少设备错误映射导致断线时泛化 500。

## 推荐开发顺序

必须先完成：

1. 工程初始化
2. 配置和数据库
3. Device Adapter Interface
4. Mock Adapter
5. Event System
6. Environment Context
7. Safety Policy
8. Tool Executor
9. Task System
10. AI Provider
11. Agent Runtime

可以后置：

1. 复杂自动化规则
2. 多渠道通知
3. 长期记忆检索
4. 前端高级图表
5. PostgreSQL
6. Docker
7. 语音、视觉、机器人

## 架构需要提前确定的内容

1. 设备标准模型
2. 事件格式
3. 任务状态机
4. 工具风险等级
5. 用户确认机制
6. correlation ID 规则
7. 数据保留策略
8. Provider 适配接口
9. API 错误结构
10. Repository 边界

这些内容后移会造成大规模返工，应在 Phase 1 开始前锁定。

## 不应现在开发的功能

1. 老人监护相关功能
2. 自研智能家居协议
3. 多 Agent 协作
4. 插件市场
5. 多租户 SaaS
6. 完整视频监控
7. 复杂机器人控制
8. 高风险设备自动化
9. 向量数据库
10. Kubernetes

## 维护成本分析

| 成本 | 评估 |
| --- | --- |
| 日常运行 | 单后端 + SQLite，成本低 |
| 调试 | 本地进程和结构化日志，较容易 |
| 测试 | Mock 设备和 Provider，可离线测试 |
| 数据库 | 单文件备份，简单 |
| 扩展 | 通过接口新增适配器和工具 |
| 主要风险 | Python 经验较少、外部 API 变化、真实设备状态不稳定 |

控制方式：

- 保持小模块。
- 每阶段有验收。
- 不引入额外基础设施。
- 核心安全逻辑优先测试。

## 第一阶段开始建议

Arvuno Core 已完成工程初始化、数据配置、设备接入、环境状态、事件系统、安全工具执行、任务系统基础、AI Agent、Web 控制台和自动化通知最小闭环。Phase 10 稳定化验收已完成，此前发现的问题已修复并复验，第一阶段 demo 验收已收尾。后续阶段必须等待用户另行确认；继续开发时保持小模块和明确安全边界。

Phase 9 已完成少量 Arvuno 上下文自动化、Web Console 通知和任务失败提醒。真实 Home Assistant 写操作验收后已恢复默认关闭，真实模型只在显式配置后启用。Phase 10 的 F1 已修复并复验，真实 DeepSeek 冒烟通过，真实 Home Assistant demo 读/写链路和断线/重连通过；浏览器逐页与移动端终验也已通过，第一阶段已收尾。

## ARS 长期路线状态

本节与上方仓库历史 `Phase 0-10` 编号相互独立。长期路线使用 `ARS` 编号；历史验收报告不改名。

| 长期阶段 | 状态 | 说明 |
| --- | --- | --- |
| `ARS-01` Core Execution | 已完成 | 对应仓库 Phase 10 完成状态 |
| `ARS-02` Spatial Environmental Intelligence | ARS-02.7 最终验收已完成，结论为未完全通过；待修复 Context v2 缺陷并复验 | 设计见第 20 至 24 号文档；验收补充见第 25、26 号文档。Spatial Model、Observation Model、Observation Pipeline、State Estimation、空间查询 / AI 环境理解 / Web Console 已实现；Environment Context v2 空间状态投影存在阻塞缺陷 |
| `ARS-03` World Memory | 待开发 | 依赖 ARS-02 验收 |

ARS-02.0 覆盖 Spatial Model、Entity Model、Observation Model、Observation Pipeline、State Estimation、Environment Context v2、迁移与 API 草案、隐私删除、SQLite 性能、测试策略和验收标准。用户确认设计后，先执行 `ARS-02.1 Spatial Model 工程实现`，不得直接跳到观测管线或状态估计。

2026-11-03，`ARS-02.1 Spatial Model 工程实现` 已完成并通过后端全量回归与前端构建，当前状态为待用户验收。本子阶段只包含空间层级、设备实体与归属历史、Alembic 增量迁移、空间 API 和基础空间管理页面；Observation Pipeline、State Estimation、Memory、Planner、Active Agent、GIS/3D、机器人和工业功能均未实现。

2026-11-03，`ARS-02.2 Entity 与 Observation 数据模型` 已完成并通过后端全量回归，当前状态为待用户验收。本子阶段包含 Observation schema、来源/属性/策略/授权同意表、Repository、设备-实体-来源映射、外部设备 ID 解析、单位标准化、采集/接收/处理时间区分、质量与有效期标记、幂等 append、基础查询 API 和 Alembic 增量迁移；不回填或双写 `device_states`。Observation Pipeline runtime ownership、HA/Mock 轮询自动入库、State Estimation、Environment Context v2、Memory、Planner 和 Active Agent 均未实现。

2026-11-03，`ARS-02.3 Observation Pipeline` 工程实现完成，已通过后端全量回归，当前状态为待用户验收。该子阶段将 HA / Mock 轮询状态统一映射为 Observation，完成来源与主体解析、schema 校验、单位标准化、时间语义、采样、去重、质量标记、批处理状态、来源心跳、有界保留清理和唯一当前 `device_states` 兼容投影；Observation 不自动产生 Event。State Estimation、Environment Context v2、Memory、Planner、Active Agent、隐私删除任务和真实硬件性能验收尚未开始。

2026-11-03，`ARS-02.4 State Estimation 与 Environment Context v2` 工程实现完成，已通过后端全量回归（221 项测试）、Ruff 检查和格式检查，当前状态为待用户验收。该子阶段包含实体 / 空间状态目标、append-only 状态估计历史、可重建当前投影、来源与规则追溯、属性化融合策略、冲突 / 过期 / 不可用 / 未知语义、管道触发重建、状态查询 API 和 Context v2 只读构建；Context v2 快照仅在显式 rebuild 时持久化。Memory、Reasoning、Planner、Active Agent、ARS-02.5 隐私删除、视觉、机器人和工业功能均未开始。

2026-11-03，`ARS-02.5 空间查询、AI 环境理解与 Web Console` 工程实现完成，待用户验收。该子阶段提供空间聚合 overview / coverage / 观测后代查询、Tool Registry 内的 `get_environment_state` v2 只读工具、带证据引用的确定性环境回答，以及 Spaces Console 的状态估计、感知覆盖、来源、观测历史和证据抽屉；Agent 不直接访问数据库、Repository、Adapter 或 Tool Executor。隐私删除仍属于 ARS-02 后续验收事项，Memory、Planner、Active Agent、视觉、机器人、GIS/3D、数字孪生和工业功能均未开始。

2026-11-04，`ARS-02.6 真实 ESPHome / ESP32 传感器验证` 的软件接口验收完成，真实硬件验收因当前没有 ESP32 和相关传感器而未执行。隔离空库通过 Alembic 升级，Mock Adapter 与 HA Demo 分别通过 Device Registry、Observation Pipeline、来源追踪、时间/单位/质量标记、State Estimation、Context v2、只读 Tool 和重启恢复验证；后端全量回归 228 项通过，Ruff lint 和格式检查通过。HA 写操作保持关闭并通过 Tool Executor 拒绝写操作验证。结果见 `docs/25-ars02-real-esphome-acceptance.md`。Mock 与 HA Demo 结果未替代真实 ESPHome / ESP32 验收。

2026-11-04，`ARS-02.7 完整验收` 已完成并输出 `docs/26-ars02-final-acceptance-report.md`。后端全量回归 228 项通过，Ruff、前端类型检查 / 构建 / 格式检查、Alembic 空库升级和隔离环境重启恢复通过；Mock 与 HA Demo 链路、空间历史、观测来源、时间语义、状态估计、只读 Tool、安全链路和 Web Console 空 / 失败态完成检查。最终结论为**未完全通过**：Environment Context v2 未投影 18 条空间级状态估计，与当前状态读模型不一致；隐私删除端到端审计、目标规模 SQLite 压测、备份恢复演练、真实 ESPHome / ESP32 和真实 AI Provider 验收仍未执行或未完全执行。ARS-02 不得标记关闭，应先修复 Context v2 缺陷并按第 26 号报告复验后再进入 ARS-03。
