# 24. ARS-02 Testing and Acceptance

- 阶段：`ARS-02.0：架构设计与数据契约冻结`
- 日期：2026-11-02
- 状态：设计完成，等待用户确认；本文不是已实现行为
- 范围：ARS-02 测试策略、里程碑验收和最终验收
- 禁止事项：本文不修改业务代码、数据库迁移、API、依赖、测试或前端页面

## 1. 测试原则

1. 以真实代码和迁移结果为准，不以文档存在代替实现。
2. Mock 通过只能证明软件契约，不能冒充真实 Home Assistant 或硬件验收。
3. 时间、来源、质量和未知状态是 ARS-02 的一级测试对象。
4. 每个里程碑必须运行后端全量回归；涉及前端时运行类型检查和构建。
5. 涉及数据库迁移必须验证升级、回滚、备份恢复和数据量检查。
6. 不允许通过降低安全要求、跳过断言或改写期望来获得通过。

## 2. 迁移与 Schema 测试

### ARS-02.1

1. 空数据库创建空间树成功。
2. 已有 Environment 获得 `root_space_id`，且只有一个根。
3. 空间唯一约束、父级索引和路径索引存在。
4. 迁移可回滚，回滚后现有设备控制表不受破坏。
5. 迁移前后设备数、环境数、快照数一致。
6. 备份文件可恢复并通过完整性检查。

### ARS-02.2 / 02.3

1. 每个现有 Device 生成一个 Entity，`devices.entity_id` 回填完整且无孤儿 Device。
2. Observation 必填字段和 nullable 语义与第 21 号文档一致。
3. `dedupe_key` 唯一约束生效。
4. 授权、属性策略、来源和删除任务表存在。
5. 旧 `device_states` 迁移后不被重写。
6. 大量回填分页、可重跑、可中断。

### ARS-02.4 / 02.5

1. 估计表、输入链接和当前读模型唯一约束生效。
2. Snapshot 新增版本字段后，旧快照仍可读并标记为 v1。
3. 当前读模型可从历史估计重建。
4. API 权限、错误契约和 OpenAPI 类型完整。

## 3. Spatial Model 测试

必须覆盖：

1. 创建 `home → floor → room → zone`。
2. 简化树 `home → room` 和 `room → zone`。
3. 根节点必须有唯一 Environment。
4. 非根节点必须有父节点。
5. 禁止自己成为父节点、祖先成为子孙、跨树移动。
6. 兄弟节点 slug 冲突被拒绝。
7. 移动空间后，自身和所有后代路径同事务更新。
8. 移动失败时后代路径不出现半更新。
9. 归档空间不再接收新观测，但历史查询可用。
10. `factory → workshop → production_line → workstation` 可通过类型配置表达，但不触发工业功能。

## 4. Entity 与空间归属测试

1. Device 与 Entity 一对一回填。
2. 设备更换后默认生成新 Device，不自动继承旧 Entity。
3. 用户显式把新 Device 绑定旧 Entity 后，历史查询连续。
4. 固定安装位置只有一个当前 `fixed_installation` 区间。
5. 移动设备时旧区间关闭、新区间创建。
6. 时间区间重叠被拒绝。
7. `valid_until` 必须晚于 `valid_from`。
8. 查询当前空间和查询历史时间返回不同结果。
9. 传感器移动后，旧观测仍按旧空间解释。
10. 无法判断历史位置时返回 unknown，不猜测。

## 5. Observation 测试

### 5.1 契约

每条观测必须验证：

1. `observation_id`、`source_id`、`source_type`。
2. Entity 或 Subject 至少一组。
3. `space_id` 只在真实适用时填写。
4. `attribute` 来自受控词汇表。
5. raw / normalized 值和单位语义。
6. `observed_at`、`received_at`、`processed_at` 分离。
7. `quality_status` 和 `quality_issues`。
8. `valid_from` / `valid_until`。
9. freshness 评估依据。
10. `correlation_id`、`external_id`、`dedupe_key`。

### 5.2 时间

1. 设备提供可信 UTC 时间时保存。
2. HA 仅轮询时 `observed_at = null`，不复制 `received_at`。
3. HA `last_changed` / `last_updated` 语义分别测试。
4. 无时区字符串按显式规则转换，不依赖本机时区。
5. 未来时间、过早时间、明显漂移时间产生 warning 或 invalid。
6. API 同时展示采集时间和接收时间；采集时间未知必须可见。

### 5.3 标准化与质量

1. Fahrenheit 转摄氏。
2. 百分比湿度转 `%RH`。
3. HA `on/off`、`open/closed`、`unavailable` 映射。
4. 超范围、类型错误、缺失单位、缺失主体被拒绝或降级。
5. 延迟观测保留原时间并标记延迟。
6. 跳变观测保留原值并标记 warning，不静默修正。
7. 无法标准化时 raw 保留、normalized 为空。
8. 标准化规则版本写入。

### 5.4 去重和采样

1. 同一 `external_id` 重试不产生新行。
2. 同一轮询批次相同 payload 只保留一条。
3. 跨批次无变化数据按策略节流。
4. 温度变化低于阈值可丢弃并计数。
5. 门磁状态变化、急停、控制反馈、安全相关状态不得被采样吞掉。
6. 重复率指标正确。

## 6. Pipeline 测试

1. Mock Adapter 输出进入 Observation Pipeline。
2. HA Adapter 输出不直接写 Repository。
3. Source 不存在、未启用或授权撤销时拒绝。
4. 管线批量事务失败后重试不重复入库。
5. 处理中崩溃重启后 pending 数据可恢复或明确丢弃并计数。
6. Observation、兼容投影和 Event 不出现同一状态三写。
7. `EnvironmentReconciler` 不再通过事件服务重复记录状态。
8. HA 断线、超时、5xx、实体 unavailable 分别有质量结果。
9. 轮询恢复后不会把整段断线前的旧值伪装为新观测。
10. 管线指标覆盖 accepted、deduplicated、sampled、invalid、error。

## 7. State Estimation 测试

### 7.1 七状态

| 状态 | 必测场景 |
| --- | --- |
| `observed` | 单个新鲜直接观测 |
| `derived` | 多个温度传感器按属性策略计算 |
| `inferred` | 间接证据推出结论且证据链可见 |
| `unknown` | 无传感器、授权撤销、覆盖不足 |
| `stale` | 有历史值但超过有效期 |
| `unavailable` | 来源或实体明确不可用 |
| `conflict` | 多个可信直接观测矛盾 |

必须测试状态迁移：

1. `observed → stale`
2. `unknown → observed`
3. `observed → conflict`
4. `conflict → observed`
5. `unavailable → observed`
6. `stale → unknown`
7. `derived → unknown`
8. 重算不修改旧行，只替代当前读模型。

### 7.2 溯源

1. 每个非 unknown 估计链接输入观测。
2. 规则 ID 和版本完整。
3. `effective_from`、`generated_at`、`valid_until` 语义正确。
4. 冲突保留全部候选。
5. 被排除观测有 exclusion reason。
6. Observation 删除后，历史估计保留证据摘要且链接移除。

### 7.3 融合

1. 温度使用声明策略，不做全局平均。
2. 单传感器直接 observed，不伪装 derived。
3. 异常值按策略降权、隔离或冲突。
4. 二进制值禁止平均。
5. 门传感器冲突不能靠最新时间静默覆盖。
6. PIR `false` 不产生无人结论。
7. 只有一个未覆盖全房的 PIR 时 occupancy 为 unknown 或 partial。
8. 命令与执行反馈冲突输出 conflict。
9. 多传感器湿度和温度使用独立阈值。

## 8. Environment Context v2 测试

1. Context 状态与 `current_state_estimates` 完全一致。
2. Context 不访问 Adapter 或 `device_states`。
3. 空间树包含所有活跃空间。
4. 子空间状态可正确聚合到父空间。
5. unknown、stale、unavailable、conflict 不被渲染或序列化为普通值。
6. Snapshot 保存的是时点投影，不影响后续状态。
7. Context v1 与 v2 过渡期可并存。
8. 重启后当前状态可从读模型或历史重建。
9. Agent 输入只包含授权和最小化后的摘要。

## 9. API 与前端测试

API：

1. 认证和权限边界。
2. 空间 CRUD、移动和归档。
3. 实体绑定和历史归属。
4. Observation 分页、过滤和 raw 默认隐藏。
5. 估计详情和 evidence 展开。
6. 覆盖查询。
7. 删除任务创建、取消和状态。
8. OpenAPI 与 Pydantic 契约一致。
9. 错误响应沿用现有结构。

前端：

1. 空间树创建、移动和错误提示。
2. 房间状态和状态徽章。
3. 来源抽屉显示采集时间与接收时间。
4. 采集时间未知不显示为接收时间。
5. 覆盖视图区分 blind 和 lost。
6. 冲突列表和候选来源。
7. 质量和来源健康。
8. 移动端布局不重叠、不溢出。
9. 前端类型检查和构建通过。

## 10. 安全与隐私测试

1. Agent 无法直接访问 Repository 或 Adapter。
2. 只读 Tool 无法触发写入、重算或删除。
3. 敏感属性未授权时来源层拒绝。
4. 授权撤销后当前读取立即停止。
5. 删除任务处理 Observation、估计链接、Event payload、Snapshot 和日志。
6. raw 调试访问被审计。
7. 备份恢复后已删除数据按备份策略暴露，系统不虚假报告“所有副本已消失”。
8. 贵重物品或敏感实体默认不出现在普通环境摘要。
9. 删除任务可分批、可重试、可审计。

## 11. 性能与可靠性测试

基准场景：

1. 20 个传感器，5 分钟一条。
2. 50 个传感器，1 分钟一条。
3. 压力场景 200 个传感器，10 秒一条但启用采样。

必须测量：

1. 每秒写入和事务耗时。
2. SQLite 锁等待和 busy timeout。
3. WAL 大小和 checkpoint。
4. 磁盘占用增长率。
5. 当前状态查询 P95。
6. 空间树查询 P95。
7. 证明详情查询 P95。
8. 保留删除耗时。
9. 断线重连后的补齐行为。
10. 重启后 pending、队列和当前投影恢复。

性能验收不是追求无限写入，而是证明默认采样和保留策略在目标家庭规模内稳定。

## 12. 回归测试

每个里程碑至少运行：

1. 后端全量测试。
2. Ruff 格式与静态检查。
3. Alembic 升级 / 回滚测试。
4. 架构边界测试。
5. 现有设备控制链路测试。
6. Task、Tool、Safety、审计链路测试。
7. Event 和通知测试。
8. 涉及前端时运行 TypeScript 类型检查、构建和格式检查。

必须确认：

1. Home Assistant 读 / 写安全链路不回归。
2. Mock 控制链路不回归。
3. 现有 `/api/environment` 兼容。
4. 控制台现有页面不破坏。
5. 日志脱敏不回归。

## 13. 分层验收

### ARS-02.1 Spatial Model 验收

1. 家庭空间树可用。
2. Environment 与 Space 职责分离。
3. Entity 和 Device 关系完成迁移。
4. 历史空间归属可追溯。
5. 迁移和全量回归通过。

### ARS-02.2 Entity / Observation 验收

1. Observation Schema 冻结字段全部实现。
2. HA 与 Mock 可产生标准观测。
3. 时间语义不造假。
4. 隐私策略表可用。
5. 旧状态历史不被重复写入。

### ARS-02.3 Pipeline 验收

1. 单一写入所有权完成。
2. 幂等、采样、去重、质量标记可用。
3. 重复写路径修复。
4. 保留任务和写入指标可用。
5. SQLite 基准通过。

### ARS-02.4 State Estimation 验收

1. 七状态完整。
2. 溯源完整。
3. 属性融合策略版本化。
4. Conflict 和 unknown 不被掩盖。
5. Environment Context v2 切换完成。

### ARS-02.5 API / Tool / Console 验收

1. 空间、实体、观测、估计和覆盖 API 可用。
2. Agent 只读 Tool 经过 Registry、Safety 和 Executor。
3. 前端可管理空间并解释状态来源。
4. 隐私和删除入口可用。
5. API 与前端契约测试通过。

### ARS-02.6 真实硬件验收

1. 真实 HA 传感器持续上报。
2. 至少覆盖温度、湿度或照度一类连续量。
3. 至少覆盖 motion、contact 或 occupancy 一类状态量。
4. 真实断线重连和时钟语义验证。
5. 明确记录哪些来源无法提供采集时间。
6. 不把 Mock 结果记为硬件通过。

### ARS-02.7 最终验收

1. 全量回归通过。
2. 迁移、备份、恢复通过。
3. 家庭空间、实体、观测、估计和 Context v2 闭环可用。
4. 七状态、溯源、覆盖和隐私验收全部通过。
5. SQLite 性能和存储增长满足目标家庭规模。
6. Web Console 可解释当前环境和未知项。
7. 无未授权敏感数据进入 Agent 摘要。
8. 输出 ARS-02 Acceptance Report。

## 14. 通过 / 未通过口径

| 项目 | 通过条件 |
| --- | --- |
| 设计实现 | 与已确认契约一致，字段语义没有缺失 |
| 时间语义 | 没有伪造采集时间 |
| 写入所有权 | Observation / 兼容投影 / Event 无重复历史写入 |
| 状态估计 | 七状态、溯源和有效期全部可见 |
| 融合 | 属性策略独立且版本化，无通用平均 |
| 空间追溯 | 移动后历史解释正确 |
| 隐私 | 授权、撤销、删除和备份边界可审计 |
| 性能 | 目标家庭规模稳定，保留策略可控 |
| 回归 | 现有安全控制链路无破坏 |

本文件冻结后，ARS-02.1 才能开始实现。
