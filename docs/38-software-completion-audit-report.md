# 38. Arvuno 全项目软件完成度审计报告

日期：2026-11-13  
审计对象：`e9537681d825b795fa90c93fccc3808bb6a789f7`，分支 `main`  
审计性质：软件完成度审计，不是阶段关闭验收，也不是硬件验收  
审计范围：REPAIR-01、ARS-02、ARS-03、ARS-04、ARS-05、ARS-06，以及后续规划能力的软件状态

## 1. 审计结论

当前 Arvuno 的整体软件完成度约为 **70%**。这是本次审计给出的估计值，不代表 ARS-02 至 ARS-06 已经关闭，也不代表已经具备真实硬件、真实模型或生产部署验收结论。

如果不购买任何硬件，当前仍有大量纯软件工作可以推进。现有代码和测试基础可以支撑项目从约 70% 推进到约 **85%-90%** 的“最高可软件验证完成度”。剩余约 10%-15% 必须依赖真实 ESP32/ESPHome、真实 Home Assistant 环境、真实摄像头/麦克风、真实桌面机器人硬件/固件、真实浏览器矩阵和真实外部模型服务才能最终验收。

分阶段软件完成度估计如下：

| 阶段 | 软件完成度估计 | 当前判断 |
| --- | ---: | --- |
| Phase 0-10 / ARS-01 | 约 95% | 历史验收完成，基础闭环完整，仍有少量历史遗留风险 |
| ARS-02 | 约 85% | 空间、观测、状态估计主体完整；隐私删除、规模、备份和真实设备验收未闭环 |
| ARS-03 | 约 68% | Memory/History 基础能力和 Agent 只读检索已集成；高级记忆能力未完成 |
| ARS-04 | 约 45% | 确定性推理、单设备计划、Proactive L2 和 Mock 主动感知可用；AI/多步/前端未完成 |
| ARS-05 | 约 60% | 多模态框架、语音链路和隐私治理可用；六类 Provider 仍是 Mock |
| ARS-06 | 约 62% | 桌面机器人安全链、Profile、Consent、前端和只读 Agent 工具完成；硬件和固件 Adapter 未接入 |
| ARS-02 至 ARS-06 等权平均 | 约 64% | 主体软件能力已形成，但高级能力、生产能力和真实设备验收未闭环 |

百分比含义：

1. 百分比只估计“可审计软件实现与集成程度”。
2. 测试通过只说明被测路径可复现，不等价于功能完成或生产验收通过。
3. Mock 链路只能计为 Mock 软件能力，不能计为真实硬件能力。
4. 历史验收报告中的“条件通过”“未关闭”结论保持原样，本报告不关闭任何阶段。

## 2. 审计基线与方法

### 2.1 当前基线

本次审计开始时确认：

1. 当前分支：`main`。
2. 当前 HEAD：`e9537681d825b795fa90c93fccc3808bb6a789f7`。
3. 本地 `main` 领先 `origin/main` 1 个提交。
4. 未跟踪文件为：
   - `docs/35-ars06-acceptance-report.md`
   - `docs/36-full-project-review-2026-11-10.md`
5. 本次审计未修改业务代码，唯一新增文件是本报告。

### 2.2 已运行的验证

本次审计直接使用了当前工作区的以下验证结果：

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 后端测试 | `.venv\Scripts\python.exe -m pytest backend -q` | 通过：468 passed, 1 warning |
| 前端类型检查 | `pnpm typecheck` | 通过 |
| 前端格式检查 | `pnpm format:check` | 通过 |
| 前端单元测试 | `pnpm test` | 通过：3 files / 6 tests |
| 前端构建 | `pnpm build` | 通过；bundle 约 1.25 MB，有超过 500 kB 警告，非失败 |

唯一后端 warning 是既有的 Starlette TestClient / httpx deprecation warning，不是本次审计新增问题。

### 2.3 证据口径

本报告不按 README 或历史报告的完成口径直接判断代码状态，而是检查以下内容：

1. 应用装配：`backend/arvuno_core/app.py`。
2. API 到 Service、Repository、Adapter 的真实调用链。
3. Agent Runtime 到 Tool Registry 的能力暴露方式。
4. Task System、Tool Registry、Safety Policy、Tool Executor 与 Robot 的关系。
5. EventBus、Automation、Task、Environment Reconciler 的运行链路。
6. Retention Scheduler 在应用 lifespan 中的启动和停止。
7. 前端 `App.tsx`、`frontend/src/api/*`、`frontend/src/pages/*` 的实际路由和 API 调用。
8. `backend/tests/*` 中的单元、集成、Mock、隐私、安全和恢复测试。
9. `docs/20` 至 `docs/36` 的原始设计目标和历史验收边界。

本报告没有执行真实硬件测试，也没有使用用户根目录 `.env` 中的真实凭据。

## 3. 系统级真实调用链

### 3.1 应用装配

`backend/arvuno_core/app.py` 是当前模块化单体的核心装配点。它完成以下真实装配：

1. 创建 `DatabaseManager` 和 Unit of Work。
2. 创建 `EventBus`。
3. 创建 `DeviceRegistry`、设备服务、Environment Reconciler、DevicePollingRuntime。
4. 创建 `RobotApplicationService` 并同步 Mock Robot。
5. 创建 `ObservationPipeline`、`StateEstimationService`、Environment Context V2。
6. 创建 Memory、History、Reasoning、Planning、Proactive、Active Perception 服务。
7. 创建 Multimodal、Voice、Task、Automation、Tool Registry 和 Tool Executor。
8. 创建 `AgentRuntime`。
9. 在 lifespan 中启动/停止 Retention Scheduler，并在退出时执行任务和 Automation 恢复。
10. 挂载 devices、spaces、observations、state-estimates、environment、events、tools、tasks、agent、voice、automations、memory、multimodal、history、reasoning、robots、robot-perception、retention、planning、proactive、perception 等 API。

这说明主要模块不是孤立文件，而是已经进入应用运行时。

### 3.2 Agent Runtime 边界

`backend/arvuno_core/agent_runtime/runtime.py` 中的 Agent Runtime 不直接访问数据库，也不直接访问 Device Adapter。其真实路径是：

1. Agent Runtime 构建环境和任务上下文。
2. 通过 Tool Catalog 暴露可用工具。
3. 模型只生成候选任务参数。
4. Agent Runtime 校验风险兼容性。
5. 候选动作进入 Task System。
6. Task System 通过 Tool Registry、Safety Policy、Confirmation 和 Tool Executor 执行。

`backend/arvuno_core/agent_runtime/runtime.py` 的 `_validate_risk_compatibility` 只允许 `read_only` 工具，或者工具名为 `control_device` 且风险等级为 `low_risk`。因此虽然 Robot 写工具已经注册，Agent 当前不能直接选择 medium/high risk 的 Robot 动作。

### 3.3 Tool Registry

`backend/arvuno_core/tools/registry.py` 默认注册以下工具：

| 工具 | 调用对象 | 状态 |
| --- | --- | --- |
| `list_devices` | 设备查询链路 | 已集成 |
| `get_environment_state` | Environment Query Service | 已集成 |
| `retrieve_memory` | Memory Service | 已集成 |
| `query_history` | History Service | 已集成 |
| `get_device_state` | 设备状态链路 | 已集成 |
| `control_device` | Task / Safety / Tool Executor | 已集成 |

如果存在 `robot_service`，`register_robot_tools` 会继续注册：

1. 只读：`robot_status`、`robot_capabilities`、`robot_consents`、`robot_task_history`。
2. 受控动作：`robot_observe_scene`、`robot_look_at`、`robot_speak`、`robot_listen`、`robot_safe_stop`、`robot_idle`。

`backend/arvuno_core/tools/robot.py` 要求 Robot 写动作携带 `context.task_system`、`task_id`、`task_step_id`、`tool_execution_id`，并构造服务端 `RobotTaskRequestCreate`，强制 `confirmed=False`，再进入 `execute_preauthorized_task_request`。因此 Robot 动作不能由客户端用 `confirmed=true` 绕过。

### 3.4 机器人直接写入口封锁

以下入口现在会返回统一结构化错误 `ROBOT_EXECUTION_LOCKED`：

1. `backend/arvuno_core/api/robots.py` 中的直接写入口检查。
2. `backend/arvuno_core/api/robot_perception.py` 中的执行入口检查。
3. `backend/arvuno_core/perception/robot_mobile.py` 中的移动观察执行入口检查。

对应回归包括：

1. `backend/tests/test_robot_execution_lock.py`
2. `backend/tests/test_robot_adapter.py`
3. `backend/tests/test_robot_mobile_perception.py`
4. `backend/tests/test_robot_safety_chain.py`

所以当前系统不会因为存在 Mock Robot 而意外开放真实运动控制。

### 3.5 Retention Scheduler

`backend/arvuno_core/retention/scheduler.py` 提供 RetentionScheduler。

`backend/arvuno_core/app.py` 在 lifespan 中显式启动和停止 Scheduler。

`backend/arvuno_core/api/retention.py` 提供认证保护的管理接口：

1. `GET /api/retention/policies`
2. `GET /api/retention/status`
3. `GET /api/retention/failures`
4. `POST /api/retention/run`

对应测试为 `backend/tests/test_retention_scheduler.py`，覆盖幂等清理、独立策略、失败隔离、取消审计、并发冲突、认证和 lifespan 控制。

### 3.6 EventBus 与 Task 恢复

当前 EventBus 有订阅者超时、异常隔离和多订阅者隔离测试，见：

1. `backend/tests/test_event_task_reliability.py`
2. `backend/tests/test_event_runtime_assembly.py`
3. `backend/tests/test_automation_system.py`
4. `backend/tests/test_task_system.py`

应用 lifespan 会在启动时执行 Task Recovery 和 Automation Recovery，避免重启后简单把等待确认或执行结果未知的内容伪装成成功。

## 4. 前端真实完成度

### 4.1 已路由页面

`frontend/src/App.tsx` 当前路由以下页面：

| 页面 | 主要能力 | 状态 |
| --- | --- | --- |
| SystemOverview | 系统状态、环境概览 | 已集成 |
| DeviceList / DeviceDetail | 设备列表、详情、状态 | 已集成 |
| RobotManagement | Robot 状态、能力、Consent、任务请求、事件 | 已集成 |
| Spaces | 空间树、实体、设备、观测、部分历史 | 已集成 |
| Environment | 环境状态和 Snapshot | 已集成 |
| Events | 事件列表和详情 | 已集成 |
| Memory | Memory、偏好、检索、修正、删除 | 已集成 |
| Chat | Agent 对话、确认、语音交互 | 已集成 |
| TaskList / TaskDetail | 任务列表、详情、取消 | 已集成 |
| AutomationList / AutomationDetail | Automation、Run、通知 | 已集成 |
| Notifications | 通知列表和已读 | 已集成 |
| Settings | 系统设置 | 已集成 |

前端 API 客户端位于 `frontend/src/api/*`，主要通过 `frontend/src/api/client.ts` 统一处理带超时的 fetch。

### 4.2 死页面

`frontend/src/pages/SystemStatusPage.tsx` 存在，但没有在 `frontend/src/App.tsx` 中路由。这是一个已完成但未集成的前端页面。

### 4.3 前端未覆盖的后端能力

以下后端 API 已存在，但前端没有系统性管理入口：

1. `backend/arvuno_core/api/state_estimates.py`
2. `backend/arvuno_core/api/reasoning.py`
3. `backend/arvuno_core/api/planning.py`
4. `backend/arvuno_core/api/proactive.py`
5. `backend/arvuno_core/api/perception.py`
6. `backend/arvuno_core/api/retention.py`
7. 大部分 `backend/arvuno_core/api/multimodal.py` 管理能力
8. 大部分 `backend/arvuno_core/api/history.py` 查询能力

`frontend/src/pages/SpacesPage.tsx` 有观测和部分历史查询，但不能视为完整 History 管理界面。

## 5. REPAIR-01 与工程治理状态

REPAIR-01 的主要软件修复已经落地：

| 项目 | 当前状态 | 证据 |
| --- | --- | --- |
| 机器人直接执行封锁 | 已完成 | `api/robots.py`、`api/robot_perception.py`、`perception/robot_mobile.py`、`test_robot_execution_lock.py` |
| Provider Log 隐私最小化 | 已完成软件主体 | `backend/arvuno_core/ai/logging_support.py`、`backend/tests/test_provider_log_privacy.py` |
| Retention Scheduler | 已集成 | `backend/arvuno_core/retention/*`、`app.py`、`test_retention_scheduler.py` |
| 设备不可用事件状态机 | 已完成软件主体 | `backend/tests/test_device_availability_reconciliation.py` |
| Health Settings | 已完成 | `backend/tests/test_health.py` |
| EventBus 非阻塞 | 已完成软件主体 | `backend/tests/test_event_task_reliability.py` |
| Task 超时与恢复 | 已完成软件主体 | `backend/tests/test_task_system.py`、`test_event_task_reliability.py` |
| Robot Profile 冻结 | 已完成 Mock 治理 | `backend/arvuno_core/robots/profiles.py`、`test_robot_profiles.py` |
| Robot 安全执行链 | Mock 层已完成 | `backend/arvuno_core/tools/robot.py`、`test_robot_safety_chain.py` |
| Robot 前端管理页 | 已完成 Mock 层 | `frontend/src/pages/RobotManagementPage.tsx` |

REPAIR-01 的修复不等于 ARS-06 关闭，也不等于真实机器人验证通过。

## 6. ARS-02：World Environment 与 State Estimation

### 6.1 原始设计目标

原始目标主要来自：

1. `docs/20-ars02-spatial-model-design.md`
2. `docs/21-ars02-observation-model-design.md`
3. `docs/22-ars02-state-estimation-design.md`
4. `docs/23-ars02-migration-and-api-design.md`
5. `docs/24-ars02-testing-and-acceptance.md`
6. `docs/25-ars02-real-esphome-acceptance.md`
7. `docs/26-ars02-final-acceptance-report.md`

核心目标是建立空间模型、实体归属、观测契约、状态估计、Environment Context V2、保留治理、API、Tool、AI 查询和 Web Console，并最终接入真实 ESPHome/ESP32。

### 6.2 已完成并进入业务链路的软件功能

| 功能 | 实现证据 | 集成证据 |
| --- | --- | --- |
| 空间树和空间路径 | `backend/arvuno_core/spatial/service.py`、`backend/arvuno_core/persistence/spatial.py` | `backend/arvuno_core/api/spaces.py`、`frontend/src/api/spaces.ts`、`frontend/src/pages/SpacesPage.tsx` |
| 实体与设备归属 | `backend/arvuno_core/persistence/spatial.py` | Spaces API 和前端实体归属操作 |
| Observation 归一化与入库 | `backend/arvuno_core/observations/pipeline.py`、`backend/arvuno_core/observations/service.py` | Device Polling、Mock Adapter、Home Assistant Adapter、State Estimation 重建链路 |
| Observation 质量、去重、采样 | `backend/arvuno_core/observations/pipeline.py` | `backend/tests/test_observation_pipeline.py` |
| State Estimation | `backend/arvuno_core/estimation/service.py`、`backend/arvuno_core/persistence/state_estimates.py` | `backend/arvuno_core/api/state_estimates.py`、Environment Context V2 |
| Append-only 历史 | `backend/arvuno_core/persistence/state_estimates.py` | `backend/tests/test_state_estimation.py` |
| Environment Context V2 | `backend/arvuno_core/environment/context_v2.py` | `backend/arvuno_core/api/environment.py`、`tools/registry.py` |
| 设备轮询与状态一致性 | `backend/arvuno_core/devices/polling_runtime.py` | `app.py` lifespan、`test_polling_runtime.py`、`test_device_availability_reconciliation.py` |
| 只读环境 Tool | `backend/arvuno_core/tools/registry.py` | Agent Runtime 只能通过 Tool Catalog 调用 |

### 6.3 已完成但尚未完全集成的功能

| 功能 | 当前状态 | 证据 |
| --- | --- | --- |
| State Estimates 管理 API | 后端已实现 | `backend/arvuno_core/api/state_estimates.py` |
| State Estimates 前端管理页 | 未实现 | `frontend/src/api/` 没有 state-estimates 客户端，`App.tsx` 没有页面 |
| Environment Snapshot API | 后端和 Environment 页面已实现 | `frontend/src/pages/EnvironmentPage.tsx` |
| 深度历史查询 API | 后端完整，前端只有 Spaces 局部入口 | `backend/arvuno_core/api/history.py`、`frontend/src/pages/SpacesPage.tsx` |

### 6.4 尚未完成的软件功能

| 功能 | 当前状态 | 证据或缺口 |
| --- | --- | --- |
| 隐私删除端到端闭环 | 未完成 | 历史报告 `docs/26` D3；衍生副本、日志、备份边界仍需统一验收 |
| 重复归属 interval 收敛 | 需要进一步确认 | `docs/26` D2 |
| 目标规模 SQLite 性能验证 | 未执行 | `docs/26` D4；20/50/200 传感器场景未完整压测 |
| 生产级备份恢复演练 | 未执行 | `backend/arvuno_core/persistence/backup.py` 有软件实现，但生产演练未闭环 |

### 6.5 需要硬件或外部环境的功能

| 功能 | 当前状态 | 阻塞 |
| --- | --- | --- |
| 真实 ESPHome/ESP32 接入 | 未验收 | `docs/25` 和 `docs/26` 明确要求硬件后执行 H1-H11 |
| 长时间断线重连和真实时钟漂移 | 未验收 | 需要真实设备时钟和网络环境 |
| 真实 AI Provider 查询验收 | 未执行 | 需要外部模型服务与凭据 |
| 真实 Home Assistant 长期运行 | 未验收 | 需要受控 HA 环境 |

### 6.6 测试覆盖

主要测试：

1. `backend/tests/test_spatial_model.py`
2. `backend/tests/test_observation_model.py`
3. `backend/tests/test_observation_pipeline.py`
4. `backend/tests/test_state_estimation.py`
5. `backend/tests/test_environment_context_v2_consistency.py`
6. `backend/tests/test_environment_consistency.py`
7. `backend/tests/test_environment_query_tools.py`
8. `backend/tests/test_device_availability_reconciliation.py`
9. `backend/tests/test_polling_runtime.py`
10. `backend/tests/test_backup_restore.py`

这些测试覆盖归一化、重复去重、迟到数据、失败恢复、状态估计溯源、append-only 历史、Context V2、轮询和备份恢复边界。但没有全量覆盖率报告，不能据此宣称生产规模和真实设备完成。

### 6.7 阻塞与依赖

1. 隐私删除闭环依赖统一数据边界设计。
2. SQLite 压测依赖目标规模数据集和性能指标。
3. 真实 ESPHome 验收依赖硬件。
4. 真实 AI Provider 验收依赖外部服务凭据。
5. 前端 State Estimates 管理页依赖 API 契约确认。

### 6.8 软件完成度判断

ARS-02 软件完成度约 **85%**。

主体软件链路已经形成：Device/Observation -> ObservationPipeline -> StateEstimation -> Context V2 -> API/Tool -> Frontend。但 ARS-02 不能关闭，因为隐私删除端到端、规模压测、备份恢复、真实 ESPHome/ESP32 和真实 AI Provider 验收尚未完成。

## 7. ARS-03：World Memory 与时间理解

### 7.1 原始设计目标

原始目标来自：

1. `docs/27-ars03-history-time-understanding.md`
2. `docs/28-ars03-acceptance-report.md`

核心目标是建立记忆类型、来源、修订、确认、修正、过期、删除、程序性记忆验证、历史时间理解、自然语言历史查询、知识提炼和长期记忆能力。

### 7.2 已完成并进入业务链路的软件功能

| 功能 | 实现证据 | 集成证据 |
| --- | --- | --- |
| Episodic / Semantic / Procedural Memory | `backend/arvuno_core/memory/service.py`、`backend/arvuno_core/persistence/memory.py` | `backend/arvuno_core/api/memory.py` |
| 用户偏好 | `backend/arvuno_core/memory/service.py` | Memory API 和 `frontend/src/pages/MemoryPage.tsx` |
| Memory 修订、确认、修正、删除、过期 | `backend/arvuno_core/memory/service.py` | `backend/tests/test_memory_system.py` |
| Procedure validation | `backend/arvuno_core/api/memory.py` | API 层可创建验证记录 |
| History 时间范围查询 | `backend/arvuno_core/history/service.py` | `backend/arvuno_core/api/history.py` |
| 空间 / 实体 / 趋势 / 快照 diff / 关联历史 | `backend/arvuno_core/history/service.py` | `backend/arvuno_core/api/history.py` |
| 自然语言历史受限查询 | `backend/arvuno_core/history/service.py` | `backend/tests/test_history_time_understanding.py` |
| Agent Memory 检索 | `backend/arvuno_core/tools/registry.py` | `retrieve_memory` 被 Agent Runtime 使用 |
| Agent History 查询 | `backend/arvuno_core/tools/registry.py` | `query_history` 被 Agent Runtime 使用 |
| Memory 前端 | `frontend/src/pages/MemoryPage.tsx` | `frontend/src/api/memory.ts` |

### 7.3 已实现但尚未集成的功能

| 功能 | 当前状态 | 证据 |
| --- | --- | --- |
| 事件查询意图映射 | `AgentIntentType.EVENT_QUERY -> query_events` 存在 | `backend/arvuno_core/agent_runtime/models.py` |
| `query_events` 工具 | Tool Registry 没有注册该工具 | `backend/arvuno_core/tools/registry.py` |
| 完整 History 管理前端 | 后端 API 存在，前端未覆盖 | `backend/arvuno_core/api/history.py`、`frontend/src/api/` |

### 7.4 尚未实现的软件功能

| 功能 | 当前状态 | 证据 |
| --- | --- | --- |
| 语义检索 | 未实现 | `docs/28` 明确当前只有关系过滤和 `LIKE` |
| SQLite FTS | 未实现 | `docs/28` 明确列为未实现 |
| 自动记忆压缩 | 未实现 | 无压缩引擎调用链 |
| 长期知识提炼 | 未实现 | `docs/28` 明确未完成 |
| Memory Graph | 未实现 | 无图模型和图查询链路 |
| 多用户 / 家庭成员隔离 | 未实现 | 当前部署契约仍是单用户/本地用户 |
| 工具执行自动产生 procedure validation | 未实现 | 当前验证记录主要通过 API 显式创建 |
| Memory evidence 数据库级强外键全覆盖 | 未实现 | 当前部分依赖创建时校验和应用层引用 |

### 7.5 需要硬件或外部环境的功能

| 功能 | 当前状态 | 阻塞 |
| --- | --- | --- |
| 真实 AI Provider 稳定调用 Memory/History | 未验收 | 需要真实模型 |
| 真实长期使用中的记忆质量 | 未验收 | 需要长期真实对话和事件数据 |
| 生产规模 SQLite / 数据库性能 | 未验收 | 需要目标规模数据 |

### 7.6 测试覆盖

主要测试：

1. `backend/tests/test_memory_system.py`
2. `backend/tests/test_history_time_understanding.py`
3. `backend/tests/test_agent_memory_history_tools.py`
4. `backend/tests/test_agent_runtime.py`
5. `backend/tests/test_correlation_id.py`

覆盖内容包括授权、来源证据、AI 推断候选语义、用户修正、确认、冲突、过期、删除、偏好治理、时间边界、迟到/未来数据、空间历史、趋势、快照 diff、关联和自然语言受限回答。

### 7.7 阻塞与依赖

1. 语义检索需要先确定向量库、FTS 或混合检索架构。
2. 多用户隔离会改变数据契约和权限模型，不能顺手实现。
3. 自动压缩和知识提炼需要可靠来源、审计和不可逆删除策略。
4. 事件查询工具需要补齐注册和契约。
5. 前端 History 页面需要查询模型和 UX 设计。

### 7.8 软件完成度判断

ARS-03 软件完成度约 **68%**。

Memory 和 History 的基础能力已经真实进入 Agent 和前端调用链。但原始设计中的语义检索、自动压缩、知识提炼、记忆图谱、多用户隔离和真实程序验证链仍未完成。不能把当前的键值/关系型记忆说成完整 World Memory。

## 8. ARS-04：World Reasoning 与 Orchestration

### 8.1 原始设计目标

原始目标来自：

1. `docs/29-ars04-world-reasoning-orchestration-design.md`
2. `docs/30-ars04-acceptance-report.md`

核心目标是建立证据模型、假设、目标、计划、重规划、主动建议、主动感知、用户授权、多步任务编排和有限自主执行。

### 8.2 已完成并进入业务链路的软件功能

| 功能 | 实现证据 | 集成证据 |
| --- | --- | --- |
| Reasoning Session / Evidence / Hypothesis | `backend/arvuno_core/reasoning/service.py`、`backend/arvuno_core/persistence/reasoning.py` | `backend/arvuno_core/api/reasoning.py` |
| 确定性规则推理 | `backend/arvuno_core/reasoning/service.py` | Active Perception 可触发重跑 |
| Goal / Plan / Plan Step | `backend/arvuno_core/planning/service.py`、`backend/arvuno_core/persistence/planning.py` | `backend/arvuno_core/api/planning.py` |
| 单设备计划执行 | `backend/arvuno_core/planning/service.py` | Plan 提交后进入 Task System，最终走 Tool Executor |
| Replanning | `backend/arvuno_core/planning/service.py` | 失败后生成新版本并保留历史 |
| Proactive Suggestion | `backend/arvuno_core/proactive/service.py` | EventBus 订阅异常/任务失败/传感器事件 |
| 去重、冷却、静默时间、频率限制 | `backend/arvuno_core/proactive/service.py` | `backend/tests/test_proactive_intelligence.py` |
| 通知上限 | `backend/arvuno_core/automation/notifications.py` | Automation/Notification 前端可见 |
| Active Perception Request | `backend/arvuno_core/perception/service.py` | `backend/arvuno_core/api/perception.py` |
| Mock Observer 闭环 | 测试中可注入 Observer | Mock 结果写入 Observation、更新状态估计并重跑 Reasoning |

### 8.3 已实现但尚未集成的功能

| 功能 | 当前状态 | 证据 |
| --- | --- | --- |
| Active Perception 与 Task System / Tool Executor 的正式执行链 | 未完成 | 当前默认应用 `app.state.perception_observer = None`，`backend/arvuno_core/app.py` 约 581 行 |
| Reasoning / Planning / Proactive / Perception 后端 API | 已实现 | 对应 API 文件 |
| 对应前端管理页 | 未实现 | `App.tsx` 没有相关路由，`frontend/src/api/` 没有对应客户端 |
| Proactive L3 候选任务创建 | 未实现 | `docs/30` 明确未完成 |

### 8.4 尚未实现的软件功能

| 功能 | 当前状态 | 证据 |
| --- | --- | --- |
| AI / 模型 Planner | 未实现 | 当前只有确定性规则 Planner |
| AI Proactive Evaluator | 未实现 | 当前是规则触发和确定性阈值 |
| AI Perception Evaluator | 未实现 | 当前使用确定性缺口和来源比较 |
| 多步计划 | 未实现 | `docs/30` 明确当前只支持单设备计划 |
| 非设备计划 | 未实现 | 当前计划边界是设备动作 |
| Proactive L3 自动创建候选任务 | 未实现 | `docs/30` 明确未完成 |
| Proactive L4 有限自主执行 | 未实现，默认禁止 | `docs/30` 明确默认禁止 |
| 默认生产 Observer | 未配置 | `app.state.perception_observer = None` |
| 真实隐私授权界面 | 未完成 | 当前是认证 API 和作用域校验，不是完整用户授权 UX |

### 8.5 需要硬件或外部环境的功能

| 功能 | 当前状态 | 阻塞 |
| --- | --- | --- |
| 真实 AI Provider 推理/规划 | 未验收 | 需要外部模型服务 |
| 真实摄像头、麦克风或机器人 Observer | 未实现 | 需要硬件/固件 |
| 真实设备控制长期效果 | 未验收 | 需要真实设备环境 |
| 真实主动感知硬件导航 | 未实现 | 依赖 ARS-06 真实机器人 |

### 8.6 测试覆盖

主要测试：

1. `backend/tests/test_reasoning_engine.py`
2. `backend/tests/test_planning_engine.py`
3. `backend/tests/test_proactive_intelligence.py`
4. `backend/tests/test_active_perception.py`
5. `backend/tests/test_event_runtime_assembly.py`
6. `backend/tests/test_automation_system.py`

覆盖内容包括证据溯源、因果升级边界、坏数据不变成事实、目标确认、授权上限、离线设备拒绝、计划提交、失败重规划、Proactive L1/L2、冷却、静默时间、频率限制、事件集成、Mock Observer、敏感授权、过期授权和架构边界。

### 8.7 阻塞与依赖

1. AI Planner 需要 Provider 契约、提示边界、候选校验和失败语义。
2. 多步计划需要 Task Step、回滚、状态验证和取消语义进一步设计。
3. Proactive L3/L4 需要更强授权和风险边界。
4. Active Perception 默认执行链需要 Observer 注入策略。
5. 前端页面依赖 Reasoning/Planning/Proactive 查询契约稳定。

### 8.8 软件完成度判断

ARS-04 软件完成度约 **45%**。

当前系统拥有可用的确定性推理、单设备计划、Proactive L2 和 Mock Active Perception。但完整设计目标中的 AI 化候选生成、多步编排、非设备计划、L3/L4、真实 Observer 和前端管理面都没有完成。这是当前完成度最低的主要阶段。

## 9. ARS-05：Multimodal Perception

### 9.1 原始设计目标

原始目标来自：

1. `docs/31-ars05-multimodal-perception-design.md`
2. `docs/32-ars05-acceptance-report.md`

核心目标是覆盖视觉、OCR、STT、TTS、Audio Event、Fusion、媒体生命周期、授权、隐私删除、Provider 边界、语音交互和真实硬件验收。

### 9.2 已完成并进入业务链路的软件功能

| 功能 | 实现证据 | 集成证据 |
| --- | --- | --- |
| Capture Session / Media Asset | `backend/arvuno_core/multimodal/service.py`、`backend/arvuno_core/persistence/multimodal.py` | `backend/arvuno_core/api/multimodal.py` |
| 私有媒体存储 | `backend/arvuno_core/multimodal/` | Media content API |
| Consent / Data Access Grant / Audit | `backend/arvuno_core/multimodal/` | Multimodal API 和 Fusion 前置检查 |
| Vision / OCR / STT / Audio Event / TTS Provider 抽象 | `backend/arvuno_core/multimodal/` | 分析、转写、音频事件和 TTS API |
| Multimodal Fusion | `backend/arvuno_core/multimodal/` | `/fusion/query` API |
| 敏感输出物理删除 | `backend/arvuno_core/multimodal/` | `test_multimodal_fusion_privacy.py` |
| 过期媒体清理方法 | `backend/arvuno_core/multimodal/` | REPAIR-01 后接入 Retention Scheduler |
| 语音指令链路 | `backend/arvuno_core/voice/service.py` | `backend/arvuno_core/api/voice.py` |
| 语音确认 | `backend/arvuno_core/voice/service.py` | ChatPage 和 Voice API |
| 前端录音与语音状态机 | `frontend/src/hooks/useVoiceRecorder.ts`、`frontend/src/hooks/useVoiceInteraction.ts` | `frontend/src/pages/ChatPage.tsx` |

### 9.3 已实现但尚未集成的功能

| 功能 | 当前状态 | 证据 |
| --- | --- | --- |
| Multimodal 管理前端 | 后端 API 大量存在，前端缺失 | `backend/arvuno_core/api/multimodal.py`；`frontend/src/api/` 只有 voice 相关 |
| Multimodal Retention | 后端已接入 Scheduler，但没有前端运维界面 | `backend/arvuno_core/api/retention.py`、`frontend/src/api/` |

### 9.4 仅 Mock 或模拟实现的功能

| Provider / 能力 | 当前状态 |
| --- | --- |
| `vision_scene` | Mock |
| `vision_object` | Mock |
| OCR | Mock |
| STT | Mock |
| Audio Event | Mock |
| TTS | Mock |
| 云 Provider / fallback / 配额重试 | 未接入生产服务 |
| 持续唤醒词 | 未实现 |
| 持续视频/音频分析 | 未实现 |
| 人脸、声纹、人员追踪、情绪识别 | 未实现 |

这些能力有服务抽象和 API，但没有真实模型识别能力。

### 9.5 尚未实现的软件功能

| 功能 | 当前状态 | 证据 |
| --- | --- | --- |
| 真实视觉 Provider Adapter | 未实现 | 六类 Provider 均 Mock |
| 真实 STT/TTS Adapter | 未实现 | 当前验证只到 Mock Provider |
| 云端 Provider 合规与配额治理 | 未实现 | `docs/32` 明确未验收 |
| 独立后台唤醒词服务 | 未实现 | 当前唤醒词只作用于单次转写结果 |
| 多模态实体语义对齐 | 未完整实现 | 当前 Fusion 是时间/空间/关联证据组织 |
| Multimodal 管理前端 | 未实现 | API 无系统性 UI |
| 冷存储、大规模媒体生命周期演练 | 未执行 | `docs/32` 明确未完成 |

### 9.6 需要硬件或外部环境的功能

| 功能 | 当前状态 | 阻塞 |
| --- | --- | --- |
| 真实摄像头采集 | 未验收 | 需要硬件与操作系统权限 |
| 真实麦克风采集 | 未验收 | 需要硬件与浏览器权限矩阵 |
| 真实扬声器播放 | 未验收 | 需要硬件 |
| 真实视觉/语音模型 | 未验收 | 需要外部模型服务或本地模型部署 |
| 真实浏览器矩阵和可访问性 | 未验收 | 需要真实浏览器/移动端环境 |

### 9.7 测试覆盖

主要测试：

1. `backend/tests/test_multimodal_fusion_privacy.py`
2. `backend/tests/test_multimodal_observation_access.py`
3. `backend/tests/test_voice_interaction.py`
4. `backend/tests/test_retention_scheduler.py`
5. `frontend/src/api/voice.test.ts`
6. `frontend/src/hooks/useVoiceInteraction.test.ts`

覆盖内容包括 Fusion 证据来源、重复/冲突、授权撤销、敏感 OCR/转写物理删除、语音唤醒词、非指令内容拦截、确认语义、音频清理和前端状态机。这些主要是 Mock/集成测试，不是真实模型或真实硬件验收。

### 9.8 阻塞与依赖

1. 真实 Provider Adapter 依赖外部服务或本地模型部署方案。
2. 云 Provider 需要隐私、合规、配额、重试和审计设计。
3. 管理前端依赖 Provider/媒体/授权 API 的运维视图设计。
4. 后台唤醒词与持续采集会显著扩大隐私边界，不应混入普通单次语音链路。
5. 真实浏览器体验需要硬件和真实浏览器矩阵。

### 9.9 软件完成度判断

ARS-05 软件完成度约 **60%**。

媒体生命周期、隐私治理和语音业务链路已经可用，但所有识别和生成 Provider 仍是 Mock。当前应描述为“多模态框架与隐私治理 Mock 条件可用”，不能描述为多模态感知完成。

## 10. ARS-06：Embodied Intelligence 与桌面机器人

### 10.1 原始设计目标

原始目标来自：

1. `docs/33-ars06-embodied-intelligence-design.md`
2. `docs/34-ars06-custom-desktop-robot-design.md`
3. `docs/35-ars06-acceptance-report.md`
4. `docs/36-full-project-review-2026-11-10.md`

当前硬件目标是 `docs/34` 中的自制桌面机器人。移动机器人能力只能保留为未来 Profile，不得在当前桌面机器人上开放。

### 10.2 已完成并进入业务链路的软件功能

| 功能 | 实现证据 | 集成证据 |
| --- | --- | --- |
| `desktop_robot` Profile | `backend/arvuno_core/robots/profiles.py` | `backend/arvuno_core/robots/service.py`、`test_robot_profiles.py` |
| `mobile_robot` Profile 治理壳 | `backend/arvuno_core/robots/profiles.py` | 移动动作被拒绝，`test_robot_safety_chain.py` |
| Robot Adapter 边界 | `backend/arvuno_core/robots/mock.py` | 当前仍是 Mock Adapter |
| Robot 状态、能力、任务、事件模型 | `backend/arvuno_core/persistence/models.py`、`backend/arvuno_core/persistence/robots.py` | Robot API |
| 直接写入口封锁 | `backend/arvuno_core/api/robots.py` | `ROBOT_EXECUTION_LOCKED`，`test_robot_execution_lock.py` |
| 统一安全执行链 | `backend/arvuno_core/tools/robot.py` | Robot Tool -> Task -> Registry -> Safety -> Executor -> Adapter |
| Consent | `backend/arvuno_core/robots/service.py` | Capability `requires_consents` 执行前检查 |
| 单次确认 Token | `backend/arvuno_core/robots/service.py` | Token 绑定参数、过期、单次使用；客户端 `confirmed=true` 无效 |
| Heartbeat / freshness | `backend/arvuno_core/robots/` | `test_robot_failsafe_state.py` |
| 安全停止语义 | `backend/arvuno_core/robots/service.py` | `robot_safe_stop` 工具和 API |
| 取消失败 / 结果未知语义 | `backend/arvuno_core/robots/service.py` | `test_robot_failsafe_state.py` |
| Robot 前端管理页 | `frontend/src/pages/RobotManagementPage.tsx` | `frontend/src/api/robots.ts` |
| Agent 只读查询工具 | `backend/arvuno_core/tools/robot.py` | `robot_status`、`robot_capabilities`、`robot_consents`、`robot_task_history` |

### 10.3 已实现但尚未集成的功能

| 功能 | 当前状态 | 证据 |
| --- | --- | --- |
| Robot 写工具注册 | Tool Registry 已注册 | `backend/arvuno_core/tools/registry.py` |
| Agent 选择 Robot 写工具 | 被 Agent 风险门禁阻止 | `backend/arvuno_core/agent_runtime/runtime.py` 只允许 read-only 或 low-risk `control_device` |
| Robot Adapter | Mock Adapter 可执行测试动作 | 尚无真实桌面机器人硬件 Adapter |
| Robot 前端管理页 | Mock API 层可用 | 无真实硬件状态可展示 |

### 10.4 仅 Mock 或模拟实现的功能

| 能力 | 当前状态 |
| --- | --- |
| `report_status` | Mock 可用 |
| `look_at` | Mock 可用 |
| `observe_scene` | Mock 可用，无真实视觉分析 |
| `request_safe_stop` | Mock 软件链路可用，无物理急停验证 |
| `enter_idle_pose` | Mock 可用 |
| `speak` | Mock 可用，无真实扬声器验收 |
| `listen` | Mock/按需授权链路可用，无真实麦克风验收 |
| `navigate_to` | 桌面 Profile 禁止 |
| `return_to_dock` | 桌面 Profile 禁止 |
| `charge` | 未按真实桌面硬件能力开放 |

### 10.5 尚未实现的软件功能

| 功能 | 当前状态 | 证据 |
| --- | --- | --- |
| 真实桌面机器人通信 Adapter | 未实现 | 当前只有 Mock Adapter |
| 固件契约与协议适配 | 未实现 | 没有 BOM/固件/协议验收 |
| 真实能力证据链 | 未实现 | `docs/35` 明确没有真实硬件证据 |
| 真实视觉分析 | 未实现 | 依赖 ARS-05 Provider |
| 真实语音采集/播放 | 未实现 | 依赖硬件和 ARS-05 Provider |
| 机械限位、看门狗、急停实测联动 | 未实现 | 需要固件与硬件 |
| 真实移动能力 | 不开放 | 当前桌面目标不支持，未来移动 Profile 默认禁用 |

### 10.6 需要硬件或外部环境的功能

| 功能 | 当前状态 | 阻塞 |
| --- | --- | --- |
| 桌面机器人装配与固件 | 未开始/未验收 | 依赖硬件和固件实现 |
| 摄像头、麦克风、扬声器实测 | 未验收 | 依赖硬件 |
| 独立安全停止验证 | 未验收 | `docs/34` 要求机器人本体具备独立机制 |
| 物理动作限位和安全包络 | 未验收 | 依赖机械/电气/固件 |
| 真实网络断连/重连 | 未验收 | 依赖真实运行环境 |

### 10.7 测试覆盖

主要测试：

1. `backend/tests/test_robot_profiles.py`
2. `backend/tests/test_robot_adapter.py`
3. `backend/tests/test_robot_execution_lock.py`
4. `backend/tests/test_robot_safety_chain.py`
5. `backend/tests/test_robot_failsafe_state.py`
6. `backend/tests/test_robot_management_interface.py`
7. `backend/tests/test_robot_mobile_perception.py`
8. `backend/tests/test_ars06_acceptance.py`

覆盖内容包括 Profile 边界、能力治理、Consent 缺失/过期/撤销/空间不匹配、确认 Token 缺失/过期/复用/参数变化、任务-工具-机器人关联、执行失败、状态验证失败、直接调用拒绝、移动能力禁止、高风险拒绝、心跳、失效安全和前端 API。

这些都属于 Mock 或集成安全测试，不能替代真实机器人验收。

### 10.8 阻塞与依赖

1. 真实硬件 Adapter 依赖最终 BOM、固件协议和安全包络确认。
2. 真实观察依赖 ARS-05 的视觉 Provider。
3. 真实语音依赖 ARS-05 的音频 Provider。
4. Agent Robot 写动作开放需要风险门禁和用户授权策略变更，不能简单把工具暴露给 Agent。
5. 真实安全停止必须由机器人本体独立实现，不能依赖网络或 AI。

### 10.9 软件完成度判断

ARS-06 软件完成度约 **62%**。

Mock/软件治理层已经相当完整：Profile、安全链、Consent、单次确认、状态、前端和只读 Agent 工具都有测试。但真实硬件 Adapter、真实固件契约、真实能力证据和物理安全验证完全未开始，ARS-06 不能关闭。

## 11. 数据治理与隐私状态

### 11.1 Provider Log

当前默认 Provider Log 只保存运行元数据，不保存完整 messages、完整 system prompt、完整模型响应或凭据。相关实现和回归：

1. `backend/arvuno_core/ai/logging_support.py`
2. `backend/tests/test_provider_log_privacy.py`
3. `backend/tests/test_logging_redaction.py`

Debug 全文能力保持显式开启、默认关闭、可过期清理的软件边界。真实生产运行中的开启行为还需要运维约束复核。

### 11.2 Retention

Retention Scheduler 已经真实接入应用 lifespan，覆盖 Event、Observation、Multimodal、Proactive、Environment Snapshot、Provider Log 等策略。

主要实现：

1. `backend/arvuno_core/retention/scheduler.py`
2. `backend/arvuno_core/retention/service.py`
3. `backend/arvuno_core/api/retention.py`

主要测试：

1. `backend/tests/test_retention_scheduler.py`
2. `backend/tests/test_observation_pipeline.py`

保留清理已有软件闭环，但还没有前端运维界面，也没有生产规模演练。

### 11.3 Multimodal 媒体

当前系统区分数据库元数据和私有媒体文件。敏感 OCR/转写可以物理删除，媒体过期清理已接入 Scheduler。

已有测试：

1. `backend/tests/test_multimodal_fusion_privacy.py`
2. `backend/tests/test_multimodal_observation_access.py`

仍需完成：

1. 生产媒体目录备份清单。
2. 数据库与媒体一致性恢复演练。
3. 孤立媒体文件的长期巡检。
4. 备份恢复后媒体引用完整性验证。

不能把“SQLite 恢复成功”说成“包含媒体在内的全系统恢复成功”。

### 11.4 Privacy Erasure

当前有 Memory 删除、Multimodal purge、日志脱敏和 Retention 清理，但“用户数据删除请求”的端到端边界仍未完全验收：

1. 数据库主记录。
2. 衍生证据。
3. Provider Log。
4. Event/Observation。
5. 媒体文件。
6. 备份。
7. 授权审计中依法或按设计需要保留的记录。

因此 ARS-02 的隐私删除端到端仍应保持未关闭。

## 12. 只有架构、接口或孤立模块，但没有形成完整业务能力的清单

| 项 | 当前状态 | 证据 | 缺口 |
| --- | --- | --- | --- |
| Agent Robot 写工具 | 已注册 | `tools/robot.py`、`tools/registry.py` | Agent Runtime 风险门禁不允许选择，实际 Agent 业务动作仍不能发起 Robot 写 |
| Robot 写动作 | Mock 安全链完整 | `test_robot_safety_chain.py` | 没有真实硬件，动作不能产生真实物理效果 |
| Mobile Robot Profile | 存在治理壳 | `robots/profiles.py`、`test_robot_safety_chain.py` | 没有移动机器人硬件和审批，不能执行移动能力 |
| Active Perception 默认执行 | Request 生命周期存在 | `api/perception.py` | 默认 `perception_observer=None`，生产应用无法执行真实观察 |
| Reasoning AI 候选生成 | 架构预留 | `docs/30` | 当前没有接入模型候选生成 |
| `query_events` | 意图映射存在 | `agent_runtime/models.py` | Tool Registry 没有 `query_events` 工具 |
| Multimodal Providers | Provider 抽象和 API 存在 | `multimodal/`、`api/multimodal.py` | 六类 Provider 均 Mock |
| Robot Mobile Perception | API/Service 存在 | `perception/robot_mobile.py` | 执行入口锁定，且没有真实机器人 |
| SystemStatusPage | 页面存在 | `frontend/src/pages/SystemStatusPage.tsx` | 没有路由 |
| History API | 后端能力较完整 | `api/history.py` | 前端只有局部入口，用户不能系统性使用 |
| State Estimates API | 后端可查询/重建 | `api/state_estimates.py` | 前端没有 API 客户端和页面 |
| Retention API | 后端运维接口可用 | `api/retention.py` | 前端没有运维页面 |

这些项必须在后续阶段明确纳入集成范围，不能因为接口存在而计为业务能力完成。

## 13. 纯软件缺口清单

以下缺口不依赖购买硬件，可以在当前 Windows/受控开发环境继续开发或验证。

### 13.1 数据与隐私

1. 设计并实现用户级 Privacy Erasure 编排。
2. 明确数据库、媒体、日志、备份、审计记录的删除和保留边界。
3. 建立 SQLite 与媒体目录的备份清单和一致性恢复验证。
4. 完成 20/50/200 传感器场景 SQLite 性能测试。
5. 修复或明确不同 `assignment_type` 重复归属 interval 的收敛规则。
6. 增加 Retention 前端管理页。

### 13.2 Memory 与 History

1. 实现语义检索或 SQLite FTS 混合检索。
2. 设计 Memory 自动压缩策略。
3. 实现长期知识提炼和事实升级边界。
4. 设计 Memory Graph 或至少关系型知识关联视图。
5. 补齐完整 History 前端。
6. 注册 `query_events` 工具，或移除死意图映射。
7. 补齐工具执行自动生成 procedure validation 的链路。

### 13.3 Reasoning、Planning 与 Proactive

1. 实现真实 AI Provider 的 Reasoning 候选生成器。
2. 实现 AI Planner 或 AI 辅助 Planner，并保留确定性校验。
3. 支持多步 Plan Step、依赖、失败分支和取消。
4. 支持非设备计划类型。
5. 实现 Proactive L3 接受后创建候选任务。
6. 重新评估 Proactive L4 的授权边界，当前必须保持默认禁止。
7. 为 Reasoning、Planning、Proactive、Active Perception 增加前端页面。
8. 将 Active Perception 与 Task System / Tool Executor 正式受控集成。

### 13.4 Multimodal

1. 设计真实 Provider Adapter 契约。
2. 实现可替换的 STT、TTS、视觉、OCR、Audio Event Provider。
3. 增加云 Provider 超时、重试、取消、部分结果和配额治理。
4. 实现 Multimodal 管理前端。
5. 完善媒体备份清单与恢复一致性工具。
6. 明确独立唤醒词与持续采集是否进入产品范围；若进入，必须先扩展隐私治理。

### 13.5 Robot 纯软件部分

1. 定义真实桌面机器人固件通信协议契约。
2. 实现可测试的固件 Simulator / Contract Adapter。
3. 完善真实状态反馈验证规则。
4. 完善任务超时、取消失败和安全停止请求的仿真回归。
5. 增加 Robot Audit / Safety Event 运维视图。
6. 明确 Agent 未来何时可以调用 Robot 写工具的风险门禁策略。

### 13.6 工程与前端

1. 移除或路由 `SystemStatusPage.tsx`。
2. 补齐 State Estimates 前端。
3. 增加 History 管理前端。
4. 增加 Retention 运维前端。
5. 优化前端 bundle，消除超过 500 kB 的 build warning。
6. 增加关键业务路径的覆盖率和性能基准。
7. 保持测试不依赖根目录 `.env` 或开发者本机环境变量。

## 14. 必须依赖硬件、固件或外部环境验证的清单

以下项不能仅通过当前 Mock 测试关闭。

| 类别 | 必须验证的内容 |
| --- | --- |
| ESP32 / ESPHome | 真实传感器发现、时钟、断线重连、读数质量、安全写边界 |
| Home Assistant | 受控真实 HA 实例的实体映射、事件语义和长期同步 |
| AI Provider | 真实模型下的 Agent、Memory/History、Reasoning、Planning、Proactive 效果与失败语义 |
| 摄像头 | 采集权限、时间戳、媒体质量、隐私删除 |
| 麦克风 | 录音权限、噪声环境、浏览器矩阵、音频清理 |
| 扬声器 | TTS 播放质量、延迟、设备释放 |
| 桌面机器人硬件 | BOM、装配、固件、通信、限位、看门狗、独立急停 |
| 机器人感知 | 真实摄像头、真实视觉分析、观察结果验证 |
| 机器人语音 | 真实麦克风采集和扬声器播放 |
| 真实浏览器 | 桌面/移动浏览器矩阵、object URL 释放、录音状态机 |
| 生产备份 | SQLite 与媒体目录联合备份、恢复和完整性验证 |

## 15. 五个关键问题

### 15.1 如果暂时不购买硬件，当前还能完成多少软件开发？

可以继续完成大量工作。当前整体软件完成度约 **70%**；不购买硬件的最高可软件验证完成度约为 **85%-90%**。

重点方向：

1. 真实 AI Provider Adapter 与受控候选生成。
2. 语义检索、记忆压缩和知识提炼。
3. 多步 Planning 与 Proactive L3。
4. Active Perception 与 Task/Tool 执行链集成。
5. Multimodal Provider Adapter 和管理前端。
6. Privacy Erasure、媒体备份恢复、Retention 前端和性能压测。
7. 桌面机器人固件 Simulator / Contract Adapter。

剩余约 10%-15% 需要真实硬件、固件、外部环境和真实浏览器矩阵。

### 15.2 ARS-02 至 ARS-06 中，哪些阶段的软件部分实际上还没有完成？

ARS-02 主体软件最完整，但隐私删除端到端、目标规模性能、备份恢复和重复归属收敛仍未完成。

ARS-03 的语义检索、自动压缩、知识提炼、Memory Graph、多用户隔离和完整 History 前端没有完成。

ARS-04 的 AI Planner、多步计划、非设备计划、Proactive L3/L4、Active Perception 执行集成和对应前端没有完成。

ARS-05 的真实 Provider Adapter、生产云治理、完整 Multimodal 管理前端、后台唤醒词和大规模媒体治理没有完成。

ARS-06 的真实桌面机器人 Adapter、固件协议、真实能力证据和物理安全验证没有完成。

### 15.3 哪些功能只是有架构、有接口，但没有形成真实业务能力？

主要包括：

1. Agent Robot 写工具：已注册，但 Agent 风险门禁不允许选择。
2. Mobile Robot Profile：只有治理壳，不能执行。
3. Active Perception：默认没有 Observer。
4. `query_events`：意图映射存在，工具不存在。
5. Multimodal 六类 Provider：接口存在，实现仍是 Mock。
6. Reasoning AI 候选生成：只有架构预留。
7. Robot 写动作：Mock 安全链存在，真实物理能力不存在。
8. `SystemStatusPage`：页面存在但未路由。
9. State Estimates、Retention、大部分 History、Reasoning、Planning、Proactive、Perception：后端存在，前端未形成完整用户能力。

### 15.4 哪些功能可以完全通过现有 Windows 开发环境完成？

可以在 Windows 环境完成或至少完成代码、Mock 和自动化验证的功能包括：

1. Provider Log、Retention、Privacy Erasure 的软件治理增强。
2. SQLite 与媒体备份清单、一致性检查和恢复工具。
3. SQLite 目标规模压测。
4. Memory FTS/语义检索原型。
5. Memory 压缩、知识提炼和审计边界。
6. 多步 Planning 和 Proactive L3。
7. Reasoning AI Adapter，真实外部模型验证可另行执行。
8. Multimodal Provider Adapter、Mock Contract Test 和管理前端。
9. History、State Estimates、Retention、Reasoning、Planning、Proactive、Perception 前端。
10. 桌面机器人协议契约、Simulator 和安全回归。
11. 事件、任务、Automation、取消、恢复和失效安全仿真测试。

这些项如果依赖外部模型 API，仍需要凭据和网络才能做最终验收，但软件实现和契约测试可以在 Windows 完成。

### 15.5 如果要达到不依赖真实硬件的最高软件完成度，还需要开发哪些功能？

最高优先级软件工作：

1. AI Provider Adapter 与 Agent/Reasoning/Planning 的候选校验闭环。
2. Memory 语义检索、压缩、知识提炼和完整 History UI。
3. 多步 Plan、非设备 Plan、Plan Step 状态验证和失败恢复。
4. Proactive L3 任务生成；L4 继续默认禁止。
5. Active Perception 正式进入 Task System / Tool Executor。
6. Multimodal 真实 Provider Adapter 接口、Mock Contract Suite、云治理和管理 UI。
7. Privacy Erasure 全链路编排与备份边界。
8. 媒体目录备份、恢复一致性验证和孤立文件治理。
9. Retention、Reasoning、Planning、Proactive、Perception、Multimodal 管理界面。
10. 桌面机器人固件 Simulator、Contract Adapter、状态反馈验证和安全事件审计视图。
11. 性能压测、覆盖率、前端 bundle 和工程检查增强。

完成以上内容后，剩余不能软件闭环的部分就集中在真实 ESP32/ESPHome、真实机器人硬件/固件、真实摄像头/麦克风/扬声器、真实浏览器矩阵和生产环境验收。

## 16. 最终判断

Arvuno 已经不是一套只停留在文档或孤立接口的项目。基础设备链、事件链、任务链、环境记忆、Agent 工具、Automation、语音、多模态治理和机器人安全治理都已经进入真实代码路径，并有大量自动化测试支撑。

但当前完成度必须分层描述：

1. **软件骨架和治理链**：完成度较高。
2. **高级智能能力**：仍明显不足，尤其 ARS-04。
3. **真实模型能力**：AI 和 Multimodal Provider 仍以 Mock/抽象为主。
4. **真实硬件能力**：ARS-06 只有软件治理和 Mock 链路，没有真实机器人。
5. **生产数据治理**：Retention 已运行，但隐私删除、媒体备份和生产演练未闭环。
6. **用户可见能力**：大量后端 API 还没有前端入口。

因此，当前最准确的结论是：

> Arvuno 当前是一个基础闭环和软件安全治理较完整、高级智能和多模态能力仍以 Mock/框架为主、真实硬件执行严格封锁的系统。整体软件完成度约 70%；不依赖硬件可推进到约 85%-90%；ARS-02 至 ARS-06 均不能关闭。

本次审计不修改业务代码，不关闭任何阶段，不将 Mock 能力描述为真实硬件能力，也不建议因为本报告的百分比估计而跳过原有阶段验收。
