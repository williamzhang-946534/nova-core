# 20. ARS-02 Spatial Model 设计

- 阶段：`ARS-02.0：架构设计与数据契约冻结`
- 日期：2026-11-02
- 状态：设计完成，等待用户确认；本文不是已实现行为
- 范围：现实空间层级、实体身份、设备关系、空间归属和历史追溯
- 禁止事项：本文不修改业务代码、数据库迁移、API、依赖或前端页面

## 1. 设计结论

ARS-02 新增 `spaces`、`entities` 和 `entity_space_assignments` 三个核心概念。`environments` 保留为 Arvuno 的运行范围和上下文所有者，并通过 `root_space_id` 指向一棵现实空间树；它不再是空间的父节点，也不承担楼层、房间、区域管理。

目标关系是：

```text
Environment（运行范围 / 上下文所有者）
  └── root_space_id → Space root（现实空间根节点）
        └── parent_id → Space tree（楼层 / 房间 / 区域）

Entity（被系统认识的对象）
  ├── Device（当前已接入设备的适配身份）
  └── EntitySpaceAssignment（带时间区间的空间归属）
```

家庭初始层级为：

```text
home → floor → room → zone
```

同一模型未来必须能表达：

```text
factory → workshop → production_line → workstation
```

本阶段只实现家庭场景和上述四种家庭空间类型，不实现工业空间、工业资产、工业协议或工业规则。扩展通过空间类型词汇表和配置完成，不通过重构表结构完成。

## 2. 概念边界

| 概念 | 定义 | 不承担的职责 |
| --- | --- | --- |
| Environment | Arvuno 的运行范围、默认配置、隔离边界和上下文所有者 | 不表示房间，不构成空间树，不保存设备最新状态 |
| Space | 现实世界的空间节点及其父子关系 | 不表示 AI 运行环境，不表示设备，不表示一次观测 |
| Entity | 被系统认识的对象，例如传感器、执行器、设备、未来机器人或有价值物体 | 不等同于接入设备，不承载设备协议细节 |
| Device | 已通过 Adapter 接入的技术设备身份 | 不承载家庭空间层级，不是所有现实对象的统一身份 |
| Observation | 一次实际观测的标准化记录 | 不直接等于当前事实，不承担长期记忆归纳 |
| State Estimate | 系统基于观测和规则对当前状态的估计 | 不替代原始观测，不伪装成直接事实 |
| Event | 系统识别到的重要变化或动作 | 不是观测主存储，不是状态估计主存储 |
| Snapshot | 某个时点的状态投影 | 不是可变事实源，不是备份数据库 |
| Memory | 被选择、归纳、管理并可长期复用的信息 | 不保存每条观测，不承担实时状态计算 |

`Environment` 与 `Space` 的职责划分是本设计的关键决策：

1. `environments.id` 继续作为运行范围 ID，供配置、快照、授权和未来多实例使用。
2. `environments.root_space_id` 唯一指向当前运行范围的空间根节点。
3. 空间父子关系只存在于 `spaces.parent_id`。
4. 不得在 `environments` 中增加楼层、房间、区域等字段。
5. 不得让 `spaces.environment_id` 成为另一条空间归属链，避免空间同时属于 Environment 和父 Space。
6. 查询一个运行范围的完整空间树时，从 `root_space_id` 或派生路径出发。

## 3. 当前代码审查结论

当前代码已经具备 Device Registry、Home Assistant Adapter、Mock Adapter、Environment Context 和 Web Console，但空间语义仍停留在字符串聚合：

1. `devices.area` 是 nullable 字符串，只用于展示和 `area_summary()` 聚合。
2. `environments.ensure_default()` 创建默认运行范围，例如 `home`，但该记录不是空间树根。
3. `device_states.observed_at` 目前混合了采集、读取和接收时间语义，不能满足观测溯源。
4. `environment_snapshots.context` 是 JSON 投影，无法回答某个房间状态来自哪些观测、是否冲突或未知。
5. 现有设备事件和状态记录没有实体身份，设备更换后难以保持“同一个现实对象”的历史连续性。

因此 ARS-02 不能直接把 `devices.area` 改名为 `space_id`。必须先建立稳定实体和空间身份，再做受限迁移。

## 4. Spatial Model 数据契约

以下为目标数据契约。字段名在工程实现时可以按 SQLAlchemy / Alembic 命名规范微调，但语义不得缺失。

### 4.1 `spaces`

`spaces` 表示现实空间节点，是可追溯的长期事实源。

| 字段 | 类型 / 约束 | 说明 |
| --- | --- | --- |
| `id` | UUID / PK | 稳定空间 ID，迁移和移动后不变 |
| `parent_id` | FK → `spaces.id`，nullable | 仅根节点为空；非根节点必须指向同一棵树 |
| `space_type` | string | 家庭阶段限定 `home`、`floor`、`room`、`zone` |
| `name` | string | 用户可见名称 |
| `normalized_name` | string | 查询和排序用归一化名称 |
| `slug` | string | 同一兄弟节点内唯一的人类可读标识 |
| `path` | string | 派生路径，例如 `home/1f/living-room/sofa-area`；移动时事务内重算 |
| `sort_order` | integer | 用户自定义排序 |
| `external_space_id` | string，nullable | HA Area 等外部空间引用，不能替代内部 ID |
| `external_source` | string，nullable | 外部空间来源，例如 `home_assistant` |
| `status` | string | `active`、`inactive`、`archived` |
| `geometry` | JSON，nullable | 未来边界、位置或地图元数据；本阶段仅预留 |
| `metadata` | JSON | 非身份、非父子关系的补充信息 |
| `created_at` | UTC datetime | 创建时间 |
| `updated_at` | UTC datetime | 最后修改时间 |
| `archived_at` | UTC datetime，nullable | 归档时间；有历史引用时禁止物理删除 |

约束和规则：

1. `parent_id` 为空的节点是根节点；初始实现中每个 Environment 只有一个根。
2. 应用层和迁移层必须拒绝环、跨树移动、重复 slug 和把非根空间挂到自身。
3. `path` 是派生缓存，不是身份；祖先移动时必须同事务更新后代路径，失败即整体回滚。
4. `space_type` 不使用会阻断未来扩展的封闭数据库枚举。家庭阶段的应用层校验只允许四种家庭类型。
5. 空间移动不重写历史观测。历史解释依赖观测发生时的 `space_id` 和实体归属区间。
6. 空间归档后不得接收新观测或新实体归属，但历史查询必须继续返回。

### 4.2 派生闭包表 `space_paths`

为避免 SQLite 深递归和反复树遍历，引入可重建的闭包或物化路径投影表：

| 字段 | 类型 / 约束 | 说明 |
| --- | --- | --- |
| `ancestor_id` | FK → `spaces.id` | 祖先空间 |
| `descendant_id` | FK → `spaces.id` | 后代空间 |
| `depth` | integer | 0 表示自身，1 表示直接子节点 |
| `path_version` | UUID | 每次树结构变更的批次 ID |
| `created_at` | UTC datetime | 投影生成时间 |

主键为 `(ancestor_id, descendant_id)`。`space_paths` 只由 Spatial Model Service 在空间创建、移动、归档后重建，不作为用户可编辑事实源。损坏时允许删除并重建，不得手工修复。

### 4.3 `environments` 变更

新增字段：

| 字段 | 类型 / 约束 | 说明 |
| --- | --- | --- |
| `root_space_id` | FK → `spaces.id`，nullable | 当前运行范围的空间根；单环境部署稳定后应非空 |

规则：

1. 迁移初期允许为空，表示尚未完成空间初始化。
2. 空间初始化后，一个 Environment 必须且只能有一个根空间。
3. 根空间可以整体替换，但必须作为显式迁移操作记录，不允许普通更新造成两个根。
4. 不新增 `environments.parent_id`、`environments.floor`、`environments.room` 等空间字段。

## 5. Entity Model 数据契约

### 5.1 `entities`

`entities` 是现实对象统一身份，不复制设备协议细节。

| 字段 | 类型 / 约束 | 说明 |
| --- | --- | --- |
| `id` | UUID / PK | 稳定实体 ID |
| `environment_id` | FK → `environments.id` | 实体所属运行范围 |
| `entity_type` | string | `device`、`sensor`、`actuator`、`robot`、`object`；本阶段主要使用前三类 |
| `name` | string | 用户可见名称 |
| `normalized_name` | string | 查询名称 |
| `description` | text，nullable | 用户描述 |
| `status` | string | `active`、`inactive`、`retired`、`unknown` |
| `semantic_tags` | JSON | 温度传感器、空调、门、贵重物品等语义标签 |
| `capabilities_ref` | JSON，nullable | 能力摘要或指向能力定义；本阶段不新建执行系统 |
| `metadata` | JSON | 非身份信息 |
| `created_at` | UTC datetime | 创建时间 |
| `updated_at` | UTC datetime | 最后修改时间 |
| `retired_at` | UTC datetime，nullable | 退役时间 |

实体类型边界：

1. 一个接入设备必须对应一个 Entity，但 Entity 不必然有 Device。
2. 传感器和执行器可以先是设备的语义角色，不要求拆成独立表。
3. 未来机器人、摄像头或贵重物体复用 Entity 身份，但能力、授权和安全策略另行扩展。
4. 本阶段不自动识别物体，不登记所有家庭物品，只登记设备、传感器、执行器和用户显式创建的有价值对象。
5. Entity 不保存当前房间字段；当前位置或固定安装位置由带时间区间的归属关系表达。

### 5.2 `devices` 变更

新增字段：

| 字段 | 类型 / 约束 | 说明 |
| --- | --- | --- |
| `entity_id` | FK → `entities.id`，nullable → 后续必填 | 稳定现实对象身份 |

迁移策略：

1. ARS-02.1 先添加 nullable 字段和索引，避免锁死已有设备。
2. 为每个现有 Device 创建对应 Entity，再回填 `devices.entity_id`。
3. `devices.area` 保留为兼容字段和迁移辅助，不作为 ARS-02 查询入口。
4. 当能通过外部 Area、用户确认或既有配置推断房间时，创建历史归属区间；无法推断时保持 unknown，不得猜测。
5. 设备更换后创建新 Device，可显式绑定旧 Entity；默认不自动把新硬件视为同一现实对象。
6. `devices.adapter_id + external_id` 继续表示接入身份，不用作现实对象 ID。

### 5.3 `entity_space_assignments`

该表表达实体在什么时间位于哪个空间，是空间历史追溯的核心。

| 字段 | 类型 / 约束 | 说明 |
| --- | --- | --- |
| `id` | UUID / PK | 记录 ID |
| `entity_id` | FK → `entities.id` | 被归属对象 |
| `space_id` | FK → `spaces.id` | 空间节点 |
| `assignment_type` | string | `fixed_installation`、`current_placement`、`observed_presence`、`user_asserted` |
| `valid_from` | UTC datetime | 归属开始时间 |
| `valid_until` | UTC datetime，nullable | 为空表示当前仍有效 |
| `confidence` | numeric，nullable | 0 到 1；用户断言可为 1.0 |
| `source_type` | string | `user`、`adapter`、`observation`、`migration` |
| `source_id` | string，nullable | 来源标识 |
| `source_observation_id` | UUID，nullable | 支撑该归属的观测；ARS-02.2 后使用 |
| `reason` | text，nullable | 用户说明或迁移说明 |
| `created_at` | UTC datetime | 创建时间 |
| `updated_at` | UTC datetime | 更新时间 |

规则：

1. `valid_until` 必须为空或晚于 `valid_from`。
2. 移动实体时，同事务关闭旧区间并创建新区间，不允许覆盖历史。
3. 当前归属可以有多个类型，例如固定安装位置和观测到的临时位置并存，但 `fixed_installation` 的当前区间应唯一。
4. SQLite 没有区间排除约束，重叠检查由 Repository / Service 在写入事务中执行，并必须有并发测试。
5. 固定传感器移动后，历史观测仍指向旧 `space_id`，同时可通过实体归属区间解释当时位置。
6. API 查询“当前在哪个空间”读取当前区间；查询“当时在哪个空间”使用 `observed_at BETWEEN valid_from AND valid_until`。

## 6. 空间类型与扩展

### 6.1 家庭类型

| 类型 | 语义 | 示例 |
| --- | --- | --- |
| `home` | 住宅根节点 | 一套房子 |
| `floor` | 楼层 | 一层、二层、负一层 |
| `room` | 房间 | 客厅、卧室、厨房 |
| `zone` | 房间内功能区 | 沙发区、床头区、工作区 |

家庭阶段建议父子约束：

```text
home → floor → room → zone
```

允许简化为 `home → room` 或 `room → zone`，以适配小户型或用户不想维护完整层级的情况。应用层可以警告不常见层级，但不得因为非典型户型阻止创建。

### 6.2 工业扩展

未来空间类型仅是词汇和策略扩展：

| 类型 | 语义 |
| --- | --- |
| `factory` | 工厂根节点 |
| `workshop` | 车间 |
| `production_line` | 产线 |
| `workstation` | 工位 |

禁止现在实现工业模块、OPC UA、设备台账、工艺规则或安全合规策略。表结构不包含家庭专用字段、不使用家庭专用父级硬编码、不把根类型固定为 `home`，即满足本阶段扩展要求。

## 7. 与观测和状态估计的关系

1. Observation 可以携带 `entity_id` 和 `space_id`。
2. 如果观测来自固定传感器，`space_id` 应与观测发生时的实体归属一致。
3. 如果观测描述的是空间本身，例如未来空气质量或区域占用，`space_id` 是观测主体之一。
4. 如果只知道设备不知道现实空间，`space_id` 为空，状态估计必须输出 unknown 或无法空间归因，不得默认塞入默认房间。
5. State Estimate 的空间聚合从 `space_paths` 获取后代空间和实体，不遍历 `devices.area` 字符串。
6. Event 只在状态估计识别到重要变化时生成，并在 payload 中引用 `state_estimate_id`，不把 Event 当作观测来源。

## 8. 隐私和历史保留

1. 空间名称可能包含敏感个人信息，API 返回前沿用现有认证授权边界。
2. 空间归档不等于隐私删除；隐私删除需要通过 ARS-02 的删除任务处理相关观测、估计和派生展示。
3. 贵重物品实体名称默认只对已授权管理界面展示，不进入普通 Agent 工具响应。
4. 用户撤销空间或实体授权后，当前读取必须立即停止，历史数据按属性策略删除或匿名化。
5. 备份中的历史数据必须在隐私设计中显式处理，不能因为备份存在而宣称删除完成。

## 9. 验收边界

Spatial Model 的 ARS-02.1 验收要求：

1. 能创建、查询、更新、移动和归档家庭空间树。
2. 能阻止环、跨树移动、重复 slug 和无效时间区间。
3. 能从 Environment 找到唯一根空间并加载完整树。
4. 能为现有设备创建 Entity 并回填 `devices.entity_id`。
5. 能记录设备当前空间和历史空间区间。
6. 空间移动后，历史观测和状态估计仍可按当时空间解释。
7. 不破坏现有设备控制、事件、任务、安全和控制台回归。

本文件冻结后，ARS-02.1 才能开始实现。
