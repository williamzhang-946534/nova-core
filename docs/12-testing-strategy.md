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

测试不得依赖：

- 真实 AI API Key
- 真实 Home Assistant
- 真实设备状态
- 网络可用性
- 执行顺序
- 当前系统时间

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
| 用户取消 | cancelled |
| 步骤超时 | failed |
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

## 测试数据管理

1. 不使用真实 API Key。
2. 不使用真实家庭地址。
3. 不使用真实个人敏感信息。
4. 设备名可使用测试名称。
5. 时间使用固定 UTC 时间。
6. 数据库每个测试独立创建和销毁。

## 测试结论

第一阶段必须在实现真实设备控制之前完成：

1. Mock Device Adapter。
2. Safety Policy 测试。
3. Tool Executor 测试。
4. Task 状态机测试。
5. AI Provider Mock。

没有这些测试，不应开放真实 Home Assistant 写操作。
