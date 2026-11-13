# Arvuno Core 开发规范

本文档约束 Arvuno Core 的长期开发方式。除非用户明确要求改变，否则后续开发和文档更新都应遵循这些规则。

## 项目边界

Arvuno Core 是个人 AI 环境感知与智能控制系统，核心价值是环境理解、任务规划、受控执行、结果验证和长期记忆。

### 当前方向

- AI Agent
- 环境状态模型
- 事件系统
- 长期记忆
- 任务规划
- 工具执行
- Home Assistant 接入
- 自动化规则
- 执行验证
- Web 控制台

### 禁止方向

以下内容不允许作为当前产品规划或默认实现：

- 老人监护、老人异常检测、养老服务、老人安全告警、老人远程照护
- 自研 Zigbee、Matter 或其他智能家居协议栈
- 自研机器人硬件
- 完整视频监控系统
- 完整智能家居设备管理平台
- 多租户商业 SaaS
- 插件市场
- 多 Agent 协作框架
- 高风险自主设备控制
- 复杂视觉模型
- 大规模分布式系统

未来扩展只能以接口和文档设计的形式预留，不能提前实现复杂功能。

## 架构原则

1. 采用模块化单体架构，第一阶段所有核心模块运行在同一个后端进程中。
2. 不使用微服务、Kubernetes、Kafka、RabbitMQ 或其他高运维成本基础设施。
3. Home Assistant 是设备接入基础设施，不是 Arvuno Core 的核心领域模型。
4. AI 模型不能直接访问数据库、执行系统命令或调用设备适配器。
5. 所有设备操作必须通过 Tool Registry、Safety Policy 和 Tool Executor。
6. Agent 负责理解和规划，Tool Executor 负责校验、授权、执行和验证。
7. Device Registry 只保存 Arvuno 需要的设备投影、别名和权限，不复制 Home Assistant 的设备管理、设备发现或协议适配能力。
8. Event System 只保存 Arvuno 的上下文、任务、审计和自动化所需事件，不复制 Home Assistant 的完整历史库。
9. 简单设备自动化优先使用 Home Assistant；Arvuno 自动化只做需要 AI 上下文、任务记录或多设备编排的场景。
10. Agent Runtime 不得导入 Repository、SQLAlchemy 模型、Home Assistant HTTP 客户端或设备 Adapter。
11. 事件系统第一阶段使用应用内事件总线，事件必须持久化。
12. 数据访问必须经过仓储或清晰的 Repository 边界，业务逻辑不能直接依赖 SQLite 特有能力。
13. 配置必须通过环境变量或本地配置文件管理，禁止在源码中写入 API Key。
14. 优先使用成熟、低成本、可在 Windows 本地运行的技术。
15. 当前只允许 Mock 桌面机器人状态、能力、授权和治理查询，以及经 Agent → Task System → Tool Registry → Safety Policy → Tool Executor 的受控执行链路。真实机器人物理执行、移动能力和 `legacy_mock_mobile` 执行保持锁定；Robot API 不提供物理动作入口。

## 后端规范

- 使用 Python 类型标注。
- 使用 Pydantic 定义输入、输出和领域模型。
- I/O 操作使用异步接口。
- API 路由只做协议转换、参数校验和响应封装，不承载业务逻辑。
- 业务逻辑放在服务层或领域模块中。
- 数据库访问放在 Persistence Layer。
- 统一错误类型、错误码和日志字段。
- 避免全局可变状态，依赖通过明确的构造函数或依赖注入传入。
- 所有外部调用必须有超时、异常处理和日志。

## 前端规范

- 使用 TypeScript，禁止把 API 数据长期保存在弱类型的 `any` 中。
- API 请求统一封装，页面组件不直接散落请求细节。
- API 类型与后端接口文档保持一致。
- 状态管理保持简单，优先使用 TanStack Query 管理服务端状态。
- 组件职责清晰，避免把所有逻辑写在单个页面组件中。
- 错误、加载和空状态必须显式处理。
- Web 控制台定位是 Arvuno Core 的运行与观测界面，不是 Home Assistant Dashboard。

## 安全规范

1. 每个工具必须声明风险等级和默认权限。
2. 高风险工具默认禁止执行，必须显式开启并要求用户确认。
3. AI 输出只能作为待验证的候选计划，不能直接作为可信执行指令。
4. 工具参数必须通过 Pydantic 或等价 Schema 校验。
5. 设备控制必须经过设备权限检查、风险检查、执行日志和结果验证。
6. 第一阶段禁止未经确认的门锁控制、高风险设备控制、任意系统命令执行、任意文件删除和任意网络访问。
7. 敏感配置不得提交到仓库。

## 测试规范

- 核心状态模型、事件模型、权限判断、任务状态机和工具参数校验必须有单元测试。
- Home Assistant Adapter、AI Provider、Tool Executor 和 API 必须通过可替换的模拟实现测试。
- 必须提供 Mock Device Adapter，使没有真实设备时也能验证控制流程。
- 安全场景必须覆盖未授权设备控制、非法参数、高风险动作、AI 返回错误工具调用、设备离线、执行超时和 API Key 缺失。
- 每个开发阶段完成前必须运行该阶段验收测试。

## 协作流程

1. 修改前先阅读相关文档和代码，不覆盖已有工作。
2. 涉及架构、数据模型、安全边界或公共接口的变更，必须同步更新文档。
3. 新功能先确认边界，再实现最小可用版本。
4. 不做无关重构，不引入当前阶段用不到的依赖。
5. 每个阶段结束时检查是否符合路线图验收标准。

## 当前阶段约束

架构已确认，Phase 0–9 已完成，Phase 10 / 第一阶段 demo 验收已完成；真实模型、真实 Home Assistant demo 读/写链路、断线/重连、Web Console 逐页与移动端复核均已通过，实体硬件验收不包含在该结论内，结果见 `docs/16-phase10-acceptance-report.md`。仓库 Phase 0–10 与长期 `ARS-02` 至 `ARS-06` 编号独立；历史验收结论不改写，ARS 阶段不因维护修复自动关闭。

REPAIR-01 维护修复和软件能力补齐已完成并通过全量回归（后端 502 tests），但仍在等待用户复核后自行提交。本轮新增 Privacy Erasure 编排、Memory 压缩与知识提炼、工具执行自动 Procedure Validation（migration `9c0d1e2f3a4b`）、Reasoning AI 候选生成、多步 Planning、Proactive L3、Active Perception 受控集成、Multimodal Provider 契约、Robot 固件协议契约与 Simulator，以及 Retention/History/State Estimates/Reasoning/Planning/Proactive/Active Perception/Multimodal 前端管理页。交付边界与测试结果见 `docs/39-software-delivery-acceptance-report.md`。

当前仓库允许维护 FastAPI/React 基础骨架、健康检查、配置、SQLite 数据模型、Alembic 迁移、Repository 边界、备份与多模态媒体备份、统一设备接口、Home Assistant Adapter、Mock Device Adapter、轻量 Device Registry、后台状态轮询、设备可用性状态投影、标准 Event Schema、带订阅者隔离的进程内 Event Bus、事件持久化、事件查询 API、Environment Context、Memory、AI Provider、最小化 Provider Log、Agent Runtime、Robot Profile 与能力治理、Mock 桌面机器人、Web Console、保留策略调度、少量 Arvuno 上下文自动化、任务恢复、测试、格式化、CI、依赖锁定、环境变量示例和 Windows 启动配置。

真实 Home Assistant 写操作必须保持默认关闭。任务步骤必须通过 Tool Executor 执行；AI 输出只能是候选意图和计划；自动化工具动作必须通过 Task System 和 Tool Executor 执行，且只允许 read_only 或 low_risk 自动执行；前端只能访问 Arvuno API。默认 Provider Log 只保存运行元数据，完整请求/响应调试日志默认关闭且只允许 development 短期开启；测试不得隐式读取根目录 `.env`。未经真实硬件安全审批，不得开放真实机器人物理运动或 `mobile_robot` 治理；机器人动作必须通过统一安全执行链，确认只能使用服务端一次性 Token，不接受客户端 `confirmed=true` 作为绕过通道。环境上下文必须从 Device Registry 投影并在验证成功后同步；自身控制不得发布 `device_state_changed`。

## 命名规范

项目英文名为 Arvuno，产品标识为 Arvuno Core。后端 Python 包使用 `arvuno_core`，环境变量使用 `ARVUNO_` 前缀，前端包名为 `arvuno-frontend`。当前仓库物理目录和 Git 远程名称不因产品改名自动调整；旧 Nova 数据文件和环境变量不会被自动迁移。
