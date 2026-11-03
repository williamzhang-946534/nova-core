# 22. ARS-02 State Estimation 设计

- 阶段：`ARS-02.0：架构设计与数据契约冻结`
- 日期：2026-11-02
- 状态：设计完成，等待用户确认；本文不是已实现行为
- 范围：估计目标、估计结果、观测溯源、冲突、未知状态和 Environment Context v2
- 禁止事项：本文不修改业务代码、数据库迁移、API、依赖或前端页面

## 1. 设计结论

State Estimate 是 Arvuno 对某个主体、某个属性、在某段时间内现实状态的判断。它可能直接来自一次有效观测，也可能由多个观测派生、由间接证据推断，或者明确承认未知、过期、不可用与冲突。

核心原则：

1. Observation 是证据，不是结论。
2. State Estimate 是当前语义状态的唯一事实源。
3. 每个估计必须能追溯到输入观测、计算规则、生成时间和有效期。
4. 不确定不是失败；把 unknown 伪装成事实才是失败。
5. 不同属性使用不同融合策略，禁止把简单平均作为所有传感器的通用融合规则。
6. Environment Context v2 只读状态估计，不再自行解释 `device_states`。

## 2. 与现有 Environment Context 的关系

当前 `environment/context.py` 主要从设备最新状态生成摘要，并把 JSON 保存到 `environment_snapshots`。它能支持第一阶段控制台，但不能回答：

1. 客厅温度来自哪些传感器。
2. 某个数值是观测值、派生值还是推断值。
3. 证据是否冲突。
4. 传感器离线后当前值是 stale 还是 unknown。
5. 某个空间哪些属性完全没有覆盖。

ARS-02.4 后，`environment_snapshots.context` 只保存 Environment Context v2 的时点投影，不再作为状态计算源。计算顺序变为：

```text
Observations
  → State Estimation Rules
  → state_estimates
  → current_state_estimates
  → Environment Context v2
  → environment_snapshots
```

## 3. 估计目标契约

### 3.1 `estimation_targets`

估计目标定义“要对谁、哪个属性、以什么粒度持续估计”。

| 字段 | 类型 / 约束 | 说明 |
| --- | --- | --- |
| `id` | UUID / PK | 目标 ID |
| `environment_id` | FK → `environments.id` | 所属运行范围 |
| `target_type` | string | `entity`、`space`、`environment` |
| `entity_id` | FK → `entities.id`，nullable | `target_type=entity` 时必填 |
| `space_id` | FK → `spaces.id`，nullable | `target_type=space` 时必填 |
| `attribute` | string | 标准属性 |
| `strategy_id` | string | 融合或推断策略 ID |
| `strategy_version` | string | 策略版本 |
| `enabled` | boolean | 是否启用 |
| `validity_policy` | JSON | 属性、空间和来源的有效期规则 |
| `conflict_policy` | JSON | 差异阈值、候选保留和降级规则 |
| `coverage_policy` | JSON | 判断 unknown / partial coverage 的条件 |
| `created_at` | UTC datetime | 创建时间 |
| `updated_at` | UTC datetime | 更新时间 |

唯一约束：

```text
(environment_id, target_type, entity_id, space_id, attribute)
```

SQLite 对 NULL 在唯一约束中的行为不适合直接表达该规则，工程实现可用哨兵值、部分索引组合或应用层约束，但必须保证同一范围内没有重复活跃目标。

估计目标来源：

1. 设备或传感器登记时自动创建实体级目标。
2. 用户创建房间时自动创建房间常用环境目标，例如温度、湿度、占用。
3. 状态估计规则声明空间级或环境级派生目标。
4. 未注册目标的历史观测不得被静默丢弃，应进入待归类队列或诊断记录。

## 4. 估计结果契约

### 4.1 `state_estimates`

`state_estimates` 是 append-only 历史表。

| 字段 | 类型 / 约束 | 说明 |
| --- | --- | --- |
| `id` | UUID / PK | 估计 ID |
| `target_id` | FK → `estimation_targets.id` | 估计目标 |
| `environment_id` | FK → `environments.id` | 查询和删除用冗余 |
| `status` | string | 七个固定状态之一 |
| `value` | JSON | 标准值或候选值 |
| `unit` | string，nullable | 标准单位 |
| `confidence` | numeric，nullable | 0 到 1；仅当策略有明确语义时使用 |
| `evidence_summary` | JSON | 来源、观测时间、输入数量和候选差异摘要 |
| `conflict_details` | JSON，nullable | 冲突候选、来源、数值和原因 |
| `rule_id` | string | 计算规则 ID |
| `rule_version` | string | 规则版本 |
| `input_cutoff_at` | UTC datetime | 参与计算的最大输入时间 |
| `effective_from` | UTC datetime | 状态语义开始时间 |
| `generated_at` | UTC datetime | 估计生成时间 |
| `valid_until` | UTC datetime，nullable | 状态有效期；未知策略可为空 |
| `superseded_at` | UTC datetime，nullable | 被新估计替代的时间 |
| `created_at` | UTC datetime | 写入时间 |

规则：

1. 已写入结果不更新。修正或重算生成新行，并给旧行写 `superseded_at`。
2. `confidence` 不是必须字段。没有明确概率模型时使用证据质量、来源数量和覆盖情况表达，不虚构百分比。
3. `conflict_details` 必须保留互相矛盾的证据，不能只保存胜者。
4. `effective_from` 来自输入观测或规则时间；`generated_at` 只表示计算时间。
5. `valid_until` 可以由属性时效、来源心跳和策略共同决定。

### 4.2 `state_estimate_observations`

| 字段 | 类型 / 约束 | 说明 |
| --- | --- | --- |
| `estimate_id` | FK → `state_estimates.id` | 估计结果 |
| `observation_id` | FK → `observations.id` | 输入观测 |
| `contribution` | string | `direct`、`candidate`、`context`、`negative_evidence` |
| `weight` | numeric，nullable | 策略计算使用的权重 |
| `exclusion_reason` | string，nullable | 收到但被排除的原因 |
| `created_at` | UTC datetime | 关联时间 |

主键为 `(estimate_id, observation_id)`。

要求：

1. `observed`、`derived` 和正常 `inferred` 估计必须有关联输入；无法关联时状态不能高于 unknown。
2. `conflict` 至少保留两个互斥候选的输入。
3. `stale` 保留上一次有效输入，同时记录过期原因。
4. `unavailable` 可关联离线观测；完全没有任何历史输入时可保持 unknown。
5. 观测按保留策略删除后，历史估计保留 `evidence_summary`，输入链接随删除策略移除；这是可追溯性的显式边界，不得隐藏。

### 4.3 `current_state_estimates`

这是可重建的当前读模型，每个活跃估计目标一行。

| 字段 | 说明 |
| --- | --- |
| `target_id` | 估计目标，主键 |
| `latest_estimate_id` | 最新未替代估计 |
| `status` / `value` / `unit` / `confidence` | 查询用冗余 |
| `valid_until` | 当前有效期 |
| `refreshed_at` | 最近刷新时间 |
| `projection_version` | 投影版本 |

规则：

1. 只通过事务或投影器从 append-only 历史更新。
2. 损坏或缺失时可由 `state_estimates` 重建。
3. 查询当前状态优先读该表；审计和解释跳转历史表。
4. 到期状态不靠后台任务才变成 stale，查询层必须按 `valid_until` 降级展示。

## 5. 状态集合

状态集合固定为以下七个，不得新增“大概”“正常”等口语状态。

| 状态 | 语义 | 进入条件示例 |
| --- | --- | --- |
| `observed` | 一个合格观测直接描述该属性 | 门磁返回 `open`；单一有效温度计读数 |
| `derived` | 多个观测或已有量按明确规则计算 | 多个温度传感器加权中位数得到房间温度 |
| `inferred` | 由间接证据推出，不是直接测量 | 空调反馈运行且温度趋势下降，推断正在降温 |
| `unknown` | 系统没有足够证据，或覆盖不足 | 房间没有占用传感器；PIR 未覆盖全屋时不能推出无人 |
| `stale` | 有历史证据但已超过有效期 | 温度计 2 小时无更新 |
| `unavailable` | 明确收到来源、实体或能力不可用 | HA 报告实体 unavailable |
| `conflict` | 多个可信证据在同一时间语义下矛盾 | 两个门传感器对同一门给出相反状态 |

### 5.1 状态优先级

这不是全局硬编码优先级，而是决策顺序：

1. 先检查输入完整性和授权，未授权输入视为不存在。
2. 再检查 `unavailable` 是否有明确不可用证据。
3. 再检查 `conflict` 是否达到属性冲突阈值。
4. 再判断有效观测是否足够；不足则 `unknown`。
5. 有效但过期时输出 `stale`，不得继续把旧值标成 observed。
6. 单一直接证据输出 `observed`。
7. 多源计算或间接推理分别输出 `derived` 或 `inferred`。

### 5.2 状态迁移

| 原状态 | 常见后续 | 约束 |
| --- | --- | --- |
| `observed` | `observed`、`derived`、`stale`、`unavailable`、`conflict` | 新证据矛盾时不得静默覆盖 |
| `derived` | `derived`、`observed`、`stale`、`unknown`、`conflict` | 输入减少时必须重算覆盖和置信语义 |
| `inferred` | 任意状态 | 证据链变化时不得保留旧结论 |
| `unknown` | `observed`、`derived`、`inferred`、`unavailable` | 新增传感器后应自动补建目标 |
| `stale` | `observed`、`derived`、`unknown`、`unavailable`、`conflict` | 恢复更新后重新生成，不复活旧行 |
| `unavailable` | `observed`、`unknown`、`stale` | 必须区分来源恢复和历史值过期 |
| `conflict` | 任意状态 | 冲突解除必须说明哪个证据失效或被替代 |

## 6. 溯源要求

任何非 unknown 估计的 API 响应必须能展开：

```json
{
  "status": "derived",
  "value": 23.4,
  "unit": "°C",
  "rule": {
    "id": "room_temperature_median_v1",
    "version": "1.0.0"
  },
  "evidence": [
    {
      "observation_id": "...",
      "source_id": "...",
      "entity_id": "...",
      "observed_at": null,
      "received_at": "2026-11-02T08:00:00Z",
      "value": 23.5,
      "quality_status": "warning"
    }
  ],
  "generated_at": "2026-11-02T08:00:02Z",
  "valid_until": "2026-11-02T08:10:00Z"
}
```

解释必须区分：

1. 观测发生时间：可能未知。
2. Arvuno 收到时间：永远存在。
3. 估计生成时间：规则执行时间。
4. 状态有效期：策略判断结果。

## 7. 融合策略

### 7.1 策略注册

每个属性至少声明一个策略 ID 和版本。策略输入包括观测质量、时间、来源信任、传感器安装位置、空间覆盖和属性语义。

禁止实现“所有传感器取平均”的通用策略。简单平均只在明确声明适用范围、权重和异常处理的情况下，可以作为某个具体策略的一部分。

### 7.2 家庭属性初始策略

| 属性 | 初始策略 | 关键规则 |
| --- | --- | --- |
| `temperature` | 加权中位数 / 截尾融合 | 按来源质量、时间衰减、安装位置加权；单传感器直接 observed；差异超阈值输出 conflict；不用简单平均 |
| `humidity` | 加权中位数 | 与温度类似，范围和跳变阈值独立配置 |
| `motion` | 事件式正证据优先 | 任一覆盖内有效传感器 `true` 可推出 detected；`false` 只表示未检测到运动，不等于无人 |
| `occupancy` | 覆盖感知推断 | 有人需要正证据或足够多模态证据；无人必须满足完整覆盖、全部新鲜负证据和规则版本 |
| `contact` | 最新直接观测优先 | 同一门的多个直接传感器冲突时输出 conflict；不能用新旧值平均 |
| `illumination` | 空间代表性中位数或用途场景值 | 根据传感器位置和用途选择，不混合不适合比较的安装点 |
| `co2` | 加权中位数 / 趋势保留 | 异常跳变先降质量，不立即覆盖合理值 |
| `device_availability` | 适配器直接状态优先 | 区分设备不可达、HA 实体 unavailable 和 Arvuno 未轮询 |
| `actuator_state` | 反馈优先、命令上下文 | 反馈与命令矛盾输出 conflict；不能把命令当现实完成状态 |

### 7.3 二进制和枚举规则

1. 二进制和枚举值不得平均。
2. 多数投票只能作为明确声明的策略，且必须有最低证据数量、覆盖和一致性要求。
3. `on/off`、`open/closed`、`occupied/unoccupied` 冲突时优先输出 conflict。
4. PIR `false` 不是 `occupancy=unoccupied`。它只是该传感器视野内在检测窗口内没有观察到运动。
5. 负证据必须声明覆盖范围；覆盖不足时输出 unknown。

## 8. 冲突处理

冲突估计必须保留：

1. 每个候选值、单位和来源。
2. 每个候选的观测时间、接收时间和质量。
3. 阈值和规则版本。
4. 是否存在策略选择的展示值。
5. 冲突开始时间和持续时间。

策略可以选择一个供自动化使用的候选值，但 API 和前端必须显示 conflict，不能把选择后的值伪装成 observed。安全相关属性默认不自动选择，应等待新证据或用户裁决。

## 9. 未知、盲区和覆盖

Coverage 由三部分组成：

1. 注册覆盖：该空间和实体登记了哪些可观测属性。
2. 当前覆盖：来源当前是否可用、授权和新鲜。
3. 语义覆盖：证据能否支撑目标属性，例如 PIR 不能覆盖“无人”结论。

输出可以使用：

| 覆盖 | 含义 |
| --- | --- |
| `covered` | 有足够当前证据 |
| `partial` | 有证据但空间或时间覆盖不足 |
| `blind` | 从未具备观测能力 |
| `lost` | 曾有覆盖但来源失联或授权撤销 |

Coverage 不是第八种估计状态，而是解释 unknown、stale 和 unavailable 的依据。

## 10. Environment Context v2

### 10.1 输出结构

Environment Context v2 是只读投影，按空间树组织：

```json
{
  "environment_id": "...",
  "root_space_id": "...",
  "generated_at": "2026-11-02T08:00:03Z",
  "spaces": [
    {
      "space_id": "...",
      "path": ["home", "1f", "living-room"],
      "state": {
        "temperature": {
          "status": "derived",
          "value": 23.4,
          "unit": "°C",
          "valid_until": "..."
        },
        "occupancy": {
          "status": "unknown",
          "coverage": "partial"
        }
      },
      "coverage": {
        "covered_attributes": ["temperature", "humidity"],
        "unknown_attributes": ["occupancy"],
        "lost_attributes": []
      }
    }
  ],
  "entities": [],
  "quality_summary": {
    "conflict_count": 0,
    "stale_count": 1,
    "unavailable_count": 0
  }
}
```

### 10.2 规则

1. Context 不访问原始 Adapter，不直接读 `device_states`。
2. Context 不生成新的事实状态；所有状态必须来自 `current_state_estimates`。
3. Context 可以聚合、过滤、排序和生成交互摘要。
4. `environment_snapshots` 保存投影和任务关联，不作为恢复当前状态的唯一来源。
5. Agent 环境输入使用摘要和有限 provenance；需要完整观测时调用只读 Tool。
6. 前端显示 unknown、stale、unavailable 和 conflict，不能把这些状态渲染成普通正常值。

## 11. Event 和 Snapshot 边界

1. Event 在估计状态发生重要变化时发布，例如 observed → conflict、unknown → occupied。
2. Event payload 引用 `state_estimate_id` 和 `target_id`，不复制完整观测历史。
3. 高频数值抖动必须经过阈值和冷却，避免事件风暴。
4. Snapshot 是 `generated_at` 时的投影，不用于纠正后续状态。
5. Memory 未来只能引用状态估计或其摘要，不得把每条观测自动提升为长期记忆。

## 12. 验收边界

State Estimation 的 ARS-02.4 验收要求：

1. 七个状态均有自动化测试和 API 可见语义。
2. 每个非 unknown 估计可追溯输入观测、规则版本、生成时间和有效期。
3. 冲突证据不被胜者覆盖。
4. PIR `false` 不产生无人结论。
5. 二进制和枚举属性没有平均计算。
6. Environment Context v2 与当前估计一致，且不直连 Adapter 或 Repository。
7. 重启后当前投影可恢复或重建，历史估计不被重复生成。

本文冻结后，才能进入 ARS-02.4 工程实现。
