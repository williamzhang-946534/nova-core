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

当前推进边界：长期路线暂时先推进到第七部分 `ARS-06 Embodied Intelligence / 机器人接入`；第八部分 `ARS-07 Industrial Intelligence / 工业环境扩展` 暂停，不进入当前计划。这不关闭 `ARS-02` 至 `ARS-04` 已记录的验收缺口，机器人接入前仍必须完成独立架构和安全确认。

| 长期阶段 | 状态 | 说明 |
| --- | --- | --- |
| `ARS-01` Core Execution | 已完成 | 对应仓库 Phase 10 完成状态 |
| `ARS-02` Spatial Environmental Intelligence | ARS-02.7 最终验收保持未完全通过；D1 Context v2 缺陷已修复并复验 | 设计见第 20 至 24 号文档；验收补充见第 25、26 号文档。Spatial Model、Observation Model、Observation Pipeline、State Estimation、空间查询 / AI 环境理解 / Web Console 已实现；Context v2 空间状态投影已与当前读模型一致。隐私删除端到端、目标规模压测、备份恢复、真实 ESPHome / ESP32 和真实 AI Provider 仍未完成验收 |
| `ARS-03` World Memory | ARS-03 验收部分通过 / 未完全关闭 | Memory 分类、Service、检索、生命周期、用户偏好、时间理解、只读历史查询和 Agent 只读工具入口已实现并通过回归；语义检索、自动压缩、记忆图谱、多用户隔离和真实程序执行验收链路未实现。结果见第 28 号报告 |
| `ARS-04` World Reasoning & Orchestration | ARS-04 验收部分通过 / 未完全关闭 | 设计与工程实现见第 29 号文档；验收结果见第 30 号报告。确定性 Reasoning、单设备 Goal / Planning、失败重规划、Proactive 基础治理和 Active Perception Mock 闭环已通过回归；AI / 模型 Planner 与评估器、多步与非设备计划、Level 3 / 4、Task System 感知集成、真实 Observer / 授权界面 / Provider 验收仍未实现 |
| `ARS-05` Multimodal Perception | ARS-05.4 Mock / 按需架构条件通过 / 不关闭 | 设计见第 31 号文档；验收见第 32 号报告。按需图像 / OCR / 音频、Provider 抽象、Mock 视觉 / STT / TTS、Observation 映射、Fusion、隐私治理、物理删除、超时和语音 API / 前端状态机已通过隔离回归。真实摄像头 / 麦克风与真实模型、生产云端 Provider、真实浏览器语音端到端、独立后台唤醒词、持续分析和自动后台保留清理调度器未完成 |
| `ARS-06` Embodied Intelligence | ARS-06.1 Mock Robot Adapter 实现完成 / 待用户验收；真实硬件接入仍受安全门槛限制 | 当前载体选定为自制桌面机器人，设计见第 34 号文档；第 33 号文档保留为商用机器人 / 通用 Adapter 参考。Robot 接口、Registry、Capability Schema、状态模型、任务请求状态机、事件、MockRobotAdapter、REST API 和持久化已实现；Web Console 最小状态页与 Agent 只读工具未实现。第一版不做轮式导航、机械臂、抓取或持续采集；全部能力默认 concept / disabled / 需确认，急停默认激活，机器人默认禁用；BOM、固件契约和安全实测未冻结，真实硬件不开放 |
| `ARS-07` Industrial Intelligence | 暂停 / 不进入当前计划 | 工业环境扩展保留为未来方向；不提前实现工业 Adapter、协议接入或工业规则 |
| `ARS-08` Distributed World Intelligence | 远期规划 / 暂缓 | 不进入当前计划，只保留长期方向 |

ARS-02.0 覆盖 Spatial Model、Entity Model、Observation Model、Observation Pipeline、State Estimation、Environment Context v2、迁移与 API 草案、隐私删除、SQLite 性能、测试策略和验收标准。用户确认设计后，先执行 `ARS-02.1 Spatial Model 工程实现`，不得直接跳到观测管线或状态估计。

2026-11-03，`ARS-02.1 Spatial Model 工程实现` 已完成并通过后端全量回归与前端构建，当前状态为待用户验收。本子阶段只包含空间层级、设备实体与归属历史、Alembic 增量迁移、空间 API 和基础空间管理页面；Observation Pipeline、State Estimation、Memory、Planner、Active Agent、GIS/3D、机器人和工业功能均未实现。

2026-11-03，`ARS-02.2 Entity 与 Observation 数据模型` 已完成并通过后端全量回归，当前状态为待用户验收。本子阶段包含 Observation schema、来源/属性/策略/授权同意表、Repository、设备-实体-来源映射、外部设备 ID 解析、单位标准化、采集/接收/处理时间区分、质量与有效期标记、幂等 append、基础查询 API 和 Alembic 增量迁移；不回填或双写 `device_states`。Observation Pipeline runtime ownership、HA/Mock 轮询自动入库、State Estimation、Environment Context v2、Memory、Planner 和 Active Agent 均未实现。

2026-11-03，`ARS-02.3 Observation Pipeline` 工程实现完成，已通过后端全量回归，当前状态为待用户验收。该子阶段将 HA / Mock 轮询状态统一映射为 Observation，完成来源与主体解析、schema 校验、单位标准化、时间语义、采样、去重、质量标记、批处理状态、来源心跳、有界保留清理和唯一当前 `device_states` 兼容投影；Observation 不自动产生 Event。State Estimation、Environment Context v2、Memory、Planner、Active Agent、隐私删除任务和真实硬件性能验收尚未开始。

2026-11-03，`ARS-02.4 State Estimation 与 Environment Context v2` 工程实现完成，已通过后端全量回归（221 项测试）、Ruff 检查和格式检查，当前状态为待用户验收。该子阶段包含实体 / 空间状态目标、append-only 状态估计历史、可重建当前投影、来源与规则追溯、属性化融合策略、冲突 / 过期 / 不可用 / 未知语义、管道触发重建、状态查询 API 和 Context v2 只读构建；Context v2 快照仅在显式 rebuild 时持久化。Memory、Reasoning、Planner、Active Agent、ARS-02.5 隐私删除、视觉、机器人和工业功能均未开始。

2026-11-03，`ARS-02.5 空间查询、AI 环境理解与 Web Console` 工程实现完成，待用户验收。该子阶段提供空间聚合 overview / coverage / 观测后代查询、Tool Registry 内的 `get_environment_state` v2 只读工具、带证据引用的确定性环境回答，以及 Spaces Console 的状态估计、感知覆盖、来源、观测历史和证据抽屉；Agent 不直接访问数据库、Repository、Adapter 或 Tool Executor。隐私删除仍属于 ARS-02 后续验收事项，Memory、Planner、Active Agent、视觉、机器人、GIS/3D、数字孪生和工业功能均未开始。

2026-11-04，`ARS-02.6 真实 ESPHome / ESP32 传感器验证` 的软件接口验收完成，真实硬件验收因当前没有 ESP32 和相关传感器而未执行。隔离空库通过 Alembic 升级，Mock Adapter 与 HA Demo 分别通过 Device Registry、Observation Pipeline、来源追踪、时间/单位/质量标记、State Estimation、Context v2、只读 Tool 和重启恢复验证；后端全量回归 228 项通过，Ruff lint 和格式检查通过。HA 写操作保持关闭并通过 Tool Executor 拒绝写操作验证。结果见 `docs/25-ars02-real-esphome-acceptance.md`。Mock 与 HA Demo 结果未替代真实 ESPHome / ESP32 验收。

2026-11-04，`ARS-02.7 完整验收` 已完成并输出 `docs/26-ars02-final-acceptance-report.md`。后端全量回归 228 项通过，Ruff、前端类型检查 / 构建 / 格式检查、Alembic 空库升级和隔离环境重启恢复通过；Mock 与 HA Demo 链路、空间历史、观测来源、时间语义、状态估计、只读 Tool、安全链路和 Web Console 空 / 失败态完成检查。最终结论为**未完全通过**：Environment Context v2 未投影 18 条空间级状态估计，与当前状态读模型不一致；隐私删除端到端审计、目标规模 SQLite 压测、备份恢复演练、真实 ESPHome / ESP32 和真实 AI Provider 验收仍未执行或未完全执行。ARS-02 不得标记关闭，应先修复 Context v2 缺陷并按第 26 号报告复验后再进入 ARS-03。

2026-11-04，ARS-02 D1 `Environment Context v2 空间状态投影缺失` 已修复并复验。根因是 Context v2 状态索引与空间 / 实体读取使用了不一致的 target key；修复统一为二元 key，未改变 State Estimation 语义。新增测试覆盖 root / floor / room / zone 投影、冲突 / stale / unavailable / unknown、即时 Context 与 Snapshot 一致、API 与只读 Tool 一致、重启恢复、状态更新、空间迁移和重复重建幂等。后端全量回归 258 项通过，Ruff lint 和格式检查通过。D1 不再阻塞 Memory 等上层能力，但 D2-D8 仍未完成，ARS-02 不关闭。

2026-11-04，`ARS-03.2 环境时间理解与历史关联` 工程实现完成，待用户验收。该子阶段在既有空间、实体、观测、事件、任务和环境快照上增加只读 History Repository、Service、Schema 和带认证的 History API；提供时间范围、空间后代、实体 / 设备、趋势、快照查询、有限快照差异、correlation 关联和四类确定性中文历史问答。SQLite 继续使用 naive UTC 存储，API 使用 aware 时间并按用户 IANA 时区展示；迟到、未来偏差、缺少采集时间和缺失区间显式暴露。快照差异只标注可由设备命令尝试恢复的投影候选，明确物理观测不能真正回滚。实现细节和测试边界见 [27-ars03-history-time-understanding.md](27-ars03-history-time-understanding.md)。本子阶段不自动写入 Memory，不引入向量数据库，不做通用自然语言理解，不开始 ARS-03.3。

2026-11-04，`ARS-03 World Memory` 验收完成并输出 `docs/28-ars03-acceptance-report.md`。后端全量回归 255 项通过，Ruff、前端类型检查 / 构建 / 格式检查和 Alembic head `d41d8acd98a0` 检查通过；五类记忆职责、来源追踪、事实与推断分离、用户偏好管理、过期清理、真实删除、时间查询、空间 / 设备历史、趋势、快照差异、事件 / 任务关联和确定性历史问答通过隔离测试。最终结论为**部分通过 / 未完全通过**：Agent Runtime 未接入 Memory retrieval 和 History API，语义检索、自动压缩、长期知识提炼、记忆图谱、多用户隔离、真实工具执行产生程序验证、目标规模压测、生产备份恢复演练和真实 AI Provider 验收未完成。ARS-02 Context v2 空间级状态投影缺陷继续作为遗留阻塞项，ARS-03 不关闭。

2026-11-04，Agent 已通过 `retrieve_memory` 和 `query_history` 两个只读工具接入 `MemoryService` 与 `HistoryService`。工具入口不暴露 Repository、SQLAlchemy 或内部 HTTP 调用；Memory Retrieval 覆盖偏好、稳定事实、历史事件、任务记录和已验证程序，History Query 覆盖时间、空间、实体、趋势、快照、差异和关联查询。检索结果携带原始来源引用，缺失区间显式返回；关键词检索现在同时匹配 `memories.keywords`。新增工具边界、权限、Agent 意图、服务委托和应用集成测试。后端全量回归 273 项通过，Ruff lint 和格式检查通过。语义检索、自动压缩、长期知识提炼、记忆图谱、多用户隔离和真实程序验证链路仍未实现，ARS-03 继续保持不关闭。

2026-11-04，`ARS-04.0 World Reasoning & Orchestration` 架构设计完成并输出 `docs/29-ars04-world-reasoning-orchestration-design.md`，当前状态为等待用户确认。设计冻结 Reasoning / Planning / Task System / Tool Executor / Proactive Intelligence / Active Perception 的职责边界，定义 Evidence、Hypothesis、Goal、Plan、Replanning、Proactive Suggestion 和 Observation Request 数据契约，并给出 API、授权、隐私、测试和实施切分。该记录不表示数据模型、迁移、Service、API、Agent 集成或任何 ARS-04 工程能力已经实现。

2026-11-06，`ARS-05.3 语音交互体验` 的按需链路工程实现完成，待用户验收。后端复用 MultimodalService 授权、私有媒体存储、STT invocation、模型版本追踪和敏感音频清理，只在 Provider 显式标记 instruction 后进入 Agent Runtime；任务确认必须使用独立 task ID + token 接口。独立唤醒词模块只处理单次转写，前端不常驻监听。前端提供 `idle / listening / recognizing / executing / speaking` 状态、显式授权配置、按需 WAV 录音上传和 TTS 播放。当前默认 STT / TTS 仍是本地 Mock，真实模型、真实麦克风硬件验收、后台唤醒词和 ARS-05.4 最终验收未完成。

2026-11-04，`ARS-04.1 Evidence-based Reasoning Engine` 工程实现完成，待用户验收。该子阶段新增 Reasoning Session、Evidence Bundle / Item、Hypothesis 与证据关系表及 Alembic 迁移；Reasoning Service 可读取 World Model 当前估计、Observation、环境事件、任务与 Memory，生成结构化 Evidence Bundle、确定性规则结论、非因果时间相关性、显式验证原因、数据质量和未知信息，并持久化诊断记录。API 支持诊断、会话、证据、假设和原始来源查询；推理过程不修改 World Model observed 状态，不把模型结论写成事实或 Memory。历史回放、已验证原因、错误数据、来源追溯和 World Model 不可变性已覆盖测试。后端全量回归 278 项通过，Ruff 与 Alembic head 检查通过。AI 候选生成器保持 `not_configured`；Goal、Plan、Replanning、Proactive Intelligence、Active Perception、工具执行和设备控制未实现。

2026-11-05，`ARS-04.2 Planning Engine 与 Goal Compiler` 工程实现完成，待用户验收。该子阶段新增 Planning Session、Goal、Plan、Plan Step 和 Replanning Record 表及 Alembic 迁移；Goal Compiler 可将自然语言目标解析为含目标空间、期望状态、约束、优先级、完成条件、澄清项和未知项的结构化目标，并在缺少可操作设备时短路返回未解决状态。Planning Engine 基于当前 World Model 投影生成确定性的“读取状态、执行控制、验证结果”单设备计划，验证工具可用性、在线状态、依赖关系、风险、禁止条件和自动重试安全；系统级风险上限保持 `low_risk`，授权上限不会被历史相似任务扩大。计划生命周期覆盖 candidate、confirmed、plan、approve、submit 和 replan；需要确认的计划经由 Task System 传递 `requires_confirmation` 到 Tool Executor，Planner 不直接操作设备。离线设备预检、模糊目标短路、授权上限、依赖失败、执行失败、结果不满足和版本保留的重规划审计已覆盖测试；后端全量回归 288 项通过，Ruff 与 Alembic 单 head 检查通过。AI / 模型 Planner、Proactive Intelligence、Active Perception、多步计划和非设备计划仍未实现。

2026-11-05，`ARS-04.3 Proactive Intelligence` 工程实现完成，待用户验收。该子阶段新增 Proactive Suggestion 表和 Alembic 迁移，事件总线接入传感器异常、设备不可用和任务失败触发；实现候选评估、优先级、证据引用、去重、冷却、按用户本地时区判断的静默时间、小时 / 日通知上限、用户压制偏好、接受 / 打开 / 忽略 / 反馈、删除、过期清理和质量统计。Level 1 仅记录，Level 2 记录并通知，运行时最大自主级别保持 2；Proactive Service 不直接执行设备动作，不监听自身产生的事件，不把一次 motion 读数推断为离家或异常，用户忽略建议也不会提高提醒频率。后端全量回归 312 项通过，Ruff lint / format 和 Alembic 单 head 检查通过。Active Perception、真实 AI Proactive 评估器、趋势 / 推理假设驱动的候选生成、Level 3 接受后自动创建候选任务、Level 4 有限自主执行、完整前端管理页和真实 Provider 验收仍未实现。

2026-11-05，`ARS-04.4 Active Perception Decision` 工程实现完成，待用户验收。该子阶段新增 Active Perception Request 表和 Alembic 迁移，实现缺口评估、已有观测 / 当前估计覆盖检查、来源可信度与成本比较、敏感属性授权、观测请求生命周期、拒绝 / 删除、过期清理和带认证的 API。Mock Observer 可验证只读观测闭环：结果必须通过目标、空间、来源和属性校验并写入真实 Observation，随后触发 State Estimation 重建和 Reasoning 重跑；没有 Observer 或 Observer 返回空时请求标记 unavailable，不伪造观测结果。应用默认 `perception_observer = None`；本阶段不做自主持续采集、摄像头 / 麦克风 / 机器人接入、硬件导航或设备控制。后端全量回归 323 项通过，Ruff lint / format 和 Alembic 单 head `a7d4f83c1092` 检查通过。Task System / Tool Executor 集成、真实 Observer、AI 感知评估器和真实隐私授权流程验收仍未实现。

2026-11-06，`ARS-04.5 最终验收` 完成并输出 `docs/30-ars04-acceptance-report.md`。验收发现 `StateEstimationService.list()` 直接使用系统时间判断 freshness，而验收固定时钟无法注入；已补上默认行为不变的可选时间注入并复验。后端全量回归 323 项通过，ARS-04 专项 50 项通过，Ruff lint / format、Alembic 单 head 与隔离空库升级、前端 typecheck / build / format 均通过。最终结论为**部分通过 / 未完全通过**：事实 / 假设分离、证据来源、Planning / Task 边界、失败重规划、Proactive 治理、授权上限、Active Perception 缺口识别和敏感权限通过；AI Planner / 评估器、多步与非设备计划、Level 3 / 4、感知执行集成、真实硬件、真实授权界面、ARS-04 前端管理和真实 Provider 端到端未完成。ARS-04 不关闭。

2026-11-06，`ARS-05.0 多模态架构设计` 完成并输出 `docs/31-ars05-multimodal-perception-design.md`，当前状态为等待用户确认。设计冻结按需 Image / Video Frame / Voice / STT / TTS / Audio Event、Media Asset、Provider Invocation、Extraction Result、Observation Link、Multimodal Consent、有限 Fusion、保留清理和物理删除边界；所有环境事实仍必须通过既有 Observation Policy、Observation Pipeline 和 State Estimation。本文不表示任何数据模型、迁移、Service、API、Provider、前端或真实硬件能力已经实现。

2026-11-06，`ARS-05.4 最终验收` 完成并输出 `docs/32-ars05-acceptance-report.md`。验收发现 `timeout_ms` 未实际限制 Provider 调用，已为 Vision / OCR / STT / Audio Event / TTS 增加统一超时、`timeout` 调用状态、媒体清理和会话失败；外层错误处理不再把超时改写成普通失败，并补充 Provider 崩溃测试。ARS-05 专项 28 项通过，后端全量回归 351 项通过，Ruff、隔离空库升级到 `e5f1a2b3c4d5`、前端 typecheck / build / format 均通过。最终结论为**Mock / 按需架构条件通过**：候选语义、来源追踪、Fusion、授权、撤销、敏感删除、本地边界、故障和超时通过；真实摄像头 / 麦克风、真实模型、生产云端 Provider、真实浏览器语音端到端、后台唤醒词和自动保留清理调度器未完成。ARS-05 不关闭。

2026-11-06，`ARS-06.0 智元机器人接入架构设计` 完成并输出 `docs/33-ars06-embodied-intelligence-design.md`。该文档保留为商用机器人 / 通用 Robot Adapter 参考；设计明确 Arvuno Core 独立承载 World Model、Memory、Reasoning、Planning、Permission、Task System 与 Tool Executor，实时运动、碰撞保护与急停始终归属机器人本体控制系统。

2026-11-06，机器人载体选定为**自制桌面机器人**，ARS-06.0 补充设计完成并输出 `docs/34-ars06-custom-desktop-robot-design.md`，当前状态为等待用户安全确认。该设计将第一版范围收缩为固定桌面载体、受限 pan / tilt 姿态、按需图像、单次语音输入、TTS 播报和状态上报；不实现轮式导航、机械臂、抓取、持续视频监控、常驻麦克风采集或 Level 4 自主执行。自制硬件没有厂商安全兜底，后续必须先冻结 BOM、机械 / 电气设计、固件接口契约、硬件停止、限位、看门狗和失效安全测试，再逐步开放能力；所有能力默认 disabled。

2026-11-09，`ARS-06.1 Robot Adapter 与 Mock Robot` 工程实现完成，待用户验收。该子阶段新增 robots、capabilities、状态快照、事件和任务请求表及 Alembic 迁移 `a6b2c3d4e5f6`；实现 RobotAdapter 接口、Robot Registry、Capability Model、状态 / 位置模型、任务请求状态机、事件、MockRobotAdapter、连接与断线处理和带认证的 REST API。Mock 支持移动成功、导航失败、定位丢失、低电量、任务取消、设备离线、人工接管、急停和超时；全部能力默认 concept / disabled / 需确认，急停默认激活，机器人默认禁用。事件保存前统一将外部 robot ID 归一化为内部 ID；架构边界测试确认 Agent Runtime / Planner 不导入 robots 模块。后端聚焦回归 29 项通过。Web Console 最小状态页和 Agent 只读机器人工具尚未实现；本阶段不包含真实机器人控制代码。
