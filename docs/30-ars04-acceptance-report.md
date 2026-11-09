# 30. ARS-04 World Reasoning & Orchestration Acceptance Report

- 日期：2026-11-06
- 分支：`main`
- 评审基线：`7d898fa Implement ARS-04 planning and perception systems`
- 验收范围：ARS-04.0 设计复核，ARS-04.1 Evidence-based Reasoning，ARS-04.2 Planning / Goal Compiler，ARS-04.3 Proactive Intelligence，ARS-04.4 Active Perception
- 最终结论：**部分通过 / 未完全通过；ARS-04 不关闭**

## 1. Executive Summary

ARS-04 的确定性推理、证据和假设持久化、单设备目标编译、计划生成与安全重规划、主动建议治理和主动感知决策闭环已经实现并通过本轮回归。Reasoning 产物区分观测事实、规则推导、AI 假设、已验证原因和未知信息；Evidence 保留原始来源引用。Planning 只生成和验证候选计划，提交后由 Task System 管理，设备动作仍由 Tool Executor 执行。Proactive 运行时自主级别默认封顶在 Level 2，具备去重、冷却、静默时间和频率限制。Active Perception 能识别信息缺口，敏感观测必须有作用域一致且未过期的授权，没有 Observer 时返回 unavailable，不伪造观测结果。

本轮不能宣告 ARS-04 完成。AI / 模型 Planner、AI Proactive 评估器、AI 感知评估器、多步计划、非设备计划、Proactive Level 3 接受后自动创建候选任务和 Level 4 有限自主执行仍未实现。Active Perception 没有接入 Task System / Tool Executor，也没有真实摄像头、麦克风、机器人或自主持续采集。真实隐私授权界面、ARS-04 前端管理界面和真实 AI Provider 端到端验收未完成。因此本报告验收的是确定性安全基础，不是完整 World Reasoning & Orchestration。

## 2. Validation Environment

验证使用隔离临时 SQLite 数据库和自动化测试环境；没有修改运行中的环境状态或真实设备。本轮验收前发现一个与日期推进有关的测试时钟问题，修复后重新执行全部验收检查。

| 检查 | 结果 |
| --- | --- |
| ARS-04 专项回归 | 首次 49 passed / 1 failed；修复时钟注入后 50 passed |
| Backend full regression | 323 passed，1 个既有 FastAPI / Starlette TestClient deprecation warning |
| Backend lint | `ruff check .` 通过 |
| Backend format | `ruff format --check .` 通过，214 files already formatted |
| Alembic heads | 单 head：`a7d4f83c1092` |
| Alembic current | 本地开发库已处于 `a7d4f83c1092`，本次未改库 |
| Alembic empty upgrade | 隔离空库升级到 `a7d4f83c1092` 通过，临时库已删除 |
| Frontend typecheck | `pnpm typecheck` 通过 |
| Frontend build | `pnpm build` 通过；保留既有 Vite chunk 大于 500 kB warning |
| Frontend format | `pnpm format:check` 通过 |

重点测试文件：

- `backend/tests/test_reasoning_engine.py`
- `backend/tests/test_planning_engine.py`
- `backend/tests/test_proactive_intelligence.py`
- `backend/tests/test_active_perception.py`
- `backend/tests/test_architecture_boundaries.py`
- `backend/tests/test_tool_system.py`
- `backend/tests/test_task_system.py`
- `backend/tests/test_agent_runtime.py`
- `backend/tests/test_automation_system.py`

上述九个安全与架构相关测试文件合计收集 137 项，全部包含在后端全量回归中通过。

## 3. Acceptance Matrix

| 验收项 | 结论 | 验收说明 |
| --- | --- | --- |
| Reasoning 事实和假设分离 | 通过 | Evidence 保留来源、质量和上下文；观测、derived 结果、verified cause、AI hypothesis 和 unknown 分别表示。时间相关性保持 non-causal，只有带已验证元数据的结论可标记 causal。AI 假设不自评为 supported，也不写入 State Estimate 的 observed / derived 状态 |
| Evidence 来源可追溯 | 通过 | Reasoning API 可查询 session、evidence、hypothesis 和原始来源。测试覆盖 Observation、State Estimate、Event、Task 和 Memory 引用；Memory 作为 derived evidence，不会升格为 observed fact。原始记录删除后的降级显示依赖既有隐私删除策略，本轮未重做真实隐私删除端到端 |
| Planning 与 Task System 边界 | 通过 | Planner 生成、验证和版本化候选计划；`approve` / `submit` 只产生 Task，不直接执行设备。计划步骤携带 `requires_confirmation`，后续状态以 Task System 为准。测试证明 Planner 不导入或调用 Tool Handler，也不绕过 Task System |
| Goal Compiler 可验证目标 | 条件通过 | 自然语言目标编译为空间、期望状态、约束、优先级、授权范围、成功条件、澄清项和未知项。模糊目标不会生成设备计划。当前实现覆盖确定性单设备目标，尚不支持复杂目标分解和非设备计划 |
| 执行失败后安全停止或重规划 | 通过 | Task 失败、结果不满足和状态不一致会保留旧计划、生成版本化 replanning record 和新候选计划；必要时停止。已执行步骤、差异和风险记录保留。不静默扩大授权，也不把旧版本改写为新事实 |
| Proactive 静默 / 去重 / 频率控制 | 通过 | 建议按 dedupe key 去重，冷却期内抑制重复通知；静默时间按用户本地时区计算，high importance 例外由测试固定；小时和日通知有硬上限。用户 dismiss 不会提高提醒频率，suppress preference 有过期时间。单次 motion 读数不推断异常 |
| 用户授权不扩大 | 通过 | Goal 创建时授权被规范化；后续确认只能提交不超过既有范围的授权，重规划同样不能扩大。Proactive 运行时最大自主级别默认 2，Service 不执行设备动作。Prompt、建议或相似历史任务不能提升权限 |
| Active Perception 信息缺口识别 | 条件通过 | 可比较候选来源 trust / cost，选择值得的补充观测；历史属性可帮助新空间发现来源。无 Observer、Observer 返回空、成本过高或 procedure gap 都显式返回 unavailable / 不适合，不伪造 Observation。AI 感知评估器未实现 |
| 敏感观测权限 | 通过 | 敏感缺口必须先获得作用域匹配的显式 consent；授权有过期时间，reject / delete 会撤销授权并避免重复请求。执行时重新校验 scope、expiry 和 consent，过期或撤销后阻止采集。未实现真实隐私授权界面 |
| 第一阶段安全体系没有回退 | 通过 | 全量回归覆盖 Tool Registry / Safety Policy / 确认令牌 / Tool Executor / Task 状态机 / Agent 候选校验 / 自动化任务链路。架构边界测试确认 Agent 不接触 SQLAlchemy、Repository、Device Adapter 或内部执行端口；高风险动作默认拒绝。未引入向量数据库或多 Agent 框架 |

## 4. Clock Defect Found During Acceptance

首次 ARS-04 专项回归中，`test_mock_observer_records_real_observation_updates_state_and_reruns_reasoning` 失败：新 Observation 和 State Estimate 重建成功，但查询结果因两天时间推进被标记为 `stale`，而测试断言的是固定验收时间下的 `observed`。

根因是 `StateEstimationService.list()` 直接读取系统 `datetime.now()`，而同服务的 `rebuild()` 和 `context_inputs()` 已经支持注入 `now`。这不是 Active Perception 伪造观测或状态重建失败；属于验收查询路径的时钟边界不一致。

修复内容：

1. `StateEstimationService.list()` 增加可选内部 `now` 参数，默认仍使用系统当前时间，REST API 对外契约不变。
2. Mock Observer 闭环测试按固定验收时间查询，保留“真实 Observation 写入后状态应为 observed”的验收语义。
3. 修复后 ARS-04 专项回归 50 passed，后端全量回归 323 passed。

## 5. Architecture And Security Verification

### 5.1 Reasoning

Reasoning Session、Evidence Bundle / Item 和 Hypothesis 持久化保存，诊断结果不回写 World Model 的 observed 状态。直接观测、确定性规则结果、AI 候选、已验证原因和未知信息使用不同状态和证据等级。Reasoning API 需要 Bearer 认证，缺失权限或非法请求返回结构化错误。坏数据和低质量数据会进入质量摘要或未知信息，不会被提升为事实。

### 5.2 Planning And Execution Boundary

Goal Compiler 将可操作的单设备目标转成结构化 Goal，Planning Engine 读取当前状态和能力目录后生成“读取状态、执行控制、验证结果”的候选步骤。系统风险上限保持 `low_risk`，离线设备、禁用工具、未授权工具、禁止动作和非法依赖在提交前拒绝。计划确认后提交 Task System；确认令牌、最终 Safety Policy、参数校验、审计和结果验证仍由既有 Tool Executor 链路处理。

Replanning 保留旧 Plan 和原因记录。失败重规划不删除历史，结果不满足时重新生成候选版本。新计划不会从模型输出、用户相似历史或 Proactive 建议中获得额外授权。

### 5.3 Proactive Governance

传感器阈值、设备不可用和任务失败可以触发候选评估。Level 1 只记录，Level 2 记录并通知；运行时自主级别默认上限是 2。事件总线路径、冷却、去重、静默时间、通知上限、用户反馈、过期清理和质量统计通过测试。Proactive Service 不直接调用设备动作，也不监听自身产生的事件。

### 5.4 Active Perception

Active Perception Request 保存目标、空间、所需信息、候选来源、时间限制、隐私等级、授权要求和原因。来源比较只使用可用能力目录和历史证据，敏感属性要求显式授权。Mock Observer 返回的结果必须通过目标、空间、来源和属性校验，随后写入真实 Observation、触发 State Estimation 重建和 Reasoning 重跑。没有能力时不虚构数据；procedure gap 不会被伪装成一次 Observation 可以解决的问题。

本阶段 Observer 是测试边界，不是生产采集器。默认应用没有开启自动 Observer，也没有自主持续采集。

## 6. Unimplemented Or Not Accepted Capabilities

以下能力必须继续标记为未完成：

1. AI / 模型 Planner 未实现；当前只有确定性规则 Planner。
2. AI / 模型 Proactive 评估器未实现；当前是规则触发和确定性阈值治理。
3. AI 感知评估器未实现；Active Perception 使用确定性缺口和来源比较。
4. 多步计划未实现；当前 Planner 只生成单设备、可验证的读写验证闭环。
5. 非设备计划未实现。
6. Proactive Level 3 接受后自动创建候选任务未实现。
7. Proactive Level 4 有限自主执行未实现，且默认禁止。
8. Active Perception 与 Task System / Tool Executor 的受控执行集成未实现。
9. 真实摄像头、麦克风、机器人 Observer、硬件导航和设备控制未实现。
10. 自主持续采集未实现。
11. 真实隐私授权界面和真实授权流程验收未完成；当前授权由带认证的 API 和作用域校验覆盖。
12. ARS-04 API 已实现，但完整的 ARS-04 前端管理界面未实现。
13. 真实 AI Provider 端到端推理、规划和感知验收未执行。
14. Reasoning 的 AI 候选生成器仍处于未配置状态，当前因果升级只来自测试中的已验证元数据或确定性规则。

## 7. Inherited Risks

ARS-02 的 D2-D8 遗留项仍未全部关闭，包括隐私删除端到端、目标规模压测、备份恢复、真实 ESPHome / ESP32 和真实 AI Provider。ARS-03 的语义检索、自动压缩、长期知识提炼、多用户隔离和真实程序验证链路也未完成。这些缺口会限制真实家庭中的 Reasoning、Planning、Proactive 和 Active Perception 效果，不能因 ARS-04 基础闭环通过而视为已解决。

## 8. Final Verdict

ARS-04 的证据、假设、单设备计划、失败重规划、主动建议治理、主动感知决策和第一阶段安全边界达到**部分通过 / 条件可用**状态，可以作为后续 AI 集成和任务编排的受控基础。但完整 World Reasoning & Orchestration 还缺模型化候选生成、多步与非设备计划、候选任务闭环、真实 Observer、真实授权界面和真实 Provider 验收。

ARS-04 不关闭。后续不应把本报告中的条件通过解释为完整能力完成；所有第 6 节项目必须在对应阶段重新验收。
