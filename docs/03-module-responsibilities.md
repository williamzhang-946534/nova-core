# 03. 模块职责

## 模块调整说明

原设计建议中的 API Gateway 在第一阶段改名为 **API Layer**。当前系统只有一个后端进程和一组前端用户，不需要独立网关。API Layer 只负责协议转换、认证、参数校验、错误封装和 OpenAPI 文档。

Device Adapter 与 Device Registry 合并为 **Device Integration** 域，但内部保留独立接口。适配器负责外部平台通信，注册表只保存 Nova 需要的设备投影、别名、能力摘要和权限，不复制 Home Assistant 的设备管理平台。

Task Planner 不作为完全独立的通用规划引擎，而是 **Task System** 中的规划组件。第一阶段只需要简单单步或多步计划。

Logging 与 Scheduler 不作为业务模块单独实现，而是横切能力：

- Logging 由统一的日志基础设施提供。
- Scheduler 由轻量后台任务调度器提供，用于健康检查、设备刷新和自动化评估。

当前模块清单不包含机器人、语音、视觉或多 Agent 模块。机器人只在远期扩展文档中记录，进入开发前必须先补充独立安全设计和架构决策。

## 模块清单

| 模块 | 核心问题 | 阶段 |
| --- | --- | --- |
| API Layer | 对外提供稳定 HTTP/WebSocket 接口 | 第一阶段 |
| Device Integration | 屏蔽设备平台差异，提供统一设备接口 | 第一阶段 |
| Device Registry | 保存轻量设备投影、能力摘要、别名和权限映射 | 第一阶段 |
| Environment Context | 维护 Nova 自己的环境状态 | 第一阶段 |
| Event System | 统一事件表示、分发和持久化 | 第一阶段 |
| Memory System | 管理短期上下文、偏好和长期记忆 | 第一阶段基础版 |
| AI Provider | 隔离模型供应商差异 | 第一阶段 |
| Agent Runtime | 理解意图、选择工具、生成回答 | 第一阶段 |
| Task System | 管理任务、计划、状态和历史 | 第一阶段 |
| Tool System | 注册工具、校验参数、安全执行 | 第一阶段 |
| Safety Policy | 权限、风险和确认策略 | 第一阶段 |
| Automation Engine | 只处理需要 Nova 上下文的少量通知型或确认后低风险自动化 | 第一阶段基础版 |
| Persistence Layer | 提供数据访问边界 | 第一阶段 |
| Observability | 日志、健康检查和调用追踪 | 第一阶段基础版 |
| Scheduler | 定时任务和后台刷新 | 第一阶段基础版 |
| Notification | 向用户输出提醒 | 第一阶段基础版 |
| Frontend Dashboard | 提供控制和观测界面 | 第一阶段 |

## 1. API Layer

**解决什么问题：**

为 Web 控制台和未来客户端提供稳定、可文档化、可测试的 HTTP 和 WebSocket 接口。

**为什么需要：**

前端不应直接访问数据库或后端内部对象，外部访问必须经过统一认证、校验和错误封装。

**输入：**

- HTTP 请求
- WebSocket 连接
- 认证 Token
- API 请求 Schema

**输出：**

- 标准 JSON 响应
- WebSocket 消息
- OpenAPI 文档
- 标准错误结构

**依赖：**

- Agent Runtime
- Device Integration
- Environment Context
- Event System
- Task System
- Automation Engine
- 配置与认证组件

**不负责：**

- 业务规则执行
- 直接调用 Home Assistant
- 直接读写数据库表
- AI 提示词构造
- 工具权限判断

**测试方式：**

- API 合同测试
- 认证失败测试
- 参数校验测试
- 错误码测试
- WebSocket 订阅测试

**未来扩展：**

- 多用户认证
- API Rate Limit
- 更细粒度权限
- 独立网关或反向代理

## 2. Device Integration

**解决什么问题：**

将 Home Assistant、未来 MQTT 或其他平台的设备能力转换为 Nova 的统一设备接口。

**为什么需要：**

避免 Agent 和业务模块被某个智能家居平台的 API、实体模型或错误格式绑定。

**输入：**

- Adapter 配置
- Home Assistant REST/WebSocket 响应
- 设备动作请求
- 事件订阅请求

**输出：**

- `Device`
- `DeviceState`
- `DeviceCapability`
- `DeviceAction`
- `DeviceEvent`
- `AdapterHealth`
- 统一错误

**依赖：**

- HTTP/WebSocket 客户端
- 配置系统
- 日志系统
- Device Adapter Interface

**不负责：**

- 用户意图理解
- 工具权限判断
- 任务编排
- 事件持久化
- 自动化规则判断

**测试方式：**

- Adapter 单元测试
- Home Assistant API 模拟测试
- 超时和离线测试
- 动作不支持测试
- Mock Device Adapter 集成测试

**未来扩展：**

- MQTT Adapter
- ESP32 自定义传感器 Adapter
- 多设备平台并行接入

## 3. Device Registry

**解决什么问题：**

为 Nova 提供稳定的轻量设备投影，屏蔽外部实体 ID 的变化，并附加 Nova 侧权限与别名。

**为什么需要：**

Agent 和任务系统应面向 Nova 的设备 ID、区域、类型和能力，而不是直接面向 Home Assistant entity_id。设备发现、协议适配、完整设备档案和完整设备历史继续由 Home Assistant 负责。

**输入：**

- Adapter 返回的设备列表
- 手动同步请求
- 设备别名和分组配置
- 权限配置

**输出：**

- 轻量设备投影
- 设备详情
- 能力描述
- 设备与平台实体映射
- 设备权限状态

**依赖：**

- Device Adapter Interface
- Persistence Layer
- Device Capability Model

**不负责：**

- 设备通信
- 实时状态订阅
- AI 意图理解
- 自动化规则判断

**测试方式：**

- 设备同步测试
- ID 映射稳定性测试
- 能力识别测试
- 设备禁用或删除测试
- 不复制 Home Assistant 管理字段的投影范围测试

**未来扩展：**

- 自定义别名
- 区域覆盖
- 多适配器投影合并

## 4. Environment Context

**解决什么问题：**

维护 Nova 对当前环境的结构化理解，而不是每次都重新拼接设备列表。

**为什么需要：**

Agent 需要一个稳定上下文来理解当前状态、最近事件、用户目标和任务状态。

**输入：**

- Device State
- Sensor Data
- Device Event
- User Goal
- User Preference
- Active Task
- Recent Events

**输出：**

- 环境快照
- 区域状态摘要
- 在线设备摘要
- 异常状态
- Agent 可用的上下文片段

**依赖：**

- Device Registry
- Event System
- Memory System
- Task System
- Persistence Layer

**不负责：**

- 长期历史查询
- 设备控制
- 事件持久化
- 模型调用

**测试方式：**

- 状态更新测试
- 事件触发更新测试
- 区域聚合测试
- 设备离线处理测试
- 上下文裁剪测试

**未来扩展：**

- 更复杂的空间模型
- 人 presence 状态
- 语音和视觉事件上下文
- 数字孪生模型

## 5. Event System

**解决什么问题：**

用统一格式记录和分发设备、任务、工具、自动化和用户确认事件。

**为什么需要：**

状态变化、自动化触发和任务执行需要可追溯，也需要支持后续传感器、语音和视觉事件。

**输入：**

- Device Adapter 事件
- Task 事件
- Tool Execution 事件
- Automation 事件
- 用户确认事件

**输出：**

- 标准 `NovaEvent`
- 事件订阅回调
- 事件时间线查询结果
- correlation ID 关联链

**依赖：**

- Persistence Layer
- Event Bus
- 日志系统

**不负责：**

- 业务决策
- 设备控制
- 数据库迁移
- 外部消息系统

**测试方式：**

- Event Schema 校验测试
- 发布订阅测试
- 事件持久化测试
- 订阅者异常隔离测试
- 时间线查询测试

**未来扩展：**

- 外部队列适配
- 事件回放
- 事件归档
- 更细粒度订阅过滤

## 6. Memory System

**解决什么问题：**

区分短期上下文、用户偏好、事件历史、任务经验和长期记忆。

**为什么需要：**

如果只保存聊天记录，Nova 无法形成可靠的用户偏好和执行经验，也无法清理无关数据。

**输入：**

- 对话上下文
- 用户确认的偏好
- 任务结果
- 事件摘要
- 用户授权设置

**输出：**

- 短期上下文
- 用户偏好
- 可检索记忆
- 任务经验摘要

**依赖：**

- Persistence Layer
- Task System
- Event System
- 用户授权配置

**不负责：**

- 保存所有聊天记录为长期记忆
- 未经授权采集敏感信息
- 直接控制设备

**测试方式：**

- 记忆写入与读取测试
- 保留策略测试
- 授权边界测试
- 上下文窗口裁剪测试

**未来扩展：**

- 向量检索
- 记忆重要性评分
- 用户可编辑记忆库

## 7. AI Provider

**解决什么问题：**

隔离具体模型供应商、接口格式、超时和错误差异。

**为什么需要：**

业务代码不应写死 GLM、OpenAI 或其他供应商，模型应可通过配置更换。

**输入：**

- Provider 配置
- 消息列表
- 结构化输出 Schema
- 工具定义
- 超时配置

**输出：**

- 模型响应
- 结构化输出
- 工具调用候选
- Token 与耗时统计
- Provider 错误

**依赖：**

- 配置系统
- HTTP 客户端
- 日志系统

**不负责：**

- 权限判断
- 设备调用
- 任务状态管理
- 数据库访问

**测试方式：**

- Provider Mock 测试
- 超时测试
- 错误映射测试
- 结构化输出校验测试
- API Key 缺失测试

**未来扩展：**

- 多 Provider 路由
- 本地模型
- 视觉模型
- 语音模型

## 8. Agent Runtime

**解决什么问题：**

理解用户意图，组织上下文，选择工具，处理工具结果，并向用户报告。

**为什么需要：**

需要一个明确的 AI 编排层，但不能让它直接拥有系统权限。

**输入：**

- 用户消息
- 对话历史
- Environment Context
- Tool Catalog 的只读投影
- 任务结果摘要

**输出：**

- 意图识别结果
- 候选任务计划
- 候选工具调用
- 用户回答
- 需要用户确认的信息

**依赖：**

- AI Provider
- Memory System
- Environment Context
- Task System
- Tool Catalog 的只读投影

**不负责：**

- 直接执行设备动作
- 直接访问数据库
- 导入 Repository、数据库模型或数据库会话
- 绕过权限校验
- 执行系统命令
- 直接调用 Tool Executor

**测试方式：**

- 意图解析测试
- 工具选择测试
- 参数候选校验测试
- 工具结果处理测试
- 拒绝越权请求测试

**未来扩展：**

- 多轮复杂规划
- 反思与重规划
- 工具组合优化

## 9. Task System

**解决什么问题：**

把一次用户目标或自动化触发变成可管理、可恢复、可审计的任务。

**为什么需要：**

一次性聊天响应无法承载多步骤执行、失败重试、状态验证和任务历史。

**输入：**

- 用户目标
- Agent 生成的计划
- 自动化触发
- 工具执行结果
- 取消或确认信号

**输出：**

- Task
- TaskStep
- 任务状态
- 任务结果
- 任务事件

**依赖：**

- Tool System
- Event System
- Persistence Layer
- Safety Policy

**不负责：**

- 模型调用细节
- 设备协议通信
- 权限规则定义

**测试方式：**

- 状态机测试
- 多步骤执行测试
- 失败与重试测试
- 超时与取消测试
- 历史查询测试

**未来扩展：**

- 任务恢复
- 任务模板
- 更复杂工作流
- 定时任务

## 10. Tool System

**解决什么问题：**

为 Agent 提供受控能力，并统一参数校验、权限检查、执行、日志和结果验证。

**为什么需要：**

AI 输出不可直接信任，设备操作必须进入统一执行链路。
Tool System 与 Agent 通过候选计划和结果摘要交互，不共享数据库对象。

**输入：**

- Tool ID
- 工具参数
- 用户身份
- 任务上下文
- 设备权限配置

**输出：**

- ToolExecutionRecord
- 执行结果
- 验证结果
- 标准错误

**依赖：**

- Tool Registry
- Safety Policy
- 相关领域服务，例如设备服务、环境服务、事件查询服务
- Persistence Repository

**不负责：**

- 意图理解
- 任务状态推进
- 模型供应商适配
- 直接拼 SQL 或导入数据库模型
- 绕过权限的特殊通道

**测试方式：**

- 参数校验测试
- 权限拒绝测试
- 高风险拒绝测试
- 设备离线测试
- 结果验证测试
- 执行日志测试

**未来扩展：**

- 更丰富的工具类型
- 工具版本管理
- 插件式注册
- 更复杂确认流程

## 11. Safety Policy

**解决什么问题：**

集中管理工具风险等级、设备权限、执行条件和用户确认策略。

**为什么需要：**

安全规则不能散落在工具实现中，也不能交给模型自行判断。

**输入：**

- Tool 定义
- 用户身份
- 设备类型
- 动作参数
- 当前环境状态
- 用户确认记录

**输出：**

- 允许、拒绝或要求确认
- 风险等级
- 拒绝原因
- 审计记录

**依赖：**

- Tool Registry
- Device Registry
- 配置系统

**不负责：**

- 模型调用
- 具体设备动作执行
- 事件存储

**测试方式：**

- 风险等级测试
- 未授权设备测试
- 高风险动作测试
- 用户确认测试
- 静默期测试

**未来扩展：**

- 更细粒度策略
- 操作白名单和黑名单
- 时间窗口限制
- 审计报表

## 12. Automation Engine

**解决什么问题：**

只处理需要 Nova 环境上下文、任务历史或用户偏好的少量自动化，第一阶段以通知为主，动作型自动化必须经过确认且限定为低风险。

**为什么需要：**

Home Assistant 已能覆盖普通定时、状态触发和场景自动化。Nova 只覆盖需要 AI 上下文或需要进入任务审计链路的场景。

**输入：**

- NovaEvent
- 自动化规则
- Environment Context
- 用户权限

**输出：**

- automation_triggered 事件
- 新任务
- 通知
- 规则执行记录

**依赖：**

- Event System
- Task System
- Safety Policy
- Notification
- Persistence Layer

**不负责：**

- 模型调用
- 设备协议细节
- 替代 Home Assistant 的全部自动化能力
- 通用自动化编辑器
- 场景管理系统

**测试方式：**

- 条件判断测试
- 事件触发测试
- 防抖测试
- 权限与风险测试
- 失败记录测试

**未来扩展：**

- 自然语言创建规则
- 规则模板，需重新审查是否重复 Home Assistant
- AI 辅助优化，需在基础闭环稳定后再评估

## 13. Persistence Layer

**解决什么问题：**

提供统一数据访问边界，隔离业务逻辑与数据库实现。

**为什么需要：**

第一阶段使用 SQLite，但未来可能迁移 PostgreSQL，业务代码不能依赖 SQLite 特有能力。

**输入：**

- 领域对象
- 查询条件
- 事务边界

**输出：**

- 持久化结果
- 查询结果
- 数据访问错误

**依赖：**

- SQLAlchemy
- Alembic
- 数据模型定义

**不负责：**

- 业务规则
- 设备通信
- API 协议转换

**测试方式：**

- Repository 单元测试
- SQLite 集成测试
- 迁移测试
- 备份与恢复测试

**未来扩展：**

- PostgreSQL 方言迁移
- 数据归档
- 读写分离

## 14. Observability

**解决什么问题：**

让个人开发者能够定位启动失败、设备离线、模型超时和任务失败。

**为什么需要：**

AI 系统链路长，缺少 correlation ID 和结构化日志时很难排查。

**输入：**

- 请求日志
- 模型调用日志
- 工具执行日志
- 设备适配器日志
- 任务状态变化

**输出：**

- 结构化日志
- 健康检查结果
- correlation ID
- 基础统计

**依赖：**

- API Layer
- Agent Runtime
- Tool System
- Device Integration
- Task System

**不负责：**
-复杂 APM
- 用户行为追踪
- 商业数据分析

**测试方式：**

- 日志字段测试
- correlation ID 贯穿测试
- 健康检查测试
- 敏感信息脱敏测试

**未来扩展：**

- 本地指标面板
- 事件回放
- 更完整 tracing

## 15. Scheduler

**解决什么问题：**

执行周期性任务，例如设备刷新、健康检查和自动化评估。

**为什么需要：**

有些状态不能只依赖事件推送，需要定期校验。

**输入：**

- 定时任务配置
- 事件触发
- 系统启动信号

**输出：**

- 后台任务执行结果
- 健康检查事件
- 刷新任务

**依赖：**

- Device Integration
- Automation Engine
- Observability

**不负责：**

- 复杂分布式任务队列
- 重型批处理

**测试方式：**

- 调度触发测试
- 异常隔离测试
- 重复执行防护测试

**未来扩展：**

- 持久化任务队列
- 延迟任务
- 重试策略

## 16. Notification

**解决什么问题：**

在任务完成、失败、自动化触发或环境异常时提醒用户。

**为什么需要：**

用户不一定始终打开控制台，需要基础提醒能力。

**输入：**

- 任务事件
- 自动化事件
- 设备异常
- 用户通知偏好

**输出：**

- Web 控制台通知
- 未来邮件、手机或其他通知

**依赖：**

- Event System
- 配置系统
- Web 控制台

**不负责：**

- 任务执行
- 自动化规则判断
- 保存业务事件

**测试方式：**

- 通知生成测试
- 通知偏好测试
- 发送失败测试

**未来扩展：**

- 邮件
- 企业微信
- 手机推送

## 17. Frontend Dashboard

**解决什么问题：**

提供 Nova 的运行状态、设备、事件、对话、任务和自动化观测界面。

**为什么需要：**

个人系统需要可视化控制台，而不是只能通过日志或 API 操作。

**输入：**

- 后端 API
- WebSocket 事件
- 用户操作

**输出：**

- 系统概览
- 设备列表和详情
- 环境状态
- 事件时间线
- AI 对话
- 任务执行记录
- 自动化规则页面
- 设置页面

**依赖：**

- API Layer
- Authentication
- API 类型定义

**不负责：**

- 直接访问 Home Assistant
- 直接访问数据库
- 业务规则判断

**测试方式：**

- 页面渲染测试
- API 类型一致性测试
- 错误与空状态测试
- 关键用户流程测试

**未来扩展：**

- 更丰富的图表
- 移动端适配
- 语音交互界面

## 模块依赖规则

```text
Frontend
  → API Layer
    → Agent Runtime / Task System / Automation / Environment / Device API
      → Tool System
        → Safety Policy
          → Device Application Service
              → Device Adapter Interface
                  → Home Assistant / Mock Adapter
      → AI Provider
      → Memory System
    → Application Service
      → Repository
        → SQLAlchemy Models
```

禁止以下依赖：

- Agent Runtime → Home Assistant HTTP Client
- Agent Runtime → Repository / SQLAlchemy Model / Database Session
- Tool Executor → 直接 SQL
- Tool Handler → Home Assistant HTTP Client
- Frontend → Home Assistant API
- API Route → 直接设备协议调用
- AI Provider → 数据库写入

## 模块优先级结论

第一阶段必须先完成：

1. API Layer 的基础骨架
2. Persistence Layer 与数据模型
3. Device Adapter Interface
4. Home Assistant Adapter
5. Device Registry
6. Event System
7. Environment Context
8. Tool Registry / Safety Policy / Tool Executor
9. Task System
10. AI Provider
11. Agent Runtime

可以后置：

- Automation Engine 的复杂规则
- Notification 的多渠道发送
- Memory System 的长期检索
- Frontend 的高级可视化
