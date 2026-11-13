# 36. Arvuno Core 全项目审查报告（2026-11-10）

- 审查对象：当前工作区 `backend`、`frontend`、`docs`、`deploy`、`scripts`、`hardware` 与根配置
- 审查方式：静态代码审查 + 文档对照 + 全量自动化回归 + 隔离空库迁移 + 隔离进程启动冒烟 + 针对性缺陷探测
- 本次结论：**Phase 0–10 历史验收范围仍成立；ARS-02 至 ARS-06 均未关闭；当前适合本地 Mock / 受控开发，不建议直接开放真实设备或真实机器人**
- 本报告未修改业务代码；只记录审查结果和调整建议

## 1. 结论摘要

### 1.1 已完成的部分

Arvuno Core 的第一阶段闭环已经真实存在，不是空壳：

1. 后端可启动、可迁移、可备份恢复，API 有统一认证和错误结构。
2. 设备层有统一 Device Adapter、Mock Adapter、Home Assistant Adapter、Device Registry 和轮询。
3. 环境层有 Environment Context、Observation Pipeline、State Estimation、Context v2、History。
4. 执行层有 Tool Registry、Safety Policy、一次性确认、Tool Executor、执行审计和状态验证。
5. 任务层有 Task/TaskStep 状态机、取消、确认、超时、历史、事件和 correlation ID。
6. Agent 层有 Provider 抽象、结构化输出校验、候选计划、Tool Catalog 投影和 Task System 集成。
7. 自动化、通知、Memory、Reasoning、Planning、Proactive、Active Perception、Multimodal、Voice、Robot（Mock）都有实际代码和回归测试。
8. Web Console 有系统概览、设备、空间、环境、事件、记忆、对话、任务、自动化、通知和设置页面。
9. 当前后端全量回归 **399 passed**；前端 typecheck、Prettier、Vite build 均通过；隔离空库可迁移到 head。

### 1.2 未完成或不能宣告完成的部分

1. **ARS-02**：D2–D8 仍未关闭，包括隐私删除端到端、目标规模压测、备份恢复演练、真实 ESPHome / ESP32、真实 AI Provider。
2. **ARS-03**：语义检索、自动压缩、长期知识提炼、记忆图谱、多用户隔离、真实工具执行产生程序验证未完成。
3. **ARS-04**：AI Planner / 评估器、多步与非设备计划、Level 3 / 4、Active Perception 与 Task System 的受控执行集成、真实 Observer / 授权界面未完成。
4. **ARS-05**：真实摄像头、麦克风、视觉 / STT / TTS 模型、生产云端 Provider、真实浏览器语音、后台唤醒词和自动保留清理未完成。
5. **ARS-06**：真实机器人 ARS-06.2 未执行；机器人执行链路没有接入 Tool Registry / Safety Policy / Tool Executor；能力 consent、一次性确认、心跳、重连、状态 freshness、Web Console 机器人页和 Agent 只读工具未完成；第 34 号桌面机器人设计与当前 Mock `navigate_to` / 移动观察实现冲突。
6. **ARS-07 / ARS-08**：按路线图暂停，不进入当前计划。

### 1.3 最重要的五个阻塞项

1. **机器人执行绕过了统一安全执行链路**：API 和移动观察服务直接调用 `RobotApplicationService`，没有经过 Tool Executor、Safety Policy 和统一工具审计。
2. **机器人授权模型不完整**：能力声明的 `requires_consents` 没有被强制检查；通用任务 API 允许 `confirmed=true` 直接执行；没有一次性确认令牌；高风险能力没有统一拒绝。
3. **数据保留策略没有真正运行**：事件、Observation、多模态媒体、Proactive 建议、Environment Snapshot、Provider Log 都没有自动清理调度器；配置中的保留天数基本没有运行时效果。
4. **设备不可用事件会重复产生**：Adapter 连续抛异常时，每次轮询都会再次发布 `device_unavailable`，会放大自动化、通知和 Proactive 评估。
5. **Provider Log 实际保存了完整对话输入**：与文档“对话内容不在后端持久化”矛盾，且没有保留期限；这是隐私与数据最小化问题。

## 2. 验证基线

| 检查 | 结果 | 说明 |
| --- | --- | --- |
| 后端全量回归 | **399 passed**，1 个既有 Starlette / httpx TestClient deprecation warning | `backend/tests` 48 个测试文件 |
| 后端 Ruff lint | `ruff check .` 通过 | 全 backend 范围 |
| 后端 Ruff format | `ruff format --check arvuno_core` 通过；`ruff format --check .` **失败** | 仅 `tests/test_robot_mobile_perception.py` 有 3 处格式漂移 |
| Alembic head | `b8c3d4e5f6a7` | 单 head |
| 开发库当前版本 | `a7d4f83c1092` | 落后于 head；下次启动应用会自动升级并先备份 |
| 隔离空库升级 | 通过 | 67 张表（66 张领域表 + `alembic_version`），5 张 robot 表存在 |
| Python 依赖一致性 | `pip check` 通过 | 无破损依赖 |
| 前端 typecheck | 通过 | `tsc --noEmit` |
| 前端格式 | 通过 | Prettier check |
| 前端 build | 通过 | Vite 3077 modules；JS bundle 约 1.24 MB，保留大于 500 kB warning |
| 隔离进程启动 | 通过 | `python -m arvuno_core.main` 在临时数据库启动；`/health`、`/api/system/status` 正常；无 Token 的 `/api/devices` 返回 401 |
| 前端自动化测试 | **未执行** | 项目无前端测试框架 |
| 覆盖率 | **未执行** | 无 coverage 配置或门槛 |
| 真实 HA / DeepSeek | **本轮未复验** | 依赖历史 `docs/16`；不得把历史结果当作本轮新证据 |

审查还确认了一个测试隔离问题：部分测试直接调用 `create_app()`，会读取根目录 `.env`。把 `ARVUNO_ENVIRONMENT` 临时改为 `test` 后，`tests/test_health.py` 立即失败，因为它硬编码断言 `development`。测试套件不是完全 hermetic 的。

## 3. 已完成 / 已实现的能力

### 3.1 Phase 0–10 基础闭环

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| FastAPI 启动、健康检查、OpenAPI | 已实现 | `main.py`、`api/health.py`、`tests/test_health.py`、`tests/test_openapi.py` |
| SQLite、Alembic、WAL、备份恢复 | 已实现 | `persistence/database.py`、`persistence/backup.py`、`test_database_schema.py`、`test_backup_restore.py` |
| 配置校验与生产安全护栏 | 已实现 | `config.py`：生产必须有 API Token，生产禁止 HA 写开关 |
| API 认证与错误契约 | 已实现 | Bearer Token、统一 `ErrorResponse`、400/401/404/502/504 等错误 |
| Device Adapter / Registry / HA / Mock | 已实现 | `devices/`、`test_home_assistant_adapter.py`、`test_mock_device_adapter.py` |
| 事件总线、持久化、查询、保留配置 | 已实现（但清理未调度） | `events/`、`test_event_system.py`、`test_events_api.py` |
| Environment Context / Observation / State Estimation / History | 已实现 | `environment/`、`observations/`、`estimation/`、`history/` 及对应测试 |
| Tool Registry / Safety Policy / 确认 / Executor | 已实现 | `tools/`、`test_tool_system.py`、`test_tool_integration.py` |
| Task / TaskStep / 取消 / 确认 / 超时 | 已实现（确认超时无后台调度） | `tasks/`、`test_task_system.py` |
| AI Provider / Agent Runtime | 已实现 | `ai/`、`agent_runtime/`、`test_ai_provider.py`、`test_agent_runtime.py` |
| 自动化与通知 | 已实现 | `automation/`、`test_automation_system.py` |
| Memory / Reasoning / Planning / Proactive / Active Perception | 已实现基础版 | `memory/`、`reasoning/`、`planning/`、`proactive/`、`perception/` |
| Multimodal / Voice（Mock） | 已实现按需链路 | `multimodal/`、`voice/`、`test_multimodal_*`、`test_voice_interaction.py` |
| Robot（Mock） | 已实现 | `robots/`、`test_robot_adapter.py`、`test_robot_mobile_perception.py`、`test_ars06_acceptance.py` |
| Web Console | 已实现核心页面 | `frontend/src/pages`；14 个已路由页面 |

### 3.2 已经实现但不等于验收关闭的 ARS 子阶段

- **ARS-02.1–02.7**：空间、Observation、Pipeline、State Estimation、Context v2、空间查询和最终验收已实现；未关闭项见第 4 节。
- **ARS-03.1–03.2**：Memory 分类、生命周期、偏好、检索、History、时间理解和 Agent 只读工具入口已实现；语义检索和长期治理未完成。
- **ARS-04.1–04.4**：Reasoning、Planning、Proactive、Active Perception 的确定性基础已实现；AI Planner / 评估器、多步计划、Level 3 / 4 未完成。
- **ARS-05.1–05.3**：按需图像 / OCR / 音频、Mock 视觉 / STT / TTS、授权、删除、Fusion、语音 API 和前端状态机已实现；真实模型和真实硬件未完成。
- **ARS-06.1、06.3**：Mock Robot Adapter、能力模型、状态、任务请求、REST API、移动观察 Mock 闭环已实现；06.2 真实机器人和 06.4 真正关闭未完成。

## 4. 未完成 / 未关闭及阻碍

| 阶段 | 当前状态 | 未完成内容 | 阻碍在哪里 |
| --- | --- | --- | --- |
| ARS-02 | 未完全通过 / 不关闭 | 隐私删除端到端审计、20/50/200 传感器规模压测、备份恢复演练、真实 ESPHome / ESP32、真实 AI Provider | 缺真实硬件、缺目标规模数据、隐私删除没有覆盖媒体 / 日志 / 备份边界、没有真实模型会话 |
| ARS-03 | 部分通过 / 不关闭 | 语义检索、自动压缩、长期知识提炼、记忆图谱、多用户隔离、真实工具执行程序验证 | 当前只有关系过滤 + `LIKE`；没有 embedding / 向量库；没有多用户边界；程序验证靠显式写入 |
| ARS-04 | 部分通过 / 不关闭 | AI Planner / 评估器、多步与非设备计划、Level 3 / 4、Active Perception 与 Task System / Tool Executor 集成、真实 Observer、授权界面 | 当前是确定性单设备规划；Observer 默认 `None`；移动观察直接调用 Robot Service；无前端管理页 |
| ARS-05 | Mock 条件通过 / 不关闭 | 真实摄像头 / 麦克风、真实视觉 / OCR / STT / TTS / Audio Event、生产云端 Provider、真实浏览器语音、后台唤醒词、自动保留清理 | 全是 Mock Provider；无真实硬件；无自动清理调度器；真实浏览器 / 麦克风端到端未验收 |
| ARS-06 | Mock 条件通过 / 不关闭 | 真实机器人（06.2）、统一安全执行链路、能力 consent / 撤销、一次性确认、心跳 / 重连 / freshness、返回坞 / 禁入区、Web Console 机器人页、Agent 只读工具 | 无真实硬件、BOM、固件契约、台架测试和安全审批；机器人 API 直接执行；第 34 号桌面设计与当前移动 Mock 实现冲突 |
| ARS-07 | 暂停 | 工业 Adapter、协议、规则 | 按路线图不进入当前计划 |
| ARS-08 | 暂缓 | 分布式世界智能 | 远期方向 |

**总体判断**：Phase 0–10 的历史验收结果可以保留；但长期路线没有任何一个 ARS 阶段可以标记关闭。当前是“基础能力已实现、真实环境和高级智能未验收”的状态。

## 5. 高优先级设计 / 实现问题

### P0-1 机器人执行绕过 Tool Registry / Safety Policy / Tool Executor

**现象**

- `api/robots.py` 直接调用 `RobotApplicationService`。
- `perception/robot_mobile.py` 也直接调用 `RobotApplicationService.create_task_request`。
- `tools/registry.py` 没有任何 robot 工具；Robot 任务没有 `tool_execution_id`，没有进入统一执行审计。
- 机器人任务只经过自身的 `RobotTaskStatus` 状态机和 API Token，不经过 Safety Policy 的风险上限判断。

**影响**

这违反项目的基本安全约束：“所有设备操作必须通过 Tool Registry、Safety Policy 和 Tool Executor”。机器人是比灯更危险的执行器，却走了比普通设备更弱的执行路径。ARS-06 报告中的“Mock 条件通过”不能解释为安全链路通过。

**建议**

1. 为机器人增加受控工具（至少 `robot_status` 只读、`robot_navigate`、`robot_observe`、`robot_cancel`），全部通过 Task System / Tool Executor / Safety Policy。
2. 机器人高风险能力默认拒绝，运动能力要求确认令牌和空间授权。
3. 统一 Robot Task 与 ToolExecutionRecord 的关联，保留 robot request ID 和 tool execution ID。
4. 如果坚持独立 Robot 安全域，必须先由用户明确签署边界，并在 AGENTS / 设计中写清楚；不能默默绕过。

### P0-2 机器人授权、consent 和确认模型不完整

**现象**

- `RobotCapability.requires_consents` 只有声明，没有执行检查。审查中把 `observe` 能力启用后，未提供任何摄像头 consent 也能创建并成功执行任务。
- 通用 `POST /api/robots/{robot_id}/task-requests` 允许客户端提交 `confirmed=true`，直接跳过两步确认。
- 机器人确认接口只依赖 Bearer Token，没有一次性 token。
- 没有机器人 consent 表、撤销接口、授权有效期。
- 能力没有运行时启用 API；`sync_robot` 会用 Adapter 返回的能力覆盖数据库，真实能力启用缺少操作面。

**影响**

摄像头、麦克风、运动和观察授权无法被可靠地强制；模型或前端如果误提交 `confirmed=true`，会直接越过用户确认。真实硬件阶段不可接受。

**建议**

1. 增加 Robot Consent 模型和 API（grant / revoke / list），绑定机器人、能力、空间、数据类别、有效期和任务。
2. 执行前强制检查 `requires_consents` 和 `requires_confirmation`。
3. 确认使用一次性 token，并绑定 robot ID、request ID、参数摘要和过期时间。
4. 禁止外部请求直接携带 `confirmed=true`；内部服务调用使用独立受信接口。
5. 增加能力启用 / 禁用 / 证据审批 API，避免只有代码内 `set_capability` 才能启用。

### P0-3 数据保留策略没有真正执行

**现象**

- `EventRetentionService` 只定义、只被测试使用，应用没有实例化或调度。
- `ObservationPipeline.cleanup_expired`、`MultimodalService.purge_expired`、`ProactiveService.cleanup_expired` 没有后台调度器。
- 只有 Memory 有 `POST /api/memories/cleanup`；Observation、Event、Proactive、Multimodal 没有对应的常规清理入口。
- `provider_logs`、`environment_snapshots` 没有清理策略。
- 多模态媒体文件保存在 `data/media/multimodal`，但 `SqliteBackupService` 只备份 SQLite 文件，不备份媒体文件。

**影响**

事件、观测、媒体、Provider 日志和快照会持续增长；配置中的 `ARVUNO_EVENT_RETENTION_DAYS` 等参数没有实际效果。隐私删除和备份恢复都不能覆盖完整数据生命周期。ARS-02 / ARS-05 的保留与删除缺口因此不能关闭。

**建议**

1. 增加一个轻量后台 Scheduler，在应用 lifespan 中启动，统一执行 Event、Observation、Multimodal、Proactive、Environment Snapshot 和 Provider Log 的保留清理。
2. 为每个清理任务记录执行结果和失败原因；提供手动触发 API 用于运维。
3. 备份增加媒体目录清单或媒体归档；恢复时校验数据库引用和媒体文件的一致性。
4. 明确“数据库元数据恢复”和“媒体完整恢复”的区别，不能把只恢复 SQLite 说成完整恢复。

### P0-4 Adapter 连续异常会重复发布 `device_unavailable`

**现象**

`EnvironmentReconciler.reconcile` 在 Adapter 抛出 `AdapterUnavailableError` 时发布 `device_unavailable` 事件，但没有把不可用状态写入 Device Registry 或 Observation Pipeline。下一次轮询仍看到旧的“在线”状态，于是再次发布同样的不可用事件。

**复现**

在隔离环境中让同一设备的 `get_state` 连续抛 `AdapterUnavailableError`，连续两次 `poll_once` 后，事件表出现两条相同设备的 `device_unavailable`。现有测试只覆盖“一次异常”或“Adapter 返回 unavailable 状态”，没有覆盖“连续异常”。

**影响**

- 事件表膨胀。
- 自动化规则重复触发。
- Proactive 重复评估，可能生成重复建议。
- Environment Snapshot 按事件重复保存。
- 通知和后续任务被重复创建。

**建议**

1. 在异常路径也写入不可用投影（或至少写入一个“已发布不可用”的去重标记）。
2. 以 `(device_id, current_state, observed_at)` 或状态机方式去重。
3. 增加连续异常、恢复、再次异常、事件迟到的回归测试。
4. 不要把“发布事件”当作“更新状态”。

### P0-5 Provider Log 保存了完整对话输入

**现象**

`ai/logging_support.py` 的 `provider_log_input` 保存了完整的 `messages` 内容（包括 system prompt 和用户消息）以及 response schema key。它只做密钥模式脱敏，不做个人信息最小化。`provider_logs` 没有清理策略。

**影响**

- 与 `docs/06-api-design.md` 中“对话内容不在后端持久化”的声明矛盾。
- 用户自然语言、环境信息和系统提示会被长期保存在 SQLite 中。
- 没有 retention、删除接口或用户可见的保留说明。
- 在共享机器、备份或日志导出场景中扩大隐私暴露面。

**建议**

1. 默认只保存请求类型、消息角色数量、内容哈希、token 数量、schema 版本和一个短摘要，不保存全文。
2. 如果确实需要调试全文，增加显式开关、短期保留和删除接口。
3. 更新文档，明确“Provider Log 不是无状态”的事实；或者实现真正的无状态 / 脱敏日志。

### P0-6 真实机器人不可用，且载体设计与实现冲突

**现象**

- 没有真实机器人硬件、BOM、机械 / 电气设计、固件契约、台架记录、急停实测和安全审批。
- 第 34 号文档选定自制桌面机器人，并明确第一版不注册 `navigate_to`、`return_to_dock`、`charge`、`inspect`。
- 当前 `MockRobotAdapter` 注册了上述能力，移动观察实际执行 `navigate_to + observe`。

**影响**

ARS-06 无法关闭。当前 Mock 结果只能证明“移动机器人 Mock 链路可用”，不能证明“桌面机器人设计通过”。如果后续直接按当前代码开放真实硬件，会同时违反载体设计和安全边界。

**建议**

1. 先由用户确认唯一权威载体：桌面机器人还是移动机器人。
2. 如果是桌面机器人：移除 / 禁用移动能力，补齐 `look_at`、`observe_scene`、`request_safe_stop`、`enter_idle_pose`。
3. 如果是移动机器人：重写第 34 号设计基线，并补齐空间授权、禁入区、定位和返坞。
4. 在载体确认前，不开放任何真实运动能力。

## 6. 中优先级设计 / 实现问题

### P1-1 `/health` 使用全局 Settings，而不是当前 app 的 Settings

`api/health.py` 依赖 `get_settings()`（`lru_cache` 全局），而不是 `app.state.settings`。用自定义 `Settings(environment="test")` 创建 app 时，`/health` 仍可能返回开发环境配置；测试中设置 `ARVUNO_ENVIRONMENT=test` 会让 `test_health.py` 失败。

**建议**：健康检查改用 `request.app.state.settings`；测试显式注入配置并断言注入值，而不是硬编码 `development`。

### P1-2 等待确认的任务没有自动过期和恢复

- `TaskService` 有 `_remaining_seconds` 和 `resume_task`，但 `resume_task` 没有 API 入口。
- 等待确认的任务不会被后台定时取消；只有用户调用 confirm 时才检查超时。
- 应用重启后，运行中的任务不会恢复；等待确认的 token 只保存在进程内确认服务中，重启后不可用。

**建议**：增加启动恢复流程和等待确认超时调度；为 `resume_task` 提供受控 API；明确重启后的任务终态。

### P1-3 EventBus 同步等待 Automation / Task，可能阻塞设备轮询

`EventBus._dispatch` 顺序 `await` 所有订阅者；`AutomationService.handle_event` 在事件处理内部直接 `TaskService.create_and_run`。一个慢工具、慢数据库写入或等待确认的自动化会阻塞整个事件发布路径，进而阻塞设备轮询和其它订阅者。

**建议**：为订阅者增加超时；把自动化任务执行放入受控后台队列；事件总线只负责持久化和轻量分发；增加慢订阅者测试。

### P1-4 API 层仍包含直接持久化和业务逻辑

`api/settings.py`、`api/system.py`、`api/devices.py`、`api/environment.py` 直接使用 Unit of Work / Repository，并在路由中做分页、统计和组合。项目文档要求“API 路由只做协议转换、参数校验和响应封装”。

**建议**：抽出 SystemSettingsService、SystemStatusService、DeviceQueryService 等应用服务；API 只调用服务。不是立即阻塞，但会阻碍后续测试和重构。

### P1-5 项目级格式检查实际失败

README 写的是 `ruff format --check backend`，但当前 `tests/test_robot_mobile_perception.py` 有 3 处格式漂移，导致该命令失败。虽然 `arvuno_core` 本身格式通过，但“项目级健康检查”并不全绿。

**建议**：格式化该测试文件，并把 CI 的 lint / format / test 一起固定下来。

### P1-6 测试不 hermetic，且缺少 CI / 前端测试 / 覆盖率

- 7 处测试直接 `create_app()`，会读取根 `.env`。
- 无 `.github/workflows`、无 CI 配置。
- 无前端测试框架、无前端测试脚本。
- 无 coverage 门槛。
- `test_health.py` 硬编码 `development`，环境变量变化即失败。

**建议**：所有测试显式注入 `Settings(_env_file=None, ...)`；建立 GitHub Actions 或本地 `scripts/check.ps1`；至少增加关键前端纯函数 / API 校验测试；设定 coverage 目标但不要只看数字。

### P1-7 后端依赖没有锁文件 / 哈希

`requirements.txt` 使用范围约束，没有 lockfile 或 hash。当前环境能通过，但不能保证另一台机器安装出相同版本；FastAPI 0.162、Starlette 1.10 与项目文档时代可能存在行为差异。

**建议**：生成带哈希的 lockfile（pip-tools / uv / pip freeze），固定测试和运行环境。

### P1-8 SQLite 专有部分索引影响 PostgreSQL 迁移

`DeviceState`、`EstimationTarget` 等使用 `sqlite_where` 部分索引。当前只支持 SQLite 没问题，但文档把 PostgreSQL 作为未来方向；迁移时需要改写这些索引。

**建议**：把 SQLite 特有优化集中到方言适配层，或在迁移文档中明确“迁 PostgreSQL 时必须重写部分索引”。

### P1-9 Home Assistant demo 暴露到所有网卡且镜像未固定

`deploy/home-assistant-demo/compose.yaml` 使用 `"8123:8123"`，默认绑定 `0.0.0.0`，并拉取 `homeassistant/home-assistant:stable` 未固定版本。对本地个人系统，这会把 demo 暴露到局域网，并带来不可重复的升级。

**建议**：改为 `127.0.0.1:8123:8123`，固定镜像标签或 digest，并在文档中说明 demo 仅本机使用。

### P1-10 凭据与浏览器端令牌管理

- 根目录 `.env` 包含真实 AI / HA 凭据；`.gitignore` 覆盖 `.env`，但不能防止会话记录、备份或截图泄露。
- 本轮审查曾读取 `.env`；如果该会话记录会被共享或导出，建议轮换 AI API Key 和 HA Token。
- 前端把 API Token 存在 `localStorage`；任何 XSS 都能读取。
- `/openapi.json` 和 `/docs` 不需要认证；与“所有非健康接口需 Token”的安全文档不完全一致。

**建议**：不要在审查 / 日志中读取 `.env`；使用本地密钥管理或短期令牌；考虑把 Token 放到 `sessionStorage` 或后端会话；生产环境关闭或保护 OpenAPI 文档；明确凭据轮换流程。

## 7. ARI / ARS 功能层面的其它问题

### P2-1 机器人状态与任务边界

- `RobotApplicationService.state()` 每次请求才从 Adapter 读状态，没有心跳、状态过期和 freshness。
- `cancel_task_request` 在 Adapter 返回 `success=False` 时仍把任务标记为 `CANCELLED`。
- 超时只把任务标记为 `TIMEOUT`，没有重新读取机器人状态或请求安全停止；真实运动可能仍在继续。
- 机器人事件没有发布到主 EventBus，Automation / Proactive 无法对机器人安全事件做出反应。
- 没有 `request_safe_stop` API。
- 没有能力启用 / 禁用 API；`sync_robot` 会用 Adapter 返回值覆盖数据库中的能力状态。
- 没有机器人 Web Console 页面和 Agent 只读工具。

**建议**：把机器人安全状态、任务和事件纳入统一运行模型；增加心跳、freshness、安全停止、恢复确认和事件总线桥接。

### P2-2 主动观察的语义仍是占位实现

`RobotMobilePerceptionService._observation_input` 对 `scene_label` / `object_presence` 返回空标签、0 置信度和 `analysis=not_performed`，只保存媒体句柄。它可以证明“Observation 链路通”，不能证明“主动观察结果有意义”。

**建议**：接入真实视觉 Provider 或明确标记为 Mock 媒体占位；没有分析能力时不要生成看似环境事实的 Observation。

### P2-3 Task / Automation 的边界细节

- 自动化工具动作如果在 Task 中进入等待确认，Automation Run 会立即记 `FAILED`，用户之后确认 Task 也不会更新 Automation Run。
- Agent / Automation / Task 的大量执行是在 HTTP 请求内同步等待，长任务会占用请求。
- 没有任务队列、后台恢复、等待确认超时调度器。

**建议**：明确“自动化任务”和“用户确认任务”的状态映射；增加后台任务执行和恢复；对长任务返回 202 + 查询。

### P2-4 其它低优先级问题

- `DeviceApplicationService.get_state()` 把读取状态标记为 `verified=True`，语义上容易误导。
- `EnvironmentReconciler` 对 Adapter 异常没有状态投影；与 P0-4 同源。
- `DevicePollingRuntime` 的外部 ID 列表在启动时冻结，新增设备需要重启；没有手动 resync API。
- Home Assistant Adapter 没有重试；`get_devices` 逐个实体串行请求，大 allowlist 会慢。
- `conversations` / `conversation_messages` 表存在但没有任何 API 使用；是死 schema。
- `SystemStatusPage.tsx` 未被 `App.tsx` 路由，是死页面；`health.ts` 也随之只服务死页面。
- `voice.ts` 在 `processVoice` 中先 `response.json()`，失败时又调用 `errorFromResponse(response)` 再次读 body，结构化错误会丢失。
- `useVoiceInteraction.startListening` 读取闭包中的旧 `recorder.recording`，成功开始录音后可能把 stage 设回 `idle`；界面状态与实际录音不一致。
- `play()` 创建 object URL 后没有 `revokeObjectURL`，重复播报会泄漏内存。
- 前端没有 fetch 超时；后端长任务时页面可能一直 loading。
- 前端 bundle 约 1.24 MB，没有代码分割；首屏性能和移动端体验有优化空间。
- 前端缺少机器人、Planning、Proactive、Reasoning、Active Perception 页面；大量 ARS-04 / ARS-06 API 只能手工调用。
- 没有请求速率限制；本地单用户风险低，但不适合暴露到局域网。
- 日志文件没有轮转；长期运行会无限增长。

## 8. 文档与实现不一致清单

这些不是“文档写得不够多”，而是会误导后续开发者或让安全边界失效的实质性冲突：

| 文档 / 约定 | 文档说法 | 当前实现 | 建议 |
| --- | --- | --- | --- |
| `AGENTS.md` “当前阶段约束” | 不实现 Memory、会话持久化、Agent 自主规划、机器人和语音视觉 | Memory、Reasoning、Planning、Proactive、Multimodal、Voice、Robot 都已存在 | 更新为当前 Phase 10 + ARS 状态，或明确标注该段是历史 Phase 10 约束 |
| `README.md` 第 5 行 | “尚未实现 Memory、会话持久化、Agent 自主规划…” | Memory / 历史 / Agent 工具已实现 | 重写 README 当前状态和文档索引 |
| `docs/00` 第 13、128 行 | 不包含 Memory；机器人只在未来扩展 | 已包含 Memory 和 robots | 更新项目概览 |
| `docs/02`、`docs/03` | 模块清单不含机器人、语音、视觉；提到 WebSocket | 已有 robots / voice / multimodal；没有 WebSocket | 更新模块清单和传输方式说明 |
| `docs/05` 数据模型 | 主要描述 Phase 2 表；声称 UTC ISO 字符串 | 66 张表；实际使用 `DateTime`；缺少 Observation / Reasoning / Planning / Multimodal / Robot 等表 | 全量更新数据模型，或标注为 Phase 2 历史版本 |
| `docs/06` API 设计 | “对话内容不在后端持久化” | `provider_logs.input_summary` 保存完整 messages | 二选一：改实现或改文档，并增加保留策略 |
| `docs/12` 测试策略 | 提到 WebSocket、`pytest -m security/acceptance`、覆盖率 | 无 WebSocket、无 marker、无 coverage | 更新测试策略或补齐执行配置 |
| `docs/19` 手册状态 | ARS-02 / 05 仍为设计待确认，ARS-06 待开发 | 这些阶段已有大量实现和验收报告 | 更新状态表，避免后续 Agent 按旧状态工作 |
| `docs/34` 桌面机器人设计 | 不注册 `navigate_to`、`return_to_dock`、`charge`、`inspect` | Mock 全部注册，移动观察使用 `navigate_to` | 先确认载体，再统一设计和实现 |
| `docs/03` API Layer | API 只做协议转换，不直接读写数据库 | `api/settings.py`、`api/system.py`、`api/devices.py`、`api/environment.py` 直接使用 UoW / Repository | 抽服务层，或修改架构文档承认例外 |

## 9. 调整建议（按优先级）

### P0：在开放真实硬件 / 进入下一阶段前必须完成

1. **统一机器人安全执行链路**：Robot Tool Handler → Task System → Tool Executor → Safety Policy；禁止 API 直接调用 RobotApplicationService 执行运动。
2. **补齐机器人授权**：Robot Consent 表、撤销、能力级 `requires_consents` 强制、一次性确认 token、高风险能力默认拒绝。
3. **补齐机器人失效安全**：心跳、重连、状态 freshness、超时后重新读取状态并请求安全停止、取消失败的真实结果、`request_safe_stop`。
4. **实现保留调度器**：Event / Observation / Multimodal / Proactive / Provider Log / Environment Snapshot 的自动清理和审计。
5. **修复重复不可用事件**：异常路径写入不可用投影或去重标记，并补连续异常测试。
6. **关闭 Provider Log 隐私缺口**：默认只保存脱敏摘要，增加 retention / delete。
7. **确认载体**：桌面机器人还是移动机器人；在确认前不开放真实运动。

### P1：下一轮稳定性 / 可用性工作

1. 增加后台任务调度：等待确认超时、运行中任务恢复、Retention、Proactive cleanup、Multimodal purge。
2. 为 EventBus 订阅者增加超时，自动化任务移出同步事件路径。
3. 修复 `/health` 的 Settings 注入和测试 hermeticity。
4. 建立 CI：Ruff check / format / backend pytest / frontend typecheck / format / build，并增加前端测试。
5. 固定后端依赖 lockfile 和前端 lockfile 的使用方式。
6. 备份覆盖媒体目录，日志增加 rotation，明确数据库与媒体的恢复一致性。
7. Home Assistant demo 改绑 `127.0.0.1` 并固定镜像版本。
8. 补齐 Web Console 的机器人、Planning、Proactive、Reasoning、Active Perception 页面，或明确这些功能暂不提供 UI。
9. 修复前端 voice 错误解析、录音 stage、object URL 泄漏和 fetch 超时。

### P2：代码与文档清理

1. 抽出 API 层中的业务逻辑（settings / system / devices / environment）。
2. 更新 `README`、`docs/00`、`docs/02`、`docs/03`、`docs/05`、`docs/12`、`docs/19` 和 `AGENTS.md` 的当前状态。
3. 删除或标注未使用的 `conversations` / `conversation_messages` 表和 `SystemStatusPage`。
4. 统一机器人 API 的响应包装和分页风格。
5. 为 SQLite 部分索引补 PostgreSQL 迁移说明。
6. 增加请求速率限制、请求体大小限制和更严格的 Token 强度检查。
7. 评估前端 bundle 拆分和移动端性能。

## 10. 最终判定

### 已完成

- Phase 0–10 的工程基础和第一阶段闭环已完成历史验收。
- 设备、事件、环境、Observation、State Estimation、Tool、Task、Agent、自动化、Memory、Reasoning、Planning、Proactive、Active Perception、Multimodal、Voice、Mock Robot 都有实际实现和回归测试。
- 当前 399 项后端测试、前端 typecheck / format / build、隔离空库迁移和隔离进程启动均通过。

### 未完成

- ARS-02 至 ARS-06 全部未关闭；ARS-07 / ARS-08 暂停。
- 真实设备、真实机器人、真实摄像头 / 麦克风、真实模型、真实云端 Provider、目标规模性能和完整隐私删除均未验收。
- 机器人安全执行链路、consent、一次性确认、心跳 / 重连 / freshness、Web Console 和 Agent 工具未完成。
- 数据保留调度、媒体备份、Provider Log 最小化和前端测试 / CI 未完成。

### 阻碍

- 真实硬件 / 真实模型缺失。
- 机器人安全边界尚未接入统一执行链。
- 载体设计冲突未解决。
- 隐私和保留策略没有运行时执行。
- 测试与文档仍以旧的 Phase 10 基线为主，项目当前状态没有被一致地表达。

### 结论

Arvuno Core 当前是一个**可运行、可回归、功能面很宽的本地 Mock / 受控开发系统**，不是已经完成全部长期路线的产品。Phase 0–10 的成果应保留；ARS-02 至 ARS-06 必须继续标记为未关闭。

在机器人安全执行链路、保留策略、真实硬件验收和载体确认完成之前，不应开放真实运动控制、真实摄像头 / 麦克风采集或生产环境写入。
