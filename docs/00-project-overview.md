# 00. 项目概览

## 项目状态

| 项目 | 状态 |
| --- | --- |
| 项目目录 | `E:\williamzhang\zzh\zzh-personal-project\nova` |
| 当前阶段 | Phase 6 任务系统已完成（待用户验收） |
| 代码状态 | 前后端骨架、健康检查、数据模型、迁移、Repository、备份恢复、统一设备接口、Home Assistant Adapter、Mock Adapter、轻量 Device Registry、状态轮询、Event Schema、进程内 Event Bus、事件查询 API、Environment Context、Tool Registry、Safety Policy、用户确认、Tool Executor、执行审计、状态验证、Task/TaskStep 状态机、任务执行、历史查询与任务事件已初始化 |
| 架构确认 | 已确认 |
| 第一阶段运行环境 | Windows 11 本地 |

本文档集是 Nova Core 的架构基线。架构已获得确认，Phase 6 已完成任务系统代码；自动化测试使用 Home Assistant 模拟响应、Mock Device Adapter 和显式任务计划，尚未连接真实 Home Assistant，也不包含 AI Provider、Agent Runtime、自动化引擎、通知系统或业务功能。

## 项目背景

Nova Core 是一个运行在个人 Windows 电脑上的 AI 环境感知与智能控制系统。它通过智能家居设备、传感器和外部 API 获取现实世界信息，建立自己的环境上下文，接收用户目标，调用 AI 模型进行推理和规划，再通过受控工具执行任务并验证结果。

项目的长期方向是成为能够感知环境、建立长期记忆、理解用户意图、规划任务、调用设备并验证执行结果的个人 AI 系统。第一阶段不追求覆盖所有未来能力，而是完成一条完整闭环：

```text
获取真实环境信息
→ 理解目标
→ 生成计划
→ 调用设备
→ 验证结果
→ 记录执行过程
```

## 第一阶段目标

Nova Core 第一阶段需要逐步具备以下能力：

1. 接入 Home Assistant。
2. 查询设备列表。
3. 查询设备当前状态。
4. 获取设备状态变化事件。
5. 建立 Nova 自己的环境上下文。
6. 保存设备事件和任务记录。
7. 通过自然语言理解用户意图。
8. 调用受控工具。
9. 控制一个低风险设备。
10. 验证实际设备状态。
11. 记录任务执行结果。
12. 提供 Web 控制台。
13. 提供少量 Nova 上下文自动化和通知能力。
14. 支持后续接入更多设备。

## 当前产品边界

### 属于 Nova Core

- AI Agent Runtime
- 环境状态模型
- 事件系统
- 长期记忆
- 任务规划与任务记录
- 工具注册与安全执行
- 设备权限控制
- 多设备任务编排
- 执行结果验证
- 自动化规则
- 用户偏好理解
- Web 控制台

### 不属于 Nova Core

- 完整复刻 Home Assistant
- 自研智能家居协议栈
- 完整设备管理平台
- 完整视频监控系统
- 多租户商业 SaaS
- 插件市场
- 高风险自主控制
- 复杂机器人系统

### 明确取消的方向

老人监护、老人异常检测、养老服务、老人安全告警、老人远程照护及相关商业服务已经取消，不得作为 Nova Core 的当前产品规划。

## 文档结构

| 文档 | 内容 |
| --- | --- |
| [00-project-overview.md](00-project-overview.md) | 项目背景、目标、边界和文档结构 |
| [01-product-definition.md](01-product-definition.md) | 产品定位、用户价值、场景和验收目标 |
| [02-system-architecture.md](02-system-architecture.md) | 总体架构、运行方式、关键流程和边界 |
| [03-module-responsibilities.md](03-module-responsibilities.md) | 模块职责、输入输出、依赖和测试方式 |
| [04-technology-stack.md](04-technology-stack.md) | 技术选型分析和最终建议 |
| [05-data-model.md](05-data-model.md) | 数据表、字段、关系和迁移原则 |
| [06-api-design.md](06-api-design.md) | REST API、WebSocket 和错误规范 |
| [07-device-adapter-design.md](07-device-adapter-design.md) | 设备抽象、Home Assistant 适配和模拟设备 |
| [08-event-system-design.md](08-event-system-design.md) | 事件格式、总线、持久化和订阅机制 |
| [09-agent-and-tool-design.md](09-agent-and-tool-design.md) | Agent、工具、任务规划和安全执行 |
| [10-memory-system-design.md](10-memory-system-design.md) | 记忆类型、保存策略和隐私边界 |
| [11-security-and-permissions.md](11-security-and-permissions.md) | 风险等级、权限、确认和威胁模型 |
| [12-testing-strategy.md](12-testing-strategy.md) | 单元、集成、安全、模拟和验收测试 |
| [13-development-roadmap.md](13-development-roadmap.md) | 分阶段开发计划和验收标准 |
| [14-decisions-and-tradeoffs.md](14-decisions-and-tradeoffs.md) | 关键架构决策和取舍 |
| [15-future-extension.md](15-future-extension.md) | 未来扩展接口与不提前实现的内容 |

## 核心术语

| 术语 | 定义 |
| --- | --- |
| Environment Context | Nova 对当前环境、设备、传感器、用户目标和最近事件的结构化理解 |
| Device Adapter | 将 Home Assistant 或其他设备平台转换为 Nova 统一设备接口的适配层 |
| Device Registry | Nova 内部的轻量设备投影、能力摘要、别名和权限映射 |
| Tool | Agent 可调用的受控能力，例如查询设备、查询环境状态或控制设备 |
| Tool Registry | 工具元数据和 Schema 的注册中心 |
| Tool Executor | 负责参数校验、权限检查、风险检查、执行和验证的组件 |
| Task | Nova 中的多步骤执行单元，包含计划、状态、结果和错误 |
| Event | 系统内可持久化的状态变化或执行事实 |
| Memory | 结构化保存的短期上下文、用户偏好、任务经验和长期记忆 |
| Provider | AI 模型供应商适配层 |

## 当前结论

Nova Core 应采用 Windows 本地运行的模块化单体架构。第一阶段以 Home Assistant 作为唯一真实设备接入平台，以 SQLite 作为本地数据库，以 FastAPI 和 React 构建系统，并在架构上保持设备适配层、事件系统、任务系统、工具执行和安全策略的独立边界。

架构收敛规则：

1. Home Assistant 继续负责设备集成、发现、协议适配、完整设备历史和基础自动化。
2. Nova 只保存设备投影、上下文事件、任务审计和用户偏好，不复制 Home Assistant 的平台能力。
3. Agent 只产生候选意图和计划，不接触数据库实现、SQL 或设备协议客户端。
4. 机器人只在 [15-future-extension.md](15-future-extension.md) 中作为远期方向记录，当前模块清单和接口设计中没有机器人模块。

Phase 6 完成后等待用户验收。真实 Home Assistant 写操作保持默认关闭；未经用户确认，不应进入 Phase 7 AI Agent 或后续业务功能开发。
