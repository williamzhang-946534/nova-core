# 04. 技术选型

## 选型结论

### 后端

| 技术 | 结论 | 原因 |
| --- | --- | --- |
| Python | 采用 | AI、Agent、数据处理和智能家居生态成熟；学习成本可控 |
| FastAPI | 采用 | 原生支持异步 API、Pydantic 校验、OpenAPI 和 WebSocket |
| Pydantic | 采用 | 统一配置、请求、响应、事件和工具参数模型 |
| SQLAlchemy | 采用 | 提供成熟 ORM 和数据访问边界，便于未来迁移数据库 |
| SQLite | 采用 | 单文件、零部署、适合 Windows 个人系统第一阶段 |
| Alembic | 采用 | 管理数据库结构演进，避免手工改表 |
| pytest | 采用 | 单元测试、集成测试和参数化测试成本低 |
| httpx | 采用 | 异步 HTTP 客户端，适合调用 Home Assistant 和 AI API |

### 前端

| 技术 | 结论 | 原因 |
| --- | --- | --- |
| React | 采用 | 用户已有经验，生态成熟 |
| TypeScript | 采用 | 保证 API 类型和组件输入输出清晰 |
| Vite | 采用 | 启动快、配置简单，适合本地开发 |
| Ant Design | 采用 | 适合控制台类系统，表格、表单和状态组件成熟 |
| React Router | 采用 | 支持多页面控制台导航 |
| TanStack Query | 采用 | 管理服务端状态、缓存、重试和加载错误状态 |

### 暂不采用

| 技术 | 结论 | 原因 |
| --- | --- | --- |
| NestJS | 暂不采用 | 后端更贴近 Python AI 生态；用户熟悉其思想，可迁移 |
| PostgreSQL | 暂不采用 | 第一阶段数据量和部署需求不需要额外数据库服务 |
| Docker | 暂不采用 | Windows 原生运行更简单；可作为后续打包方案 |
| Kafka / RabbitMQ | 不采用 | 进程内事件总线已满足第一阶段需求 |
| Kubernetes | 不采用 | 个人单机项目无法承受运维成本 |
| 向量数据库 | 暂不采用 | 第一阶段记忆量小，先设计接口不引入组件 |
| 多 Agent 框架 | 不采用 | 会增加复杂度且不符合第一阶段目标 |

## 后端分析

### Python

**优势：**

- AI Provider、结构化输出、工具调用和数据处理生态成熟。
- 后续接入本地模型、数据处理和更多传感器分析能力时选择更多。
- Pydantic 可以让动态模型输出快速变成可验证的类型化对象。
- 适合个人开发阶段的脚本化调试和测试。

**风险：**

- 开发者 Python 后端经验较少。
- Python 项目如果缺少规范，容易出现弱类型、全局状态和业务逻辑散乱。

**控制措施：**

- 全部核心接口使用类型标注。
- 使用 Pydantic 强校验边界数据。
- 使用 Repository 隔离数据库。
- 保持模块边界，不允许路由层承载业务逻辑。
- 测试覆盖核心状态和权限逻辑。

### FastAPI

**优势：**

- 异步模型适合同时处理 HTTP、WebSocket、Home Assistant 事件和 AI 调用。
- 与 Pydantic 深度集成，适合接口合同优先开发。
- 自动生成 OpenAPI，便于前后端协作。
- 学习成本低于完整重型框架。

**注意点：**

- FastAPI 依赖注入需要保持清晰，不能为了省事把所有服务都放进全局变量。
- SQLite 异步访问需要选择稳定的连接策略，实施时优先使用经过验证的 `aiosqlite` 或同步 SQLAlchemy 配合清晰事务边界。

### Pydantic

使用场景：

- 应用配置
- API 请求和响应
- Event Schema
- Tool Schema
- Device State Model
- AI 结构化输出
- 自动化规则模型

原则：

- 外部输入必须通过 Pydantic 校验。
- 数据库模型和 API Schema 分离，避免 ORM 对象直接泄漏给前端。
- 工具参数必须有严格 Schema。

### SQLAlchemy

使用原因：

- 成熟、文档丰富、支持 SQLite 和 PostgreSQL。
- 可以通过 Repository 层隔离业务逻辑和数据库实现。
- 支持 JSON 字段，适合第一阶段保存事件 payload 和工具参数。

约束：

- 不使用 SQLite 特有 SQL 方言。
- 不依赖数据库隐式行为处理业务状态。
- 复杂查询优先写在 Repository 中，而不是业务服务中拼接 SQL。

### SQLite

适用原因：

- 第一阶段是单用户、单进程、本地运行。
- 数据量小，部署成本接近零。
- 备份可以简化为复制数据库文件。

约束：

- 写入并发有限，事件写入要避免长事务。
- 数据库路径必须可配置。
- 需要定期备份，不能把 SQLite 当作不可丢失的长期唯一备份。

### Alembic

必须使用迁移管理：

- 首次建表。
- 后续新增字段。
- 索引调整。
- 数据清理策略变更。

禁止直接在运行环境手工修改表结构。

### pytest

测试范围：

- 状态模型
- 事件模型
- 权限判断
- 工具参数校验
- 任务状态机
- Home Assistant Adapter
- Mock Adapter
- API 合同
- Provider 错误处理

## 前端分析

### React + TypeScript

控制台需要大量列表、详情、时间线、表单和状态展示，React 和 TypeScript 能较好约束 API 数据结构。

### Ant Design

适合页面：

- 系统概览
- 设备列表
- 设备详情
- 任务记录
- 事件时间线
- 自动化规则
- 设置页面

设计约束：

- 不做营销式页面。
- 以信息密度、可扫描性和操作效率为主。
- 不复刻 Home Assistant Dashboard。

### TanStack Query

适合管理：

- 设备列表
- 环境状态
- 事件分页
- 任务历史
- 自动化规则

避免：

- 在前端复制后端业务状态。
- 使用复杂全局状态管理当前不需要的状态。

## 数据库策略

第一阶段使用 SQLite。

未来 PostgreSQL 迁移条件：

1. 数据量导致 SQLite 查询明显变慢。
2. 需要多进程写入。
3. 需要更复杂全文检索或数组类型。
4. 需要长期运行服务化部署。

在迁移前，必须保持：

- 无 SQLite 特有 SQL。
- Repository 边界清晰。
- UUID 主键策略统一。
- JSON 字段结构通过 Pydantic 校验。
- 时间统一使用 UTC 存储。

## AI Provider 策略

第一阶段实现统一 Provider Interface，优先支持兼容 OpenAI API 格式的模型接口。

必须支持：

- Base URL
- API Key
- Model Name
- Timeout
- Retry
- 结构化输出
- 工具定义
- 错误分类
- 调用日志

不得支持或允许：

- 硬编码 API Key
- Provider 名称写入业务逻辑
- 模型输出直接执行
- 无超时外部请求
- 未记录的模型调用

GLM-5.3 或其他模型不能被假设为完全等同 OpenAI 能力。结构化输出和工具调用必须在 Provider 层做能力探测与降级设计。

## 依赖控制

第一阶段建议核心依赖：

```text
后端：
fastapi
uvicorn
pydantic
pydantic-settings
sqlalchemy
alembic
aiosqlite 或 sqlite 驱动
httpx
pytest

前端：
react
typescript
vite
antd
react-router-dom
@tanstack/react-query
```

是否引入额外库必须满足：

1. 解决明确问题。
2. 维护活跃。
3. Windows 可运行。
4. 不破坏模块边界。
5. 不引入复杂部署要求。

## Windows 原生运行与 Docker 对比

| 维度 | Windows 原生 | Docker |
| --- | --- | --- |
| 启动难度 | 低 | 中 |
| 调试体验 | 高 | 中 |
| Home Assistant 连接 | 直接 | 需要网络配置 |
| 文件路径 | 简单 | 需要挂载 |
| 环境隔离 | 一般 | 好 |
| 备份 | 数据库文件复制 | Volume 管理 |
| 额外资源占用 | 低 | 中 |

**推荐：** 第一阶段 Windows 原生运行。待系统稳定后，再评估 Docker 打包。

## 成本分析

| 项目 | 预算 |
| --- | --- |
| 开发电脑 | 使用现有设备 |
| 数据库 | SQLite，免费 |
| 后端框架 | 免费 |
| 前端框架 | 免费 |
| Home Assistant | 使用现有部署 |
| AI API | 按需小额消费 |
| 测试设备 | 可先用 Mock Adapter |

第一阶段可以在 1000 元人民币以内完成核心软件开发。若加入真实传感器或更多智能设备，需要单独计算硬件成本，但不属于软件架构必需支出。

## 最终建议

采用 **Python FastAPI + React TypeScript + SQLite + 模块化单体**。

这个组合符合：

- Windows 本地运行
- 个人开发维护
- 低成本
- AI Agent 开发便利
- 前后端能力匹配
- 后续可扩展

不建议为了技术统一选择 NestJS，也不建议为了未来规模提前引入 PostgreSQL、消息队列或容器编排。
