# 37. REPAIR-01 修复验收报告

日期：2026-11-13  
范围：`docs/36-full-project-review-2026-11-10.md` 中的 WP0-WP10 修复与最终回归  
结论：**Windows 本地 Mock 与受控开发验收通过；真实机器人验收未执行；ARS-02 至 ARS-06 继续保持不关闭。**

## 1. 验收基线与 Git 状态

| 项 | 状态 | 结果 |
| --- | --- | --- |
| 分支 | 已通过 | `main` |
| HEAD | 已通过 | `98556e9e311cbdd47328797b78673e35535bcf9a` |
| 工作区 | 已通过 | 保留 dirty 基线；未执行 commit、push、`reset --hard` 或 `clean -fd` |
| 既有未提交工作 | 已通过 | 原有 ARS-06 相关实现、`docs/35`、`docs/36` 和用户工作保留 |
| 根目录 `.env` | 已通过 | 未读取、未输出、未复制真实密钥 |
| 用户日常数据库 | 已通过 | 未访问；迁移与备份验证使用隔离临时库 |

`docs/35` 和 `docs/36` 在当前基线中是未跟踪历史输入文件。本次只在 `docs/34`、路线图、提示词手册和通用设计文档中追加当前状态，不修改两份报告的原始验收结论。

## 2. 原始问题与根因

| 原始问题 | 实际根因 | 修复结果 |
| --- | --- | --- |
| Robot API 可直接执行物理动作 | REST 层直接调用 `RobotApplicationService`，绕过 Task System、Tool Registry、Safety Policy 和 Tool Executor | 已通过：直接写入口返回 `ROBOT_EXECUTION_LOCKED`；后续统一链路仅限治理后的 Mock 能力 |
| Provider Log 持久化完整对话 | 日志摘要直接保存 messages、system prompt 和完整响应 | 已通过：默认 Schema v2 只保留元数据；debug 默认关闭、开发环境限定且自动过期；旧数据原地脱敏 |
| 保留配置没有运行时调度 | 各模块只有清理方法，没有应用 lifespan 内统一触发和审计 | 已通过：单进程 `RetentionScheduler` 调度六个业务任务，`retention_runs` 记录结果 |
| Adapter 连续异常重复发布不可用事件 | 每次异常按新时间生成事件，缺少可用性状态机 | 已通过：状态转换和版本语义控制事件，异常投影保留最后可信观测 |
| 测试与 Health 依赖全局配置 | `/health` 使用 `get_settings()`；部分测试未隔离配置文件 | 已通过：`request.app.state.settings` 优先；测试显式 `Settings(_env_file=None, ...)` |
| EventBus 慢订阅者阻塞轮询 | 顺序等待订阅者，缺少超时和异常隔离 | 已通过：订阅者超时、隔离执行，事件持久化不依赖单个订阅者成功 |
| 等待确认任务和重启恢复不可靠 | 任务缺少等待确认过期策略，未知结果可能被伪装完成 | 已通过：等待确认超时、重启恢复、`needs_verification` 和机器人 `execution_state_unknown` 测试通过 |
| 机器人能力与桌面硬件不一致 | 历史移动 Mock 被当作当前载体能力目录 | 已通过：冻结 `desktop_robot`；`mobile_robot` 保留接口但治理锁定 |
| Robot Consent 和确认边界不足 | 缺少独立 Consent、执行审计和服务端一次性确认 | 已通过：能力 / 数据类别 / 空间级授权和一次性 Token 强制检查 |
| 前端缺少机器人治理界面 | 原实现只有早期最小机器人能力 | 已通过：Mock 管理页覆盖状态、能力、Consent、任务、事件和故障信息 |

## 3. 修复方案与文件索引

完整未提交变更以 `git diff` 和 `git status` 为准；本次不能自动提交，因此下面按 Work Package 列出主要修复文件。

### WP0：机器人执行临时锁定

- `backend/arvuno_core/api/robots.py`
- `backend/arvuno_core/api/robot_perception.py`
- `backend/arvuno_core/perception/robot_mobile.py`
- `backend/arvuno_core/robots/errors.py`
- `backend/tests/test_robot_execution_lock.py`
- `backend/tests/test_robot_mobile_perception.py`

已通过：`POST /api/robots/{id}/enable`、创建 / 确认 / 取消任务请求和移动感知 `execute` 均不执行物理动作。状态、能力、授权、治理、事件、任务历史、心跳和重连接口保留。

### WP1：Provider Log 隐私最小化

- `backend/arvuno_core/ai/logging_support.py`
- `backend/arvuno_core/ai/mock.py`
- `backend/arvuno_core/ai/openai_compatible.py`
- `backend/arvuno_core/persistence/models.py`
- `backend/arvuno_core/persistence/provider_logs.py`
- `backend/alembic/versions/c9d5e7f8a9b0_minimize_provider_log_privacy.py`
- `backend/tests/test_provider_log_privacy.py`

已通过：默认不保存完整 messages、system prompt 或模型响应；敏感值脱敏；debug 默认关闭，仅 development 可开启，TTL 为 60-3600 秒；读取和清理移除过期 debug。旧全文数据通过迁移原地脱敏，不复制到新表，测试确认旧 system prompt、用户内容、响应和密码明文不可恢复。

### WP2：Retention Scheduler

- `backend/arvuno_core/retention/models.py`
- `backend/arvuno_core/retention/scheduler.py`
- `backend/arvuno_core/retention/service.py`
- `backend/arvuno_core/api/retention.py`
- `backend/arvuno_core/persistence/retention.py`
- `backend/arvuno_core/persistence/multimodal.py`
- `backend/arvuno_core/persistence/backup.py`
- `backend/arvuno_core/config.py`
- `backend/arvuno_core/app.py`
- `backend/alembic/versions/d2e6f8a1b4c7_add_retention_run_audit.py`
- `backend/tests/test_retention_scheduler.py`
- `backend/tests/test_backup_restore.py`

已通过：Event、Observation、Multimodal、Proactive、Environment Snapshot、Provider Log 六个任务独立配置；UTC 时间、批处理、幂等、失败审计、手动冷却和并发拒绝已覆盖。媒体清理覆盖文件与引用；备份包含 manifest、媒体哈希、孤儿报告和完整性检查。调度器明确 `single_process_only: true`，不宣称多进程分布式协调。

### WP3：设备可用性状态机

- `backend/arvuno_core/environment/reconciliation.py`
- `backend/arvuno_core/devices/models.py`
- `backend/arvuno_core/events/models.py`
- `backend/arvuno_core/events/conversion.py`
- `backend/arvuno_core/events/service.py`
- `backend/alembic/versions/e9f0a1b2c3d4_add_device_availability_state.py`
- `backend/tests/test_device_availability_reconciliation.py`

已通过：一次异常、连续异常、恢复、恢复后再异常、迟到事件、多设备异常、Adapter 断线、单设备离线和重启重建覆盖。UNAVAILABLE 状态不重复发布不可用事件；迟到事件不覆盖更新状态。

### WP4：工程健康与可重复构建

- `.github/workflows/ci.yml`
- `scripts/check.ps1`
- `backend/requirements.lock`
- `backend/requirements-dev.lock`
- `backend/arvuno_core/api/health.py`
- `backend/arvuno_core/config.py`
- `backend/arvuno_core/logging_config.py`
- `backend/tests/test_health.py`
- `backend/tests/test_logging_config.py`
- `backend/tests/test_robot_mobile_perception.py`
- `deploy/home-assistant-demo/compose.yaml`
- `frontend/package.json`
- `frontend/src/api/client.test.ts`
- `frontend/src/api/voice.test.ts`
- `frontend/src/hooks/useVoiceInteraction.test.ts`

已通过：本地后端 lint / format / pytest / compileall / pip check 通过；前端 typecheck / Prettier / Vitest / build 通过。GitHub Actions 已配置 Python 3.11、Node 22、锁定安装和全部必需检查；实际远程 Actions 运行未执行，标记为需要用户 push / 手动启用后验证。

### WP5：EventBus 与 Task 可靠性

- `backend/arvuno_core/events/bus.py`
- `backend/arvuno_core/tasks/models.py`
- `backend/arvuno_core/tasks/service.py`
- `backend/arvuno_core/automation/models.py`
- `backend/arvuno_core/automation/service.py`
- `backend/arvuno_core/persistence/tasks.py`
- `backend/arvuno_core/persistence/automations.py`
- `backend/tests/test_event_task_reliability.py`
- `backend/tests/test_automation_system.py`

已通过：慢订阅者、超时、异常隔离、多订阅者隔离、慢自动化、等待确认超时、重启、未知结果、取消和重复执行防护覆盖。任务不将未确认或结果未知执行伪装为完成；Automation Run 与最终确认 / 拒绝结果关联。

### WP6-WP8：Robot Profile、安全链与失效安全

- `backend/arvuno_core/robots/profiles.py`
- `backend/arvuno_core/robots/models.py`
- `backend/arvuno_core/robots/registry.py`
- `backend/arvuno_core/robots/service.py`
- `backend/arvuno_core/robots/mock.py`
- `backend/arvuno_core/tools/robot.py`
- `backend/arvuno_core/tools/safety.py`
- `backend/arvuno_core/tools/confirmation.py`
- `backend/arvuno_core/tools/executor.py`
- `backend/arvuno_core/tools/models.py`
- `backend/arvuno_core/persistence/robots.py`
- `backend/alembic/versions/b1c2d3e4f5a6_add_robot_profiles_and_governance.py`
- `backend/alembic/versions/f7a8b9c0d1e2_add_robot_consent_and_execution_audit.py`
- `backend/alembic/versions/8a9b0c1d2e3f_add_robot_failsafe_states.py`
- `backend/tests/test_robot_profiles.py`
- `backend/tests/test_robot_safety_chain.py`
- `backend/tests/test_robot_failsafe_state.py`
- `backend/tests/test_ars06_acceptance.py`
- `backend/tests/test_robot_adapter.py`

已通过（Mock / 架构）：Robot Tool Handler 进入 Task System、Tool Registry、Safety Policy、确认检查、Tool Executor、Robot Adapter、状态验证和执行审计。`desktop_robot` 只声明报告状态、看目标、场景观察、安全停止、待机姿态、说话和按需听；移动能力保留接口但治理锁定。Consent、过期 / 撤销 / 空间边界、一次性确认 Token、重放、参数变化、高风险拒绝、heartbeat freshness、取消失败和结果未知状态覆盖。

### WP9：机器人管理界面与 Agent 查询

- `frontend/src/App.tsx`
- `frontend/src/components/AppLayout.tsx`
- `frontend/src/api/robots.ts`
- `frontend/src/api/client.ts`
- `frontend/src/pages/RobotManagementPage.tsx`
- `frontend/src/types/robots.ts`
- `backend/arvuno_core/agent_runtime/models.py`
- `backend/arvuno_core/agent_runtime/runtime.py`
- `backend/arvuno_core/tools/robot.py`
- `backend/tests/test_robot_management_interface.py`
- `backend/tests/test_agent_runtime.py`

已通过（Mock）：Web Console 提供机器人列表、运行状态、能力启停、Consent 管理、任务记录、事件、安全停止状态和故障信息。Agent 只能通过只读机器人工具查询状态、能力、任务历史和授权，不直接访问 Adapter。

### WP10：文档同步

- `AGENTS.md`
- `README.md`
- `docs/00-project-overview.md`
- `docs/02-system-architecture.md`
- `docs/03-module-responsibilities.md`
- `docs/05-data-model.md`
- `docs/06-api-design.md`
- `docs/12-testing-strategy.md`
- `docs/13-development-roadmap.md`
- `docs/19-long-term-development-prompt-handbook.md`
- `docs/34-ars06-custom-desktop-robot-design.md`

已通过：文档与当前模块、API、数据契约、测试、隐私、Robot Profile 和安全边界同步。历史报告和原始结论未改写。

## 4. 数据迁移

| 迁移 | 目的 | 结果 |
| --- | --- | --- |
| `c9d5e7f8a9b0` | Provider Log 隐私最小化，旧全文原地脱敏 | 已通过 |
| `d2e6f8a1b4c7` | `retention_runs` 审计表 | 已通过 |
| `e9f0a1b2c3d4` | 设备可用性状态投影 | 已通过 |
| `b1c2d3e4f5a6` | Robot Profile 与治理状态 | 已通过 |
| `f7a8b9c0d1e2` | Robot Consent 与执行审计 | 已通过 |
| `8a9b0c1d2e3f` | Robot 失效安全状态 | 已通过 |

Alembic 当前单头：`8a9b0c1d2e3f`。隔离空库在 `%TEMP%\arvuno-repair01-20261113-113617\acceptance-empty.db` 执行 `upgrade head` 并通过。真实数据库升级未执行，标记为需要用户确认备份和停机窗口后手动操作。

## 5. 全量测试与验收结果

| 检查 | 结果 |
| --- | --- |
| 后端全量 `pytest backend -q` | 已通过：468 passed, 1 warning, 257.21s |
| Ruff lint | 已通过：All checks passed |
| Ruff format | 已通过：272 files already formatted |
| Python compileall | 已通过 |
| `pip check` | 已通过：No broken requirements found |
| Alembic heads | 已通过：`8a9b0c1d2e3f (head)` |
| 隔离空库迁移 | 已通过 |
| 备份 / 恢复专项 | 已通过：7 passed in 4.92s |
| 前端 TypeScript typecheck | 已通过 |
| 前端 Prettier check | 已通过 |
| 前端 Vitest | 已通过：3 files / 6 tests |
| Vite production build | 已通过：3079 modules transformed；存在大 chunk 提示，非失败 |
| GitHub Actions | 未执行：当前未 push，也未经用户授权推送；已提交等效本地检查 |

唯一后端 warning 是 Starlette TestClient 对 httpx 的既有弃用提示，不是失败。

## 6. 架构边界复核

| 边界 | 结果 |
| --- | --- |
| Agent Runtime 不直接访问数据库 | 已通过：静态导入复核只看到 AI Provider、Task Model 和内部协议抽象 |
| Agent Runtime 不直接访问 Device Adapter | 已通过：静态导入复核无 devices / robots / persistence / api 导入 |
| Robot API 不直接执行物理动作 | 已通过：四个直接写入口与移动感知执行入口锁定 |
| 机器人写操作进入统一执行链 | 已通过：Robot Tool Handler 与 Safety Policy / Tool Executor / Task System 回归通过 |
| Observation 不等于 Event | 已通过：既有观测管线和事件边界回归通过 |
| Memory 不复制所有原始观测 | 已通过：既有 Memory / Agent 检索边界回归通过 |
| Provider Log 默认不保存对话全文 | 已通过：普通请求只落库允许的 Schema v2 元数据 |
| Retention Scheduler 启动并执行 | 已通过：app lifespan、注入时钟、六类任务和失败审计回归通过 |
| EventBus 不被慢订阅者无限阻塞 | 已通过：超时与隔离测试通过 |
| 测试不依赖根 `.env` | 已通过：测试 Settings 显式 `_env_file=None`，路径隔离 |

## 7. 机器人专项复核

| 项 | 结果 |
| --- | --- |
| `desktop_robot` Profile 正确 | 已通过（Mock） |
| 移动能力未误开放 | 已通过：`mobile_robot` 治理锁定；desktop 不暴露移动能力 |
| Consent 强制检查 | 已通过（Mock）：缺失、过期、撤销和空间不匹配拒绝 |
| 一次性确认 Token 有效 | 已通过（Mock）：缺失、过期、重放、参数改变和任务不匹配拒绝 |
| `confirmed=true` 不是绕过通道 | 已通过：必须使用服务端验证 Token |
| heartbeat 和状态 freshness | 已通过（Mock） |
| 取消失败不伪装成功 | 已通过（Mock）：保留 `cancel_failed` / `execution_state_unknown` |
| 安全停止请求有真实结果 | Mock 请求 / 反馈已通过；真实硬件安全停止未执行 |
| Robot Task 与 Tool Execution 关联 | 已通过（Mock）：task、step、tool execution、robot request 和 correlation ID 审计覆盖 |
| 真实桌面机器人硬件验收 | 未执行：无真实硬件、固件契约和安全实测 |

## 8. 数据隐私专项复核

| 项 | 结果 |
| --- | --- |
| Provider Log 默认最小化 | 已通过 |
| Debug 默认关闭 | 已通过 |
| Debug 过期清理 | 已通过 |
| 密钥 / 凭据脱敏 | 已通过 |
| 旧全文日志迁移 | 已通过：隔离测试中原地脱敏，不复制全文 |
| 生产旧数据库迁移 | 未执行：必须先由用户确认备份 / 恢复影响和停机窗口 |
| Retention 自动运行 | 已通过（隔离测试） |
| 多模态媒体过期清理 | 已通过（隔离临时目录测试） |
| 孤立媒体引用检测 | 已通过（隔离测试） |
| 数据库 + 媒体备份 / 恢复一致性 | 已通过（隔离测试）；manifest 记录 `media_and_metadata`、孤儿、缺失和篡改状态 |
| 生产备份 / 恢复演练 | 未执行：需要用户手动备份真实库和媒体目录 |
| Privacy Erasure 完整边界 | 已通过（设计 / 隔离测试）：区分按期 Retention、用户删除请求、数据库、媒体、日志和备份恢复边界 |

SQLite 数据库恢复成功只表示元数据恢复；完整系统恢复还必须验证媒体文件、manifest 哈希、引用完整性和备份后的新增数据恢复策略。

## 9. 真实设备验证

| 项 | 状态 |
| --- | --- |
| 真实 ESPHome / ESP32 | 未执行 |
| 真实 AI Provider | 未执行 |
| 真实摄像头 / 麦克风 | 未执行 |
| 真实桌面机器人硬件 | 未执行 |
| 真实安全停止 / 机械限位 / 看门狗 | 未执行 |
| 真实移动机器人 | 未执行，且未获安全审批 |

本次所有机器人结果只能表述为 Mock 和受控开发验证。不得据此开放真实物理运动、持续音视频采集或移动控制。

## 10. 未完成事项与残余风险

1. 真实硬件、固件、BOM、安全包络和桌面安全实测未验收。
2. 真实机器人安全停止不能由 Core 软件验收替代；机器人本体必须具备独立安全停止机制。
3. 生产数据库迁移和生产备份恢复未执行。
4. GitHub Actions 远程运行未验证。
5. Retention Scheduler 是单进程应用内调度；当前架构不提供多进程锁或分布式协调。
6. Provider Log debug 虽然脱敏且短期过期，仍可能在开发环境中短暂保存请求内容；生产必须保持关闭。
7. Vite build 提示主 bundle 大于 500 kB，未在本次范围内做产品功能拆包。
8. 前端基础测试只有 6 项，覆盖率仍低；本次未引入额外复杂测试基础设施。
9. ARS-02 至 ARS-06 历史报告中记录的遗留缺口仍未全部关闭。

## 11. 下一步建议

1. 用户复核当前 dirty 工作区，确认后自行决定分批提交；本次不自动 commit / push。
2. 在确认完整备份和停机窗口后，用户手动执行真实数据库迁移；先试备份库，再处理生产库。
3. 推送后观察一次 GitHub Actions，确认远程环境和锁定依赖一致。
4. 在真实硬件采购和固件契约冻结前，继续保持机器人执行锁和移动能力治理锁。
5. 生产部署前保持 Provider Log debug 关闭；如需排障，使用临时 development 配置并确认自动清理。
6. 按第 36 号报告遗留项继续处理 ARS 阶段缺口；不得因 REPAIR-01 自动关闭 ARS-02 至 ARS-06。
7. 若进入真实桌面机器人硬件阶段，先完成第 34 号文档第 13 节的全部用户确认和硬件台架证据。
