# 35. ARS-06 Embodied Intelligence Acceptance Report

- 日期：2026-11-10
- 验收基线：当前工作区实现，包含 ARS-06.1 Mock Robot Adapter、ARS-06.3 移动主动观察 Mock 链路和本轮 ARS-06.4 验收修复
- 验收范围：独立 Robot Adapter、Robot Capability 注册、定位和状态同步、导航任务、主动观察、感知数据来源、用户授权、急停、人工接管、离线恢复，以及机器人离线时 Arvuno Core 的独立运行
- 最终结论：**Mock 条件通过 / ARS-06 不关闭**

## 1. Executive Summary

ARS-06 当前已经具备一条可运行的 Mock 机器人链路：Robot Adapter 与普通设备 Adapter 分离，Capability 有独立 Schema、验证状态、运行时开关、风险和确认声明；机器人投影、状态快照、事件、任务请求和移动观察记录都进入持久化；导航任务支持确认、幂等、取消、拒绝、超时、定位丢失、低电、离线、急停和人工接管等失败归一化；移动主动观察复用 Active Perception、Observation、State Estimation 和 Reasoning，而不是让机器人直接写世界模型。

本轮验收发现并修复了四个缺陷：

1. 任务请求的 `timeout_seconds` 没有真正限制 Adapter 调用，慢 Adapter 可以无限占用执行路径。
2. 相同幂等键携带不同任务语义时会静默返回旧任务，而不是报告冲突。
3. 移动观察结果把 `mock_only` 硬编码为 true，非 Mock Adapter 也会被错误标记。
4. 机器人重新上线时只更新投影，没有生成连接恢复事件，离线恢复缺少可追溯审计。

修复后 ARS-06 专项 47 项测试通过，后端全量回归 399 项通过。

本轮不能宣告 ARS-06 完成。真实机器人接入 ARS-06.2 没有执行；没有真实硬件、固件、导航、摄像头、麦克风、急停和人工接管验收。Web Console 机器人状态页和 Agent 只读机器人工具仍未实现。通用机器人能力 API 没有强制 `requires_consents`，没有授权表、撤销和一次性确认令牌。自动心跳、重连轮询和状态 freshness 也没有实现。当前主动观察只返回受控媒体句柄，视觉分析固定为 `not_performed`，不能视为真实环境理解。

本轮还发现一个阻塞关闭的设计冲突：第 34 号文档选定**自制桌面机器人**并明确第一版不注册 `navigate_to`、`return_to_dock`、`charge`、`inspect`，但当前 `MockRobotAdapter` 注册了这些能力，ARS-06.3 移动观察链路也实际使用 `navigate_to`。代码形态更接近第 33 号商用移动机器人设计。ARS-06 关闭前必须由用户确认唯一权威载体和能力清单，不能同时用桌面机器人设计验收移动导航。

## 2. Validation Environment

验证使用隔离临时 SQLite 数据库和自动化测试环境；没有修改当前开发数据库、运行中的环境或真实设备。

| 检查 | 结果 |
| --- | --- |
| ARS-06 专项回归 | 47 passed（`test_robot_adapter.py` 16、`test_robot_mobile_perception.py` 13、`test_ars06_acceptance.py` 18） |
| Backend full regression | 399 passed，1 个既有 FastAPI / Starlette TestClient deprecation warning |
| Backend lint | `ruff check arvuno_core tests/test_ars06_acceptance.py` 通过 |
| Backend format | `ruff format --check arvuno_core` 通过，185 files already formatted |
| Alembic heads | 单 head：`b8c3d4e5f6a7` |
| Alembic current | 本地开发库保持 `a7d4f83c1092`，本轮未迁移开发库 |
| Alembic empty upgrade | 隔离空库升级到 `b8c3d4e5f6a7` 通过，临时库已删除 |
| 机器人表 | 空库升级后存在 `robots`、`robot_capabilities`、`robot_state_snapshots`、`robot_task_requests`、`robot_events` |
| Frontend typecheck | `tsc --noEmit` 通过 |
| Frontend format | Prettier check 通过 |
| Frontend build | Vite build 通过；保留既有 JS bundle 大于 500 kB warning |

重点测试文件：

- `backend/tests/test_robot_adapter.py`
- `backend/tests/test_robot_mobile_perception.py`
- `backend/tests/test_ars06_acceptance.py`
- `backend/tests/test_architecture_boundaries.py`

## 3. Defects Found During Acceptance

### 3.1 机器人任务超时未强制执行

验收前，`RobotTaskRequestCreate.timeout_seconds` 只被持久化，`RobotApplicationService` 直接等待 `adapter.execute_task()`。Adapter 挂起时 API 会一直等待，违反“命令有超时、运动命令不得盲目重试”的设计要求。

修复内容：

1. `execute_task` 和 `cancel_task` 统一使用 `asyncio.wait_for`，上限来自任务请求的 `timeout_seconds`。
2. 执行超时进入 `timeout`，错误码 `ROBOT_TASK_TIMEOUT`；取消超时进入 `unavailable`，同时把机器人标记为不可用。
3. 新增慢 Adapter 测试，确认 0.05 秒超时在 0.5 秒内返回，且不把超时误记为成功。

### 3.2 幂等键冲突被静默忽略

同一机器人复用同一 `idempotency_key` 但提交不同 capability / parameters 时，Repository 直接返回旧任务。这会让调用方误以为新目标已提交，破坏任务审计和运动安全。

修复内容：

1. 相同幂等键且 capability / parameters 相同时仍返回原任务，保持正常重试语义。
2. 相同幂等键但语义不同时返回 `ROBOT_TASK_IDEMPOTENCY_CONFLICT` / HTTP 409。
3. 增加 Service 和 API 两层测试，确认相同请求幂等、不同请求冲突。

### 3.3 移动观察来源被硬编码为 Mock

`RobotMobilePerceptionService` 在生成 Observation 时始终写入 `mock_only=true`，即使未来接入真实 Adapter 也会被错误标记为 Mock。该字段会直接影响来源可信度和验收记录。

修复内容：

1. `mock_only` 改为根据当前 Adapter ID 是否为 `mock_robot` 派生。
2. 移动观察验收测试同时校验来源类型、采集时间来源、时间不确定度、媒体句柄和分析状态。

### 3.4 离线恢复缺少连接事件

机器人从离线恢复后，状态投影会恢复 `connected` 和 `last_seen_at`，但没有生成 `connection_changed` 事件。离线任务失败有事件，恢复没有事件，无法从审计时间线还原完整连接过程。

修复内容：

1. 统一状态写入路径，检测 `connection_state` 或 `is_online` 变化。
2. 变化时写入 `connection_changed` 事件，恢复为 info，断开为 critical，并保留前后连接状态。
3. 离线恢复测试确认重新上线后存在 `payload.is_online=true` 的连接事件。

## 4. Acceptance Matrix

| 验收项 | 结论 | 验收说明 |
| --- | --- | --- |
| 机器人独立 Adapter | 通过 | Robot 模块与 Device Adapter 分离，Robot Adapter 只暴露高层能力；架构边界测试确认 Agent Runtime / Planner 不导入 `arvuno_core.robots`；低层参数 `motor`、`joint`、`pwm`、`servo`、`firmware`、`shell` 被拒绝 |
| Robot Capability 注册 | 通过 | 8 项 Mock 能力以 `concept / disabled / 需确认` 注册；同步后持久化验证状态、运行时开关、风险、同意声明和证据；执行要求 `runtime_enabled` 且验证状态至少 `bench_verified`；默认全部 disabled，机器人默认禁用 |
| 定位和状态同步 | 条件通过 | 位置、坐标系、姿态角、定位状态和置信度可持久化；导航成功后位置更新；状态快照和 `last_seen_at` 可查询；定位丢失阻止导航和移动观察。没有自动心跳轮询、状态 freshness TTL、地图版本和禁入区校验 |
| 导航任务 | 通过 | 支持确认、拒绝、取消、幂等、成功、导航失败、定位丢失、低电、离线、急停、人工接管和超时；任务终态和事件持久化；无确认任务不会直接执行。执行状态未细分为 accepted / running / waiting_result，后置条件只以 Adapter 返回值为准 |
| 主动观察 | 条件通过 | `evaluate → authorize → execute` 完成导航、观察、Observation 入库、State Estimation 重建和 Reasoning 重跑；导航或观察失败进入 unavailable，不伪造观测。当前没有真实视觉分析：标签为空、置信度 0、分析状态固定 `not_performed`，媒体只是受控句柄；没有返坞和任务中断恢复 |
| 感知数据来源 | 通过 | 自动注册 `robot_mobile` Observation Source，记录 `on_demand_only`、禁止持续视频、支持属性、信任等级、时间来源和隐私范围；Observation 保留 source、space、correlation ID、采集时间来源和不确定度；不保存原始媒体主存储 |
| 用户授权 | 条件通过 | 移动观察必须同时确认导航和摄像头采集，授权作用域与目标空间、机器人、步骤和位置精确匹配；篡改 scope、未授权空间和缺少确认都会阻止执行；机器人 API 需要 Bearer Token。通用能力 API 尚未强制 `requires_consents`，没有独立授权表、撤销和一次性确认令牌，直接创建任务时 `confirmed=true` 可跳过两步确认 |
| 急停 | 通过 | 急停默认激活；新导航在急停状态下进入 `safe_stopped`，错误码 `ROBOT_SAFETY_STATE`，位置不变化；状态投影显示 `emergency_stop=true` 和 `motion_safety_state=stopped`。没有 `request_safe_stop` API，也没有用户确认的恢复流程 |
| 人工接管 | 通过 | 人工接管阻止新任务并进入 `safe_stopped`；状态投影显示 `manual_takeover=true` 和 `manual_takeover` 安全状态；Arvuno 不会自动恢复被接管任务 |
| 离线恢复 | 条件通过 | 离线任务进入 `unavailable` 并标记机器人不可用；状态接口返回 disconnected；重新上线后显式状态刷新恢复 connected、online 和 `last_seen_at`，新导航任务成功，并产生连接恢复事件。没有自动心跳、重连轮询和断线期间任务观察循环 |
| 机器人离线时 Core 独立运行 | 通过 | 机器人离线时 `/health`、系统状态、设备、空间、环境、事件、任务、Memory、Observation Source 和机器人列表接口均返回 200；移动观察返回结构化 409 而不是 500；既有设备与环境读取不受影响 |
| Mock 与真实硬件分开记录 | 通过（记录层面） | 本报告所有导航、观察、安全状态和感知来源结果都来自 Mock Adapter；真实机器人测试未执行，Mock 结果没有被标记为真实硬件验收 |

## 5. Architecture And Security Verification

### 5.1 Adapter Boundary

`robots/interface.py` 只定义 `get_robot`、`get_capabilities`、`get_state`、`execute_task` 和 `cancel_task`。没有关节、电机、PWM、固件、shell 或任意 SDK 直通方法。`robots/` 不导入 `devices/`、Home Assistant、HTTP 客户端或 SQLAlchemy 之外的设备实现；Persistence 仍通过 Unit of Work 边界进入。

移动观察服务只依赖 `RobotApplicationService`，不导入 `RobotAdapter`、`RobotRegistry` 或直接调用 `adapter.execute_task`。这保证机器人高层能力不会被 Active Perception 绕过。

### 5.2 Capability Evidence And Enablement

能力注册保留 `verification_status`、`runtime_enabled`、`risk_level`、`requires_confirmation`、`requires_consents`、`min_battery_percent`、输入 / 输出 Schema、安全包络和 `evidence`。Mock 能力的 evidence 为 `mock_only=true`，验证状态默认 `concept`，不会伪装成真实硬件已验证。

执行前检查运行时开关和验证状态；`concept` 和 `specified` 能力不能执行。当前没有能力目录前端和证据审批工作流，也没有真实硬件证据链。

### 5.3 State, Time And Provenance

状态快照保存连接、在线、运动安全、急停、人工接管、电量、摄像头 / 麦克风 / 扬声器状态、位置、来源、采集时间和接收时间。Observation 保留 `source_type=robot_mobile`、`observed_at_source=device_clock`、`observed_at_uncertainty_ms=1000` 和 correlation ID。事件保留发生时间和接收时间。

没有心跳窗口、时钟偏差、迟到标记和状态过期策略；状态查询会刷新并持久化快照，但没有后台状态同步循环。

### 5.4 Authorization And Safety

移动观察授权要求两个独立布尔确认，授权 scope 同时绑定机器人、目标空间、导航目标、步骤和来源。执行前重新校验授权，篡改 scope、错误状态和空间 allowlist 都会阻止创建机器人任务。

机器人任务确认接口只依赖 API Token，没有一次性令牌；通用能力创建接口允许 `confirmed=true`。这两点使“用户确认”在直接 API 路径上弱于桌面机器人设计中的独立确认要求。真实硬件开放前必须补齐授权记录、撤销、能力同意检查和一次性确认。

### 5.5 Offline Isolation

机器人离线不会阻塞 Arvuno Core 的启动和环境查询。移动观察在机器人不可用时返回 `ROBOT_MOBILE_UNAVAILABLE`，不会创建导航任务或 Observation。离线恢复通过显式状态刷新完成，恢复事件进入机器人事件表。

## 6. Design And Implementation Scope Conflict

这是本轮验收的阻塞性发现，不能由测试通过掩盖。

| 项目 | 第 34 号设计（当前选定桌面机器人） | 当前实现 |
| --- | --- | --- |
| 载体 | 固定桌面机器人，不做轮式导航 | Mock 仍是通用移动机器人形态 |
| 第一版能力 | `report_status`、`request_safe_stop`、`cancel_task`、`enter_idle_pose`、`look_at`、`observe_scene`、`listen_once`、`speak`、`run_diagnostics` | `navigate_to`、`observe`、`inspect`、`speak`、`listen`、`return_to_dock`、`charge`、`report_status` |
| 明确不注册 | `navigate_to`、`return_to_dock`、`charge`、`inspect` | 四项全部注册并可由 Mock 执行 |
| 移动观察 | 固定位置 / 受限姿态观察 | 先 `navigate_to` 再 `observe` |
| 定位 | 桌面安全包络和姿态限位 | 房间坐标、yaw 和定位状态 |

当前代码和能力清单更接近第 33 号商用移动机器人设计，而路线图与第 34 号文档把自制桌面机器人作为有效选型。ARS-06 关闭前必须由用户确认唯一权威载体，并二选一修正实现或设计：

1. 如果载体是桌面机器人：移除或禁用 `navigate_to`、`return_to_dock`、`charge`、`inspect`，补齐 `look_at`、`observe_scene`、`request_safe_stop`、`enter_idle_pose`，移动观察改为受限姿态观察。
2. 如果继续验证移动机器人：明确第 34 号桌面机器人设计不是当前实现基线，并重新确认移动导航、空间授权和禁入区范围。

在该确认完成前，本报告中的导航和移动观察“通过”只对当前 Mock 移动链路成立，不代表桌面机器人设计通过。

## 7. Real Hardware Test Record

本节单独记录：**未执行**。

1. 没有真实机器人型号、硬件版本、固件版本、Edge Runtime 和官方开发环境。
2. 没有最终 BOM、机械结构、桌面安全包络、电气保护和供电设计。
3. 没有固件接口契约、限位、看门狗、心跳丢失、过流、过温、倾倒和断电测试记录。
4. 没有真实急停、保护停止、人工接管、恢复流程和残余风险确认。
5. 没有真实导航、定位、避障、禁入区、返坞和低电策略测试。
6. 没有真实摄像头、麦克风、扬声器、媒体时间戳、设备释放和隐私删除测试。
7. 没有真实视觉 / OCR / STT / TTS 模型和云端处理授权验收。
8. 没有用户签署的 ARS-06 安全与授权确认记录。

上述结果不能用 Mock 测试替代。ARS-06.2 真实机器人接入仍未开始。

## 8. Unimplemented Or Not Accepted Capabilities

1. ARS-06.2 真实机器人只读接入和真实导航未实现、未验收。
2. Web Console 机器人最小状态页未实现；当前只有后端 API。
3. Agent / Planner 只读机器人工具未实现；Agent 不能查询机器人状态或请求观察。
4. 机器人授权表、授权撤销、能力级 `requires_consents` 强制检查和一次性确认令牌未实现。
5. 自动心跳、重连轮询、状态 freshness TTL、迟到事件和时钟偏差处理未实现。
6. 主动观察没有真实媒体存储、视觉分析、OCR、空结果 / 部分结果语义和返坞恢复。
7. 任务状态没有 accepted / running / waiting_result 细分，没有后置条件验证、冲突任务和断线任务观察。
8. 没有 `request_safe_stop` API、禁入区、地图版本和导航边界。
9. 没有真实硬件能力证据、台架测试和安全审批。
10. 当前 Mock 能力中的 `inspect`、`return_to_dock`、`charge` 等只返回确认结果，没有完整业务语义。

## 9. Inherited Risks

ARS-02 的隐私删除端到端、目标规模压测、备份恢复和真实 ESPHome / ESP32 验收仍未全部关闭；ARS-03 的语义检索、自动压缩、多用户隔离和真实程序验证链路未完成；ARS-04 的 AI Planner / 评估器、多步与非设备计划、Level 3 / 4 和真实 Observer 未完成；ARS-05 的真实摄像头 / 麦克风、真实模型、生产云端 Provider 和自动保留清理调度器未完成。

这些缺口会直接影响机器人观察的真实性、长期治理和主动任务闭环。ARS-06 条件通过不解除上述前置风险。

## 10. Final Verdict

ARS-06 当前 Mock 链路达到 **条件通过**：独立 Adapter、能力注册、定位和状态投影、导航任务、移动观察、感知来源、授权、急停、人工接管、离线恢复和机器人离线时 Core 独立运行都有可重复测试证据。超时、幂等冲突、Mock 来源标记和恢复事件四个缺陷已修复并加入回归。

ARS-06 不关闭。真实硬件未验收，Web Console 和 Agent 工具缺失，授权模型不完整，自动心跳和状态 freshness 缺失，主动观察没有真实视觉分析。最重要的阻塞项是第 6 节的载体与能力清单冲突：在用户确认唯一权威载体之前，不能把当前移动 Mock 链路解释为自制桌面机器人验收通过。
