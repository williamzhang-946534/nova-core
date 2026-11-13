# 12. 测试策略

## 测试目标

Arvuno 的测试重点不是追求覆盖率数字，而是保证真实世界操作链路安全可靠：

1. 状态模型正确。
2. 已入库事件不因订阅者异常丢失。
3. 权限判断不可绕过。
4. AI 输出不会直接触发危险操作。
5. 设备控制可验证。
6. 失败场景能安全停止。

## 测试分层

```text
        ┌────────────────┐
        │ 验收测试        │
        ├────────────────┤
        │ API / E2E 测试  │
        ├────────────────┤
        │ 集成测试        │
        ├────────────────┤
        │ 单元测试        │
        └────────────────┘
```

| 层级 | 范围 | 是否外部访问 |
| --- | --- | --- |
| 单元测试 | 模型、状态机、权限、工具校验 | 否 |
| 集成测试 | API、数据库、Adapter、Provider、Tool Executor | 使用 Mock |
| 合同测试 | API Schema 和前端类型 | 否 |
| 安全测试 | 权限、风险、注入、确认 | 使用 Mock |
| 验收测试 | 完整用户流程 | 可选真实设备 |

## 测试环境

开发阶段提供：

1. SQLite 测试数据库，每个测试独立初始化。
2. Mock Home Assistant API。
3. Mock Device Adapter。
4. Mock AI Provider。
5. 固定时间与时区测试数据。
6. 可配置 API Token 测试值。
7. 每个 App 独立 Settings。

测试不得依赖：

- 真实 AI API Key
- 真实 Home Assistant
- 真实设备状态
- 网络可用性
- 执行顺序
- 当前系统时间
- 项目根目录 `.env` 或开发者机器环境变量

构造测试 App 或 `Settings` 时必须显式使用 `Settings(_env_file=None, ...)` 注入完整测试配置；需要临时文件的写入路径也在测试目录内生成。禁止为了通过某个开发者机器而隐式读取根 `.env`。

## 单元测试

### 状态模型

必须测试：

- DeviceState 标准化。
- 未知状态映射。
- 设备在线状态。
- 环境上下文更新。
- 传感器单位转换。
- 区域聚合。

### 事件模型

必须测试：

- Event Schema 必填字段。
- payload 按 event_type 校验。
- occurred_at 与 created_at。
- correlation ID。
- 事件过滤条件。

### 规则引擎

只测试 Arvuno 需要的少量上下文规则，不测试通用场景编辑器能力。

必须测试：

- 触发条件匹配。
- 多条件 AND。
- 数值比较。
- 字符串比较。
- 冷却时间。
- 规则禁用。
- 高风险拒绝。
- 工具失败通知。
- 异常输入。

### 权限判断

必须测试：

- read_only 工具。
- low_risk 工具。
- medium_risk 需确认。
- high_risk 拒绝。
- 设备禁用。
- 动作不在白名单。
- 风险超过设备限制。
- 确认令牌有效、过期、重放。

### 工具参数验证

必须测试：

- 必填参数缺失。
- 类型错误。
- 枚举值非法。
- 数值越界。
- 未知设备。
- 未知动作。
- 额外字段处理。

### 任务状态

必须测试：

| 场景 | 期望 |
| --- | --- |
| 创建任务 | pending |
| 开始规划 | planning |
| 需要确认 | waiting_confirmation |
| 确认后 | running |
| 全部步骤成功 | completed |
| 任一关键步骤失败 | failed |
| 步骤超时或重启时结果未知 | needs_verification |
| 用户取消 | cancelled |
| 重复确认 | 冲突或幂等返回 |

### 记忆操作

必须测试：

- 写入。
- 检索。
- 更新。
- 删除。
- 未确认记忆过滤。
- 保留策略。
- 敏感内容拒写。

### 历史时间理解

必须测试：

- aware 时间进入 API，naive 时间拒绝。
- SQLite naive UTC 边界与用户本地时区边界一致。
- 采集、接收、处理时间分离，缺少采集时间时不伪造。
- 迟到和未来偏差保留原始时间并标记。
- 按预期采样周期显式报告缺失区间。
- 空间后代不重复包含自身。
- 趋势只使用有效数值，并暴露缺失范围。
- Observation、Event、Task 通过 correlation ID 关联，弱关联必须带警告。
- 快照差异区分设备投影候选、物理观测和未知恢复性。
- 物理观测不描述为真正的时光回滚。
- 自然语言历史回答返回真实记录引用；空数据时说明缺失范围。
- 未支持的自然语言模板返回确定性错误，不猜测。

## 集成测试

### 架构边界

使用静态 import 检查验证模块隔离：

1. Agent Runtime 不导入 Repository、SQLAlchemy 模型、数据库会话、Home Assistant HTTP 客户端或 Device Adapter。
2. Tool System 不拼接直接 SQL，不导入 Home Assistant HTTP 客户端。
3. Device Tool Handler 只依赖 Device Application Service。
4. AI Provider 不导入数据库、Device Adapter 或任务状态对象。
5. 前端代码不直接调用 Home Assistant API。

### Home Assistant Adapter

使用模拟 HTTP/WebSocket 响应测试：

1. 健康检查成功。
2. Token 无效。
3. URL 无法访问。
4. 配置范围过滤和轻量设备投影同步。
5. 单设备状态查询。
6. 状态标准化。
7. 实体类型映射。
8. 动作映射。
9. 设备 unavailable。
10. 请求超时。
11. 服务调用失败。
12. 事件转换。

### AI Provider

使用 Mock Provider 测试：

1. 正常结构化输出。
2. 非法 JSON。
3. Schema 校验失败。
4. 工具不存在。
5. 参数非法。
6. 超时。
7. HTTP 429。
8. HTTP 401。
9. API Key 缺失。
10. 调用日志脱敏。

### Tool Executor

测试链路：

1. 只读工具成功。
2. 设备控制工具成功。
3. 权限拒绝。
4. 高风险拒绝。
5. 需要确认。
6. 设备离线。
7. 设备动作失败。
8. 状态验证失败。
9. 数据库写入失败。
10. 工具日志生成。

### 数据库

测试：

1. Alembic 迁移可执行。
2. 回滚脚本可执行。
3. 唯一约束。
4. 外键约束。
5. JSON 字段校验由应用层保证。
6. 分页查询。
7. 时间排序。
8. 备份与恢复。

### API

测试：

1. 认证失败。
2. 参数校验。
3. 正常 CRUD。
4. 分页。
5. 错误结构。
6. correlation ID。
7. WebSocket 订阅。
8. 幂等键。

### 自动化与通知

使用 Mock 事件和 Mock 设备测试：

1. 条件命中后生成通知和执行记录。
2. 条件不满足只记录 `condition_not_met`。
3. 禁用规则不执行、不产生通知。
4. 冷却期内重复触发记录 `cooldown_skipped`。
5. 并发重复触发按规则串行处理。
6. 低风险工具动作通过 Task System、TaskStep、Tool Executor 和 Safety Policy 执行。
7. 工具或任务失败记录 `failed` 并生成任务失败通知。
8. 中高风险动作在任务创建前记录 `risk_rejected`。
9. 自动化、事件、任务、工具执行和通知可通过 correlation ID 或关联 ID 追踪。

### REPAIR-01 安全与数据治理回归

以下当前回归必须保持通过；它们是安全边界的最低门槛，不是覆盖率上限。

#### 机器人执行锁

- 直接 `POST /api/robots/{robot_id}/enable` 拒绝且不调用 `RobotApplicationService` 执行物理动作。
- 直接创建、确认和取消机器人任务请求返回 `ROBOT_EXECUTION_LOCKED`。
- `POST /api/robot-perception/requests/{request_id}/execute` 拒绝，移动观察不再直接创建机器人任务。
- Mock 机器人状态、能力、授权、治理、事件、任务历史、心跳和重连查询 / 遥测接口保持可用。

#### Provider Log 隐私

- 普通请求持久化元数据，不落库完整 messages、system prompt 或完整模型响应。
- API Key、Token、密码、摄像头和麦克风媒体内容脱敏或不入日志。
- Debug 捕获默认关闭；仅 development 可显式开启，TTL 为 60 到 3600 秒，读取和清理会移除过期捕获。
- 旧全文日志通过迁移 `c9d5e7f8a9b0` 脱敏为不可恢复的占位元数据，迁移和测试不得打印用户内容。
- 日志查询只返回 Schema v2 允许字段。

#### Retention Scheduler

- Event、Observation、Multimodal、Proactive、Environment Snapshot 和 Provider Log 独立启用、独立周期和独立批次。
- 超期数据被删除，未超期数据保留；重复执行保持幂等。
- 清理失败写入 `retention_runs`，应用退出将运行标记为取消，重启后可按新周期执行。
- 媒体过期时同时处理数据库记录和 `data/media/multimodal` 文件；孤立引用显式暴露。
- 备份恢复测试区分 SQLite 元数据恢复、媒体文件恢复和整体一致性。
- 可注入时钟推进调度，不使用长时间 sleep 等待真实过期。

#### 设备可用性状态机

- ONLINE 到 UNAVAILABLE 发布一次不可用事件；UNAVAILABLE 到 UNAVAILABLE 不重复发布。
- UNAVAILABLE 到 ONLINE 发布恢复事件；恢复后再不可用允许发布新事件。
- 单设备离线、读取超时、认证失败、网络错误、实体 unavailable 和 Adapter 整体断线保留区分。
- Adapter 异常更新可用性投影、错误分类和最近成功时间，保留最后一次可信观测。
- 迟到事件按版本和状态语义处理，不覆盖更新的有效状态。
- 应用重启后可重建状态，连续异常不导致 Automation、Proactive、Notification 或 Snapshot 重复触发。

#### EventBus 与 Task 可靠性

- 慢订阅者有明确超时，不无限阻塞设备轮询。
- 单个订阅者异常被隔离，不影响后续订阅者和事件持久化。
- 等待确认任务自动超时，应用重启后不把未确认或结果未知任务伪装为完成。
- 设备执行结果未知保留 `needs_verification` 或对应 UNKNOWN 状态。
- 取消请求、停止中、已取消、取消失败和执行状态未知分开表达。
- 恢复后的任务有重复执行防护；Automation Run 能在确认或拒绝后获得最终结果。

#### Robot Profile 与安全链

- `desktop_robot` 只包含报告状态、看目标、场景观察、安全停止、待机姿态、说话和按需听的能力。
- `mobile_robot` 保留 `navigate_to`、`return_to_dock`、`charge` 等接口但治理锁定；`legacy_mock_mobile` 仅限显式测试配置。
- Adapter 发现不覆盖用户 enabled / approved / Consent 状态；`executable` 是派生结果。
- 无 Consent、过期 Consent、撤销 Consent 和空间不匹配分别拒绝。
- 确认 Token 缺失、过期、重复使用、参数改变或任务不匹配拒绝；`confirmed=true` 不能绕过确认。
- 高风险动作默认拒绝；执行失败和状态验证失败不报告成功。
- Robot Task、Tool Execution、Task Step、robot_request_id 和 correlation ID 可审计关联。

#### Robot 失效安全与管理界面

- 运行状态覆盖 online、offline、stale、busy、idle、error、emergency_stopped 和 unknown。
- 心跳更新 `last_seen_at` 和 freshness；过期状态不作为实时状态交给 Planner。
- 安全停止请求有真实 Adapter / Mock 反馈，不宣称硬件急停已实测。
- 取消失败保留 `cancel_failed` 或 `execution_state_unknown`，不伪造成 `cancelled`。
- Web Console 机器人页覆盖列表、运行状态、能力启停、Consent、任务、事件、安全状态和故障信息。
- Agent 只读工具覆盖状态、能力、任务历史和授权状态，不直接访问 Robot Adapter。

## Mock Device Adapter

Mock Adapter 是第一阶段的必需组件，不只是测试工具。

### 内置设备

| 设备 | 类型 | 支持动作 |
| --- | --- | --- |
| 虚拟客厅灯 | light | turn_on、turn_off、set_brightness |
| 虚拟插座 | switch | turn_on、turn_off |
| 虚拟温度传感器 | sensor_temperature | 只读 |
| 虚拟湿度传感器 | sensor_humidity | 只读 |
| 虚拟人体传感器 | sensor_motion | 只读 |
| 虚拟门磁 | sensor_contact | 只读 |

### 可模拟故障

- 设备离线
- 请求超时
- 动作失败
- 状态验证失败
- 事件延迟
- 事件风暴

### 用途

1. 单元测试。
2. 集成测试。
3. 前端开发。
4. 无真实设备演示。
5. 安全测试。

## 安全测试

| 场景 | 输入 | 期望 |
| --- | --- | --- |
| 未授权 API | 无 Token | 401 |
| 未授权设备 | 修改其他设备 | 403 |
| 禁用设备 | 设备 enabled=false | 拒绝 |
| 非法工具参数 | action 不存在 | 422 |
| 伪造工具 | tool_name 不存在 | 拒绝 |
| 高风险动作 | 门锁 unlock | 默认拒绝 |
| 未确认 medium risk | 不提交确认 | waiting_confirmation |
| 确认令牌重放 | 使用两次 | 第二次拒绝 |
| AI 输出注入 | 设备名包含“忽略规则” | 不改变权限 |
| 设备离线 | state=unavailable | 不执行 |
| 执行超时 | Mock 延迟 | 失败并验证状态 |
| API Key 缺失 | 环境变量为空 | 启动或调用失败，不泄漏密钥 |
| 机器人直接 API 写操作 | create / confirm / cancel / enable | `ROBOT_EXECUTION_LOCKED` |
| 机器人确认伪造 | `confirmed=true`，无服务端 Token | 拒绝 |
| 机器人 Consent 缺失 / 过期 / 撤销 / 空间不符 | 执行前检查 | 拒绝 |
| 机器人参数改变后重放确认 Token | 参数摘要不匹配 | 拒绝 |
| 机器人移动 / 充电能力 | desktop 或未审批 mobile | 不出现在可执行目录或拒绝 |

## 验收测试

### A1. 服务启动

**步骤：**

1. 配置 `.env`。
2. 启动后端。
3. 访问 `/health`。

**通过条件：**

- 返回 `ok`。
- 数据库可连接。
- 适配器状态可报告。
- 无未捕获启动异常。

### A2. 前端访问后端

**步骤：**

1. 启动前端。
2. 登录。
3. 打开系统概览。

**通过条件：**

- 页面正常渲染。
- API 请求成功。
- 错误状态可控。

### A3. 连接 Home Assistant

**步骤：**

1. 配置 URL 和 Token。
2. 触发设备同步。

**通过条件：**

- 只导入配置范围内的设备。
- 设备类型映射正确。
- 错误信息明确。

### A4. 读取设备状态

**步骤：**

1. 查询设备列表。
2. 查询任一设备详情。

**通过条件：**

- 状态与 Home Assistant 一致。
- 时间字段有效。
- unavailable 状态正确处理。

### A5. 记录设备事件

**步骤：**

1. 修改一个真实或 Mock 设备状态。
2. 查看事件时间线。

**通过条件：**

- `device_state_changed` 事件生成。
- 事件持久化。
- 前端刷新后仍存在。

### A6. AI 查询设备

**步骤：**

1. 在对话页询问“现在有哪些灯开着”。
2. 等待 Agent 返回。

**通过条件：**

- 意图识别正确。
- 调用只读工具。
- 回答基于真实状态。
- 工具调用有记录。

### A7. 控制低风险设备

**步骤：**

1. 输入“打开客厅灯”。
2. 等待任务完成。

**通过条件：**

- Safety Policy 允许 low_risk。
- 设备实际状态改变。
- 任务状态 completed。
- 验证结果为 true。

### A8. 设备异常报告

**步骤：**

1. 将设备设为离线或模拟离线。
2. 尝试控制设备。

**通过条件：**

- 不显示成功。
- 返回设备不可用错误。
- 任务失败记录完整。

## 覆盖率要求

第一阶段建议最低目标：

| 模块 | 覆盖重点 |
| --- | --- |
| Safety Policy | 必须高覆盖 |
| Tool Executor | 必须高覆盖 |
| Task State Machine | 必须高覆盖 |
| Automation Run State | 必须高覆盖 |
| Event Schema | 必须高覆盖 |
| Device Adapter | 错误场景必须覆盖 |
| Memory | 授权和删除必须覆盖 |
| API | 核心路径必须覆盖 |

覆盖率低于目标不是立即失败，但必须说明原因和风险。

## 测试执行策略

工程初始化后建议分层命令：

```text
pytest                    # 单元 + 集成
pytest -m security       # 安全测试
pytest -m acceptance     # 验收测试
npm run type-check       # 前端类型检查
npm run build            # 前端构建
```

具体命令以后续工程实际脚本为准。

当前统一检查：

```powershell
.venv\Scripts\python.exe -m pytest backend -q
.venv\Scripts\python.exe -m ruff check backend
.venv\Scripts\python.exe -m ruff format --check backend
.venv\Scripts\python.exe -m compileall -q backend
cd frontend
pnpm typecheck
pnpm format:check
pnpm test
pnpm build
cd ..
```

## 测试数据管理

1. 不使用真实 API Key。
2. 不使用真实家庭地址。
3. 不使用真实个人敏感信息。
4. 设备名可使用测试名称。
5. 时间使用固定 UTC 时间。
6. 数据库每个测试独立创建和销毁。
7. 不读取根目录 `.env`；`Settings` 必须使用 `_env_file=None` 注入。
8. 迁移测试使用隔离临时数据库，不连接用户日常数据库。
9. 多模态媒体写入测试专用临时目录。
10. Provider Log 测试断言敏感明文不存在，不将用户内容写入日志或报告。

## 测试结论

第一阶段必须在实现真实设备控制之前完成：

1. Mock Device Adapter。
2. Safety Policy 测试。
3. Tool Executor 测试。
4. Task 状态机测试。
5. AI Provider Mock。

没有这些测试，不应开放真实 Home Assistant 写操作。
