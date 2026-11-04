# 28. ARS-03 World Memory Acceptance Report

- 日期：2026-11-04
- 分支：`main`
- 基线提交：`7210f5a`
- 验收范围：ARS-03.0 记忆系统设计、ARS-03.1 Memory Service 和 ARS-03.2 环境时间理解与历史关联
- 最终结论：**部分通过 / 未完全通过；ARS-03 不关闭**

## 1. Executive Summary

ARS-03 的持久记忆模型、Memory Service、Memory Repository、REST API、前端管理页、生命周期和只读 History 查询已经实现，并通过本轮后端全量回归、静态检查、前端类型检查 / 构建和数据库级删除复核。五类记忆的职责边界清楚：`memories` 只保存 episodic、semantic 和 procedural 长期记忆；Working Memory 复用运行时上下文和现有会话 / 任务数据；`user_preferences` 是结构化用户偏好的权威表；History 层只读取既有观测、事件、任务、空间、实体和快照记录，不复制新的历史事实。

来源规则、事实与推断分离、AI 推断过期约束、用户纠正、偏好授权、过期清理和物理删除均已验证。时间范围、缺失区间、迟到数据、未来偏差、空间 / 设备 / 实体历史、趋势、环境快照、快照差异和事件 / 任务关联也通过测试。四类确定性中文历史问答接口可用，且回答只基于保留的真实记录。

最终验收不能标记为完全通过。原始验收时 Agent Runtime 还没有接入 Memory retrieval 或 History API；验收后更新已通过 `retrieve_memory` 和 `query_history` 两个只读工具接入现有 Service，不经过 `/api/history/ask` 内部 HTTP 自调用。当前检索仍是关系过滤加大小写折叠的 `LIKE`，现在可匹配 `keywords` 字段，但仍不是语义检索；自动压缩、长期知识提炼、记忆图谱、多用户 / 家庭成员隔离、真实工具执行自动产生程序验证、目标规模 SQLite 压测、生产备份恢复演练和真实 AI Provider 验收均未完成。ARS-02 D1 投影缺陷已修复复验，但其 D2-D8 验收缺口仍在，本报告不能关闭 ARS-02。

## 2. Acceptance Environment

验收使用隔离临时 SQLite 数据库和自动化测试环境，没有修改用户日常数据库或运行中的环境状态。数据库迁移检查结果为 Alembic head `d41d8acd98a0`。

执行的回归和检查：

| 检查 | 命令口径 | 结果 |
| --- | --- | --- |
| Backend full regression | `pytest -q` | 255 passed；唯一警告是既有 FastAPI / Starlette TestClient 的 `httpx` deprecation warning |
| Backend lint | `ruff check .` | 通过 |
| Backend format | `ruff format --check .` | 通过，209 files already formatted |
| Frontend typecheck | `pnpm typecheck` | 通过 |
| Frontend build | `pnpm build` | 通过；仅保留既有 Vite chunk 大于 500 kB warning |
| Frontend format | `pnpm format:check` | 通过 |
| Migration check | `alembic current` | `d41d8acd98a0` |
| Post-acceptance backend regression | `pytest -q` | 273 passed；加入 Memory / History Agent 只读工具集成测试后的最新全量结果 |
| Post-acceptance lint / format | `ruff check .` / `ruff format --check .` | 通过 |

重点测试文件：

- `backend/tests/test_memory_system.py`
- `backend/tests/test_history_time_understanding.py`

## 3. Acceptance Matrix

| 验收项 | 结论 | 说明 |
| --- | --- | --- |
| 五类记忆职责 | 通过 | Working Memory 不建长期表；episodic / semantic / procedural 保存在 `memories`；User Memory 权威表是 `user_preferences`；历史权威数据仍留在各自 History 表 |
| Observation / Event / Task / Conversation 边界 | 通过 | Memory 不完整复制传感器流、事件流、任务日志或聊天记录，长期摘要通过 evidence 指回原始记录 |
| 来源追踪 | 条件通过 | 记录来源类型、来源记录 ID、时间、置信、验证、确认、有效期和范围；创建时校验 evidence 存在。多态源记录没有数据库级强外键，依赖应用层校验和引用 |
| 事实与推断分离 | 通过 | AI 推断强制为未确认、未验证的 expiring candidate，默认 7 天过期；只有用户陈述可确认 |
| 用户记忆管理 | 通过 | 偏好要求显式用户来源、授权语句和确认；draft 不进入检索；用户可查看、修改、确认和删除 |
| 更新、纠正和冲突 | 通过 | 更新写修订；用户纠正保留来源历史；语义事实同主谓不同值触发冲突检查 |
| 程序记忆 | 条件通过 | 显式 procedure version 和 validation 达标后才进入检索；真实工具执行自动产生验证的链路未实现 |
| 过期、保留和清理 | 通过 | 过期记忆和过期偏好会被隐藏，cleanup 可转为过期并执行保留清理 |
| 记忆删除 | 通过 | 数据库级复核确认相关记忆、evidence、revision、access log、procedure version、validation、preference 和 preference access log 被删除；授权审计 `memory_consents` 保留是设计内行为 |
| 相关历史查询 | 通过 | 可关联 observation、event、task、conversation message、environment snapshot 和 tool execution 记录 |
| Retrieval API | 条件通过 | 按问题类型返回记忆、偏好和来源引用；当前实现是关系过滤 + `LIKE`，不是语义检索 |
| 时间范围查询 | 通过 | 支持用户本地边界转换、UTC 存储、缺失区间和分页 |
| 时间语义 | 通过 | 区分采集、接收、处理时间；暴露迟到、未来偏差和缺失采集时间 |
| 空间 / 实体 / 设备历史 | 通过 | 空间后代聚合、实体历史和设备相关历史通过测试 |
| 环境快照 | 通过 | 可按时间选择快照并返回保留范围内状态 |
| 快照差异 | 通过 | 区分设备可恢复候选、物理状态变化和不可恢复变化；不把物理世界恢复描述成时光回滚 |
| 趋势统计 | 通过 | 支持房间排序、平均值、计数和非法值过滤 |
| 事件 / 任务关联 | 通过 | 可按 correlation 关联观测、事件和任务，并连接环境变化 |
| 历史自然语言接口 | 条件通过 | 四类确定性中文模板查询通过；未知模板显式拒绝。这不是通用自然语言理解 |
| Agent 使用 Memory / History | **条件通过（验收后更新）** | `retrieve_memory` 和 `query_history` 只读工具委托 MemoryService / HistoryService；模型只接触 Tool Catalog，不接触 Repository 或 SQL。真实 DeepSeek 会话仍未验收 |
| 前端管理 | 条件通过 | `/memory` 页面、API 客户端、类型检查和构建通过；本轮未重新执行浏览器视觉验收 |
| 数据库和环境保护 | 通过 | 使用隔离临时库，迁移和既有核心回归通过；未破坏现有数据库结构或环境状态 |

## 4. Architecture Verification

### 4.1 Memory Boundaries

`memories.memory_type` 只保留三类长期记忆：

1. `episodic`：过去事件、环境变化、任务和执行摘要。
2. `semantic`：稳定事实、空间关系和设备知识。
3. `procedural`：经验证的流程和技能。

Working Memory 没有新建长期表，继续由 `conversations`、`conversation_messages`、活动任务和环境上下文承载。User Memory 的权威表是 `user_preferences`，避免把用户长期偏好混入通用事实表。

History 查询复用 ARS-02 及既有系统的权威数据：`observations`、`events`、`tasks`、`spaces`、`entities` 和 `environment_snapshots`。History Service 和 Repository 是只读查询边界，不新增历史事实副本表，也不把原始观测自动升级成长期 Memory。

### 4.2 Service And Persistence

Memory Service 负责来源校验、生命周期、冲突检查、用户确认、纠正、程序验证、过期、清理、删除、检索过滤、修订和访问审计。`MemoryStore` 隐藏 SQLAlchemy 会话，`SqlAlchemyMemoryStore` 适配 Repository 边界；阻塞数据库调用通过线程池执行。

核心表包括：

- `memories`
- `memory_evidence`
- `memory_revisions`
- `memory_consents`
- `memory_procedure_versions`
- `memory_procedure_validations`
- `memory_access_logs`
- `user_preferences`

删除验证覆盖三类代表数据。Semantic memory 删除前有 1 条 memory、1 条 evidence、2 条 revision 和 3 条 access log，删除后对应残留均为 0。Validated procedural memory 删除前有 procedure version 和 validation，删除后全部残留为 0。User preference 删除后 preference 和 preference access log 均为 0；`memory_consents` 中保留授权审计是设计内行为，不是偏好数据残留。

### 4.3 History And Time Understanding

History API 覆盖时间范围、空间后代、实体、趋势、环境快照、快照差异、correlation 关联和 `/api/history/ask`。数据库继续使用 naive UTC 存储；API 使用 aware 时间并按用户 IANA 时区换算边界。查询结果显式暴露：

- 采集时间缺失
- 迟到数据
- 未来时钟偏差
- 查询范围内的缺失区间
- 数据保留边界

历史回答基于真实保留记录，不会用模型推测补齐缺失。快照差异只标注可通过设备命令尝试恢复的投影候选；传感器读到的物理状态变化被标记为不可真正回滚，系统不宣称现实时光回滚。

## 5. Security, Privacy And Permissions

Memory 和 History API 都要求 Bearer token。未授权请求被拒绝，Memory 的 owner scope 通过 API 契约测试覆盖。偏好创建需要授权语句，draft 不进入检索，删除偏好会清理偏好访问日志。

记忆访问覆盖 create、read、retrieve、update、confirm、correct、delete 和 expire 的审计语义。AI 推断不会自动成为永久事实，临时对话也不会自动升级为长期用户偏好。当前部署契约仍是单用户 / 本地用户；家庭成员级隔离和多租户授权没有实现，不应误判为已完成。

## 6. Unimplemented Or Not Accepted Capabilities

以下能力必须保持未完成标记：

1. 语义检索未实现；当前只有关系过滤和 `LIKE` 文本匹配。
2. 记忆图谱未实现。
3. SQLite FTS 未实现，未来只能作为文本检索补充评估。
4. 自动压缩和长期知识提炼未实现。
5. 多用户 / 家庭成员数据隔离未实现。
6. 真实工具执行自动产生 procedure validation 的链路未实现。
7. Memory evidence 对所有上游源记录的数据库强外键未实现；当前依赖创建时存在性校验和应用层引用。
8. 本轮前端只完成类型检查和构建验证，未重新执行浏览器视觉验收。
9. 真实 AI Provider、目标规模 SQLite 压测和生产备份恢复演练未执行。

向量数据库没有引入。这是 ARS-03 的设计约束，不记为缺陷；后续若引入必须先重新确认架构和隐私边界。

## 7. Inherited ARS-02 Risk

ARS-02 D1 Environment Context v2 投影缺陷已在验收后修复并复验：空间级状态估计、即时 Context、Snapshot、API、只读 Tool、重启恢复、状态更新、空间迁移和重复重建一致性通过测试。但 ARS-02 的 D2-D8 仍未验收，包括重复归属收敛、隐私删除端到端、目标规模性能、备份恢复、真实 ESPHome / ESP32 和真实 AI Provider。

因此 ARS-03 验收不能关闭 ARS-02。后续工作不得把 D2-D8 视为已由 D1 修复解决。

## 8. Final Verdict

ARS-03 的记忆建模、生命周期、用户偏好、来源追溯、历史查询和时间理解达到“部分通过 / 条件可用”状态，可作为受控的 Memory 和 History 基础能力继续评审。但 Agent 记忆与历史使用链路、语义检索、长期知识提炼、多用户隔离和真实运行验收缺失，ARS-03 不能关闭。

建议的下一步不是直接开启新子阶段，而是先验证真实 AI Provider 下 Agent 能否稳定判断何时调用 Memory Retrieval 和 History Query；同时继续处理 ARS-02 D2-D8。所有未完成能力必须在后续阶段重新列入验收范围。

## 9. Post-Acceptance Tool Integration Update

更新日期：2026-11-04。本次更新只增加受控只读入口，不改变 Memory 写入策略、History 权威数据或快照差异语义。

实现结果：

1. `retrieve_memory` 注册为 `READ_ONLY`、默认允许且无需确认，委托 `MemoryService.retrieve`。
2. `query_history` 注册为 `READ_ONLY`、默认允许且无需确认，委托 `HistoryService` 的既有查询方法。
3. Agent Runtime 新增 `MEMORY_QUERY` 和 `HISTORY_QUERY` 意图映射；模型只能通过 Tool Catalog 选择参数，不接触 SQLAlchemy、Repository 或内部 HTTP API。
4. 系统提示约束回答必须来自工具返回记录；Memory 结果摘要保留来源引用和确认状态，History 结果摘要保留记录数量、本地时间和缺失区间。
5. Memory 关键词检索同步匹配 `memories.keywords`，避免用户显式提供的关键词不可检索。
6. 新增 `backend/tests/test_agent_memory_history_tools.py` 覆盖注册边界、Service 委托、服务不可用降级、schema 校验、执行器权限、Agent 意图与摘要、用户记忆确认后检索、历史查询和快照差异集成。

验证结果：

1. 后端全量回归 `273 passed`。
2. Ruff lint 和 format check 通过。
3. 本更新不宣告语义检索、自动压缩、长期知识提炼、记忆图谱、多用户隔离、真实程序验证、真实 AI Provider 会话、目标规模压测或生产备份恢复已完成。
