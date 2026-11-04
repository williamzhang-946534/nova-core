# 10. 记忆系统设计

## 目标

Memory System 让 Arvuno 区分实时状态、历史记录、长期知识、用户偏好和可复用流程，
并按来源、验证状态、授权范围和保留策略管理这些信息。

ARS-03.1 已实现关系型 Memory Store、Memory Service、REST API 和前端管理入口。
系统继续使用 SQLite 和关系查询；没有引入向量数据库，也没有把 SQLite FTS
当作完整语义记忆能力。

## 记忆架构

### 持久记忆类型

`memories.memory_type` 只保存三类持久记忆：

| 类型 | 内容 | 约束 |
| --- | --- | --- |
| `episodic` | 过去发生的事件、环境变化、任务和执行摘要 | 必须引用可追溯历史证据 |
| `semantic` | 稳定事实、空间关系和设备知识 | 可用 `subject/predicate/object_value` 冲突检查 |
| `procedural` | 经过验证的操作流程和可复用技能 | 必须有 procedure subject 和验证版本 |

Working Memory 不建新表。当前对话、消息、活动任务和环境上下文继续由
`conversations`、`conversation_messages`、`tasks` 和环境缓存表示。

### 数据职责边界

| 系统 | 权威内容 |
| --- | --- |
| Observation History | 原始观测和可追溯读数 |
| Event History | 重要领域事件 |
| Task History | 任务、步骤和工具执行过程 |
| Conversation History | 对话消息 |
| `user_preferences` | 用户结构化偏好 |
| `memories` | 筛选后的长期事实、事件摘要和流程知识 |
| Working Memory | 运行时短期上下文，不复制成长期表 |

Memory 不重复保存完整传感器流、事件流、任务日志或聊天记录。长期摘要通过
`memory_evidence` 指回原始记录，读取时可返回来源引用。

### 关键模型

领域层由 `MemoryService` 和 `MemoryStore` 组成。`MemoryStore` 是协议，隐藏
SQLAlchemy session；`SqlAlchemyMemoryStore` 适配 `MemoryRepository`。
Service 负责生命周期、来源校验、用户授权、语义冲突、程序验证、检索过滤、
修订和访问审计。所有数据库操作通过 Unit of Work 提交，阻塞数据库调用在线程池执行。

## 明确边界

### 实时状态

设备状态、传感器读数、在线状态和当前活动任务随时可被新状态覆盖。它们留在
Environment Context、Device State 和 Task 运行时上下文中，不能因新鲜度高就
自动变成永久事实。

### 历史记录

观测、事件、任务、工具执行和对话消息只追加或按各系统状态推进，Memory 不得
改写这些原始记录。长期记忆只引用它们的最小脱敏快照。

### 用户偏好

`user_preferences` 是结构化偏好的权威表。偏好必须显式来自用户，记录
`source_record_id`、授权语句、确认状态、生效时间、过期时间、保留期限和适用范围。
draft 不进入检索；用户可查看、修改、确认或删除。一次对话猜测不能自动升级为
长期偏好。

### 长期记忆

长期记忆保存用户确认事实、筛选后的任务经验、重要事件摘要和验证流程。
每条记录必须有来源类型、来源 ID、置信度、验证状态、适用范围、生效时间和保留
或过期时间。API Key、令牌、模型中间推理、完整聊天记录和未筛选事件不属于记忆内容。

## 来源规则

支持的记忆来源：

`user`、`observation`、`event`、`task`、`conversation`、`ai_inference`、
`procedure_execution`、`system`。

写入规则：

1. 每条记忆记录 `source_type`、`source_id`、`confidence`、`verification_status`、
   `user_confirmed`、`valid_from`、`expires_at` 或 `retention_until` 以及 scope。
2. 创建时可附带最多 50 条 evidence；有 `evidence_id` 时必须先验证原始记录存在。
3. 用户陈述可确认为 verified；其他来源不得伪造用户确认。
4. `ai_inference` 强制为 expiring candidate：未确认、unverified，默认 7 天过期，
   不能直接进入 `status=current`。
5. 语义事实在相同 `subject_type/subject_id/predicate` 且值不同时触发冲突；
   服务要求用户纠正或先处理旧事实。
6. Procedural Memory 创建为 testing 版本，累计到配置的成功验证数后才 verified，
   candidate 也会转为 active；只有 validated 版本进入流程检索。

## 生命周期

记忆状态：

```text
candidate → active
candidate → corrected
active → corrected
active/candidate/corrected → expired
active/candidate/corrected → archived
expired/archived → physical delete after retention_until
```

操作语义：

| 操作 | 行为 |
| --- | --- |
| 创建 | 写入记忆、来源证据、create revision 和 access log |
| 更新 | 只允许当前记忆；保留上一内容、变更字段和原因 |
| 纠正 | 设置 `corrected`，递增纠正次数；用户纠正会标记 verified。AI 推断被用户纠正后，当前来源转为 `user` 并移除候选过期时间，原来源保留在修订中 |
| 确认 | 仅 `source_type=user`；设置 active、confirmed、verified |
| 过期 | 懒检查和 cleanup 都会转为 expired，并写 revision/access log |
| 清理 | expired/archived 超过 `retention_until` 后物理删除 |
| 删除 | 物理删除记忆及其证据、修订和访问日志 |

偏好生命周期为 `draft → active → revoked`。active 偏好到期后由 cleanup 转
revoked；revoked 超过 `retention_until` 后物理删除。删除前仍能查看，
删除会清理相关访问日志。

## 检索

检索入口是 `POST /api/memory-retrieval`，请求包含：

| 问题类型 | 查询对象 |
| --- | --- |
| `preference` | active 且未过期的 `user_preferences` |
| `semantic_fact` | active/corrected semantic memories |
| `spatial_fact` | active/corrected semantic memories |
| `historical_event` | active/corrected episodic memories |
| `task_record` | 含 `task_id` 或 task evidence 的 episodic memories |
| `procedure` | 只有带 validated procedure version 的 procedural memories |
| `any` | 三类持久记忆，但程序仍要求 validated |

SQL 关系查询负责类型、状态、空间范围和分页；当前实现用大小写折叠的 LIKE 匹配
标题、内容、摘要、语义字段和偏好键/描述。它只是文本过滤，不是完整语义检索。
未来可评估 SQLite FTS 作为文本检索补充，仍不能替代语义理解和冲突推理。

检索结果包含 memory/preference 视图、`source_references` 和时间戳。每个记忆的
来源引用含 evidence 类型、原始记录 ID、上游来源、信任度、最小快照和发生时间。
Memory 相关历史接口还能关联 observation、event、task、conversation message、
environment snapshot 或 tool execution，返回当前保存的记录摘要。

## API

所有 Memory API 通过 Bearer API token 保护。

### Memory

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/memories` | 创建记忆和证据 |
| GET | `/api/memories` | 按类型、状态、来源、关键词、环境/空间/实体和分页过滤 |
| POST | `/api/memories/cleanup` | 执行过期和保留清理 |
| GET | `/api/memories/{id}` | 读取一条记忆 |
| PATCH | `/api/memories/{id}` | 更新当前记忆 |
| POST | `/api/memories/{id}/correct` | 用户或系统纠正 |
| POST | `/api/memories/{id}/confirm` | 确认用户陈述 |
| DELETE | `/api/memories/{id}` | 删除记忆 |
| GET | `/api/memories/{id}/revisions` | 查看生命周期修订 |
| GET | `/api/memories/{id}/history` | 查看关联原始历史 |
| POST | `/api/memories/{id}/procedure-versions` | 创建流程版本 |
| POST | `/api/memories/{id}/procedure-validations` | 记录流程验证 |

### Preferences

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/memory-preferences` | 创建 draft 或已确认偏好，并写授权 |
| GET | `/api/memory-preferences` | 按状态、类别、关键词和分页查询 |
| GET | `/api/memory-preferences/{id}` | 查看偏好 |
| PATCH | `/api/memory-preferences/{id}` | 修改值、类别、描述、范围和过期时间 |
| POST | `/api/memory-preferences/{id}/confirm` | 确认 draft 偏好 |
| DELETE | `/api/memory-preferences/{id}` | 删除偏好 |

### Retrieval

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/memory-retrieval` | 按问题类型检索记忆和偏好并返回来源引用 |

## 前端管理

前端提供 `/memory` 管理页。用户可以：

1. 按类型、状态、来源、关键词和范围筛选记忆。
2. 创建记忆，提交来源和证据引用。
3. 确认用户陈述、纠正、更新、归档和删除记忆。
4. 执行生命周期清理，并查看过期/删除数量。
5. 按问题类型执行检索，检查来源引用。
6. 查看记忆详情、修订和关联历史。
7. 管理 draft/active/revoked 偏好、确认、修改、过期和删除偏好。

管理页与 API 使用相同授权；未确认候选和过期数据不会伪装成当前事实。

## 隐私与权限

1. API 使用 Bearer token；token 不是记忆内容。
2. `owner_id` 和 `access_level` 表达所有权；当前部署契约是单用户/本地用户，
   多租户隔离属于未来扩展，不得假设当前 API 已按家庭成员分别授权。
3. 用户可查看、修改、确认和删除自己的记忆与偏好。
4. 偏好创建必须带授权语句；删除目标记忆或偏好时清理其访问日志。
5. API Key、令牌、原始敏感媒体和模型中间推理不得写入记忆。
6. 审计记录覆盖 create、read、retrieve、update、confirm、correct、delete 和 expire。
7. Agent 只应读取意图相关记忆，不得把全部记忆塞入 Prompt；记忆不能绕过设备和
   工具安全策略。

## 测试

后端测试覆盖：

1. API 未授权拒绝。
2. 创建、来源证据、访问日志和历史引用验证。
3. 引用不存在的历史记录时失败。
4. 列表过滤、关键词检索和检索来源引用。
5. AI 推断只能作为过期 candidate。
6. 更新、语义冲突、用户纠正、确认权限限制。
7. 程序必须达到验证次数后才可检索。
8. 记忆和偏好过期、清理、删除、冲突和授权。
9. 关联 event/task/conversation 历史。
10. owner-only API 契约。

对应测试文件是 `backend/tests/test_memory_system.py`，数据库约束由
`backend/tests/test_database_schema.py` 校验。前端 TypeScript 类型和页面通过
`tsc --noEmit` 与 production build 验证。

## 当前限制

1. LIKE 检索不具备语义泛化能力。
2. 尚未实现自动压缩、记忆图谱和多用户隔离。
3. 当前阶段不引入向量数据库；SQLite FTS 只能在需要时作为文本检索的补充评估。
