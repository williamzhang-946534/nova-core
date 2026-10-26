# Nova Core

Nova Core 是一个运行在个人 Windows 电脑上的 AI 环境感知与智能控制系统。它通过 Home Assistant 等设备适配层获取现实环境信息，建立自己的环境上下文与事件记录，由 AI Agent 理解用户目标、生成任务计划，并通过受控工具调用低风险设备，最后验证执行结果并留下完整记录。

当前项目处于 **架构已确认，Phase 2 数据与配置已完成（待用户验收）** 状态。项目包含前后端基础骨架、健康检查、SQLite 数据模型、Alembic 迁移、Repository 边界、备份恢复和 Windows 启动配置；Home Assistant、AI Provider 和业务页面尚未实现。

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
.\.venv\Scripts\python.exe -m nova_core.persistence init
.\.venv\Scripts\python.exe -m nova_core.persistence status
.\.venv\Scripts\python.exe -m nova_core.persistence backup
.\.venv\Scripts\python.exe -m nova_core.persistence restore "<backups\nova-....sqlite3>" --replace-existing
```

默认数据库位于 `data\nova.sqlite3`，日志位于 `logs\`，备份位于 `backups\`；这些本地目录和文件不会提交到 Git。恢复前应先停止后端，只允许恢复 `backups\` 目录内的备份文件，并必须显式传入 `--replace-existing`。每次存在待执行迁移时会先自动备份。

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

## 当前定位

Nova Core 不是 Home Assistant 的替代品，也不是单纯的聊天助手。它负责：

- 环境状态理解
- 事件关联与长期记忆
- 自然语言意图理解
- 任务规划与执行
- 受控工具调用
- 设备控制结果验证
- 少量 Nova 上下文自动化与通知
- Web 控制台展示

Home Assistant 负责设备集成、设备状态、设备控制和智能家居生态兼容。Nova Core 通过独立设备适配层访问它，不把 Home Assistant 的内部模型当作自己的领域模型。

## 技术方向

- 后端：Python + FastAPI + Pydantic + SQLAlchemy + SQLite + Alembic + pytest
- 前端：React + TypeScript + Vite + Ant Design + React Router + TanStack Query
- 架构：Windows 本地运行的模块化单体
- AI：统一 Provider 适配层，第一阶段优先支持兼容 OpenAI API 格式的模型接口
- 设备：第一阶段只实现 Home Assistant Adapter，并设计 Mock Device Adapter 用于测试

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

Phase 2 已完成数据与配置。用户确认本阶段成果后，Phase 3 起按以下顺序推进：

1. 设备适配层接口与 Home Assistant Adapter
2. 环境状态与事件系统
3. 工具注册与安全执行
4. 任务系统与执行记录
5. AI Provider 与 Agent Runtime
6. Web 控制台
7. Nova 上下文自动化与通知

第一阶段必须提前确定设备抽象、事件格式、任务状态机、工具权限模型和执行验证机制。语音、视觉、机器人、多 Agent、分布式系统、自研智能家居协议和商业 SaaS 均暂不开发；机器人只保留在未来扩展文档中评估，不预留当前接口。
