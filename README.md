# Arvuno Core

Arvuno Core 是一个运行在个人 Windows 电脑上的 AI 环境感知与智能控制系统。它通过 Home Assistant 等设备适配层获取现实环境信息，建立自己的环境上下文与事件记录，由 AI Agent 理解用户目标、生成任务计划，并通过受控工具调用低风险设备，最后验证执行结果并留下完整记录。

当前项目处于 **架构已确认，Phase 9 自动化与通知已完成（待用户验收）** 状态。项目包含前后端基础骨架、健康检查、SQLite 数据模型、Alembic 迁移、Repository 边界、备份恢复、统一设备接口、Home Assistant Adapter、Mock Device Adapter、轻量 Device Registry、状态轮询、标准化 Event Schema、进程内 Event Bus、事件持久化、事件查询 API、Environment Context、Tool Registry、Safety Policy、用户确认、Tool Executor、执行审计、状态验证、Task/TaskStep 状态机、显式任务计划执行、任务历史、任务事件、correlation ID 追踪、统一 AI Provider Interface、OpenAI-compatible Provider、Mock AI Provider、结构化候选输出校验、模型调用日志、`/api/chat` 自然语言入口、Web 控制台核心页面、少量 Arvuno 上下文自动化规则和 Web Console 站内通知；尚未连接真实 Home Assistant，也未实现 Memory、会话持久化、Agent 自主规划、通用自动化编辑器或多渠道通知。

## 开发环境与常用命令

### 环境要求

- Windows 11
- Python 3.11 或更高版本
- Node.js 20 或更高版本，以及 `npm` 或 `pnpm`
- Git

### 安装依赖

```powershell
cd E:\williamzhang\zzh\zzh-personal-project\nova
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend\requirements-dev.txt

cd frontend
npm install
```

如使用 `pnpm`，将前端安装命令替换为 `pnpm install`。

### 启动

后端：

```powershell
.\scripts\start-backend.ps1
```

前端：

```powershell
.\scripts\start-frontend.ps1
```
如果 `python`、`npm` 或 `pnpm` 不在 PATH 中，可分别使用：

```powershell
.\scripts\start-backend.ps1 -PythonPath "<python.exe 的完整路径>"
.\scripts\start-frontend.ps1 -PackageManagerPath "<npm.cmd 或 pnpm.cmd 的完整路径>"
```

默认地址：

- 后端 API：`http://127.0.0.1:8000`
- 健康检查：`http://127.0.0.1:8000/health`
- OpenAPI 文档：`http://127.0.0.1:8000/docs`
- 前端：`http://127.0.0.1:5173`

### 数据库、迁移与备份

后端启动脚本会自动创建本地目录并执行数据库迁移。常用管理命令：

```powershell
$env:PYTHONPATH = "backend"
.\.venv\Scripts\python.exe -m arvuno_core.persistence init
.\.venv\Scripts\python.exe -m arvuno_core.persistence status
.\.venv\Scripts\python.exe -m arvuno_core.persistence backup
.\.venv\Scripts\python.exe -m arvuno_core.persistence restore "<backups\arvuno-....sqlite3>" --replace-existing
```

默认数据库位于 `data\arvuno.sqlite3`，日志位于 `logs\`，备份位于 `backups\`；这些本地目录和文件不会提交到 Git。恢复前应先停止后端，只允许恢复 `backups\` 目录内的备份文件，并必须显式传入 `--replace-existing`。每次存在待执行迁移时会先自动备份。

从旧 Nova 命名升级时，已有 `data\nova.sqlite3` 不会被自动改名或复制。若要继续使用现有数据，先停止后端，备份数据库，然后把该文件改名为 `data\arvuno.sqlite3`；旧 `NOVA_` 环境变量也必须同步改为新的 `ARVUNO_` 前缀。

### 测试与检查

```powershell
cd E:\williamzhang\zzh\zzh-personal-project\nova
.\.venv\Scripts\python -m pytest backend\tests
.\.venv\Scripts\python -m ruff format --check backend
.\.venv\Scripts\python -m ruff check backend

cd frontend
npm run typecheck
npm run build
npm run format:check
```
真实环境变量从根目录 `.env` 读取；可从 `.env.example` 复制后修改，不要提交 `.env`。

### 设备接入配置

Phase 3 使用以下环境变量控制 Home Assistant 访问：

```text
ARVUNO_HOME_ASSISTANT_URL=
ARVUNO_HOME_ASSISTANT_TOKEN=
ARVUNO_HOME_ASSISTANT_TIMEOUT_SECONDS=10
ARVUNO_HOME_ASSISTANT_ALLOWED_ENTITY_IDS=[]
ARVUNO_HOME_ASSISTANT_WRITE_ENABLED=false
ARVUNO_DEVICE_POLL_INTERVAL_SECONDS=30
```

`ARVUNO_HOME_ASSISTANT_ALLOWED_ENTITY_IDS` 支持 JSON 数组或逗号分隔列表；为空时不会导入任何 Home Assistant 实体。`ARVUNO_HOME_ASSISTANT_WRITE_ENABLED` 仅作为开发开关，默认必须保持 `false`，生产环境会直接拒绝开启。Safety Policy 和 Tool Executor 已完成后，真实设备写操作仍必须保持默认关闭，待用户逐项确认允许的实体和动作后再开启。

当前自动化测试全部使用 Mock Adapter 和 Home Assistant HTTP 模拟响应，不需要真实 Home Assistant 或真实设备。

### 环境事件配置与查询

Phase 4 使用以下环境变量控制事件保留和默认环境名称：

```text
ARVUNO_EVENT_RETENTION_DAYS=180
ARVUNO_DIAGNOSTIC_EVENT_RETENTION_DAYS=90
ARVUNO_LONG_TERM_EVENT_TYPES=["task_started","task_completed","task_failed","tool_executed","user_confirmed"]
ARVUNO_DEFAULT_ENVIRONMENT_NAME=home
ARVUNO_API_TOKEN=
```

`GET /api/events` 和 `GET /api/events/{event_id}` 用于查询 Arvuno 自己持久化的领域事件，支持事件类型、来源、对象、correlation ID、时间范围、排序和分页过滤；除 `/health` 与 OpenAPI 文档外，事件 API 需要 Bearer Token。设备事件由统一 Device Adapter 转换为标准事件，只记录配置范围内 Arvuno 需要的状态变化，不复制 Home Assistant 完整历史。

### 安全工具配置与执行

Phase 5 使用以下环境变量控制工具权限和确认有效期：

```text
ARVUNO_TOOL_CONFIRMATION_TTL_SECONDS=300
ARVUNO_TOOL_PERMISSIONS={"list_devices":"allow","get_environment_state":"allow","get_device_state":"allow","control_device":"allow_low_risk"}
```

工具目录由 `GET /api/tools` 查询，执行入口为 `POST /api/tools/{tool_name}/execute`；两个接口都需要 Bearer Token。执行链路包含 Schema 校验、工具注册检查、设备与动作权限检查、风险检查、必要的用户确认、执行、实际状态读取、结果验证和执行记录。`medium_risk` 动作必须使用首次返回的一次性确认 Token 重放同一请求，Token 会过期且绑定工具输入与任务；`high_risk` 动作默认拒绝。

### 任务系统与执行记录

Phase 6 提供显式计划的最小任务系统。`POST /api/tasks` 创建并按顺序执行 TaskStep；每个步骤必须经过既有 Tool Executor，因此继续受 Tool Registry、Safety Policy、用户确认、执行审计和状态验证约束。请求可包含 `task_type`、`title`、`steps` 和 `timeout_seconds`，并可用 `X-Correlation-ID` 关联 API 请求、任务、步骤、工具执行和领域事件。

任务查询入口：

- `GET /api/tasks`：按状态、类型、会话和时间范围分页查询任务历史。
- `GET /api/tasks/{task_id}`：查看任务、TaskStep、工具执行记录、验证结果和错误。
- `POST /api/tasks/{task_id}/confirm`：确认或拒绝等待确认的任务步骤。
- `POST /api/tasks/{task_id}/cancel`：取消未完成任务及其未完成步骤。

需要确认时，创建响应会返回一次性 `confirmation_token`，任务进入 `waiting_confirmation`；确认 Token 只在本次响应中出现，计划中保存 SHA-256 摘要，重复确认按已使用 Token 幂等处理。任务执行失败会将当前步骤标记为 `failed` 并取消后续步骤；执行超时将任务标记为 `failed`、步骤标记为 `timed_out`；等待确认超时或用户拒绝会将任务和步骤标记为 `cancelled`。

### AI Provider 与 Agent Runtime

Phase 7 默认使用离线 Mock AI Provider，配置为 OpenAI-compatible Provider 时才发起真实模型 HTTP 调用：

```text
ARVUNO_AI_PROVIDER=mock
ARVUNO_AI_BASE_URL=
ARVUNO_AI_MODEL=
ARVUNO_AI_API_KEY=
ARVUNO_AI_TIMEOUT_SECONDS=30
ARVUNO_AI_MAX_RETRIES=2
ARVUNO_AI_STRUCTURED_OUTPUT_MODE=json_schema
ARVUNO_AI_RETRY_BACKOFF_SECONDS=0.2
```

OpenAI-compatible Provider 支持 Base URL、模型名称、API Key、超时、有限重试和 `json_schema`、`json_object`、`prompt_only` 三种结构化输出模式；收到 400/422 时会按顺序降级。Provider 日志只保存脱敏摘要和 Token 用量，API Key 只能来自 `.env` 或受保护环境变量。真实模型调用是可选手工验证，自动化测试不依赖网络。

`POST /api/chat` 接收自然语言消息并返回意图、回复、任务 ID、确认信息、Provider 日志 ID、correlation ID 和错误摘要。Agent Runtime 只把模型输出当作待验证候选：先做 Pydantic 结构化校验、意图与工具匹配、Tool Catalog 参数校验和风险检查，再通过 Task System 创建任务。执行链路仍为 `Agent Runtime -> TaskService -> TaskStep -> ToolExecutor -> SafetyPolicy -> DeviceApplicationService`；模型不能直接执行设备操作，也不能绕过确认机制。本阶段不保存对话和 Memory，不做自主多轮规划。

## Web 控制台

Phase 8 提供 Arvuno Core 的运行与观测界面，包含系统概览、设备列表与详情、环境状态、事件时间线、AI 对话、任务列表与详情、任务确认/取消和系统设置页面。前端统一通过 `frontend/src/api` 中的类型化封装访问 Arvuno API；服务端状态由 TanStack Query 管理，页面不直接请求 Home Assistant，也不在前端伪造授权或执行结果。

控制台新增查询与设置 API：

- `GET /api/system/status`：后端版本、数据库、适配器、设备与活动任务摘要。
- `GET /api/devices`、`GET /api/devices/{device_id}`、`GET /api/devices/{device_id}/state`：设备投影、详情和当前状态。
- `GET /api/environment`、`GET /api/environment/snapshots`：当前环境上下文和历史快照。
- `GET /api/settings`、`PATCH /api/settings`：读取非敏感运行摘要，更新 Web Console 非敏感偏好。

事件时间线当前按 `web_console.event_poll_interval_seconds`（默认 10 秒，范围 2-300 秒）自动轮询 `/api/events`，不是 WebSocket 推送。设备控制仍从 AI 对话进入候选计划，再由 Task System 通过 Tool Executor 和 Safety Policy 执行。设置页只保存浏览器本地的 Arvuno API Base URL 和 Bearer Token，并展示服务端非敏感配置；AI API Key、Home Assistant Token 等敏感配置只能通过受保护的 `.env` 或进程环境变量提供给后端。

## 自动化与通知

Phase 9 提供少量需要 Arvuno 上下文的自动化规则和 Web Console 站内通知。规则只支持 `device_state_changed`、`sensor_updated`、`device_unavailable` 三类触发事件；条件使用显式字段路径和操作符按 AND 组合评估；动作只支持 `notification` 和 `tool`。普通定时、状态触发和场景自动化继续由 Home Assistant 管理，本阶段不提供通用自动化编辑器。

- `GET /api/automations`、`GET /api/automations/{id}`：查询规则和详情。
- `POST /api/automations`、`PATCH /api/automations/{id}`：创建和更新规则。
- `POST /api/automations/{id}/enable`、`POST /api/automations/{id}/disable`：启用和停用规则。
- `GET /api/automations/{id}/runs`：查询执行历史、命中上下文、任务或通知关联以及错误。
- `GET /api/notifications`、`POST /api/notifications/{id}/read`：查询和标记已读站内通知。

通知动作直接生成 Web Console 通知。工具动作不会绕过安全链路，实际执行路径为 `AutomationService -> TaskService -> TaskStep -> ToolExecutor -> SafetyPolicy`；只有 `read_only` 和 `low_risk` 动作可以自动执行，`medium_risk` 和 `high_risk` 在创建任务前记录 `risk_rejected`。冷却时间基于最近一次 `completed`、`failed` 或 `risk_rejected` 执行计算，任务失败会生成错误级站内通知。触发事件、`automation_triggered` 事件、任务、工具执行和自动化执行记录通过 correlation ID 关联。

## 当前定位

Arvuno Core 不是 Home Assistant 的替代品，也不是单纯的聊天助手。它负责：

- 环境状态理解
- 事件关联与长期记忆
- 自然语言意图理解
- 任务规划与执行
- 受控工具调用
- 设备控制结果验证
- 少量 Arvuno 上下文自动化与通知
- Web 控制台展示

Home Assistant 负责设备集成、设备状态、设备控制和智能家居生态兼容。Arvuno Core 通过独立设备适配层访问它，不把 Home Assistant 的内部模型当作自己的领域模型。

## 技术方向

- 后端：Python + FastAPI + Pydantic + SQLAlchemy + SQLite + Alembic + pytest
- 前端：React + TypeScript + Vite + Ant Design + React Router + TanStack Query
- 架构：Windows 本地运行的模块化单体
- AI：统一 Provider 适配层，第一阶段优先支持兼容 OpenAI API 格式的模型接口
- 设备：第一阶段实现 Home Assistant Adapter 和 Mock Device Adapter，业务侧只依赖统一 Device Adapter 接口

## 文档索引

架构设计文档位于 [docs](docs)：

1. [项目概览](docs/00-project-overview.md)
2. [产品定义](docs/01-product-definition.md)
3. [系统架构](docs/02-system-architecture.md)
4. [模块职责](docs/03-module-responsibilities.md)
5. [技术选型](docs/04-technology-stack.md)
6. [数据模型](docs/05-data-model.md)
7. [API 设计](docs/06-api-design.md)
8. [设备适配层设计](docs/07-device-adapter-design.md)
9. [事件系统设计](docs/08-event-system-design.md)
10. [Agent 与工具设计](docs/09-agent-and-tool-design.md)
11. [记忆系统设计](docs/10-memory-system-design.md)
12. [安全与权限设计](docs/11-security-and-permissions.md)
13. [测试策略](docs/12-testing-strategy.md)
14. [开发路线图](docs/13-development-roadmap.md)
15. [决策与取舍](docs/14-decisions-and-tradeoffs.md)
16. [未来扩展](docs/15-future-extension.md)

长期开发规范见 [AGENTS.md](AGENTS.md)。

## 当前阶段结论

Phase 9 已完成自动化与通知最小闭环。用户确认本阶段成果后，后续按以下顺序推进：

1. 第一阶段稳定化验收
2. 真实 Home Assistant 可选手动验收

第一阶段必须提前确定设备抽象、事件格式、任务状态机、工具权限模型和执行验证机制。语音、视觉、机器人、多 Agent、分布式系统、自研智能家居协议和商业 SaaS 均暂不开发；机器人只保留在未来扩展文档中评估，不预留当前接口。
