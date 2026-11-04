# 25. ARS-02.6 真实 ESPHome / ESP32 传感器验收

- 日期：2026-11-04
- 分支：`main`
- 基线提交：`a1b96f0`
- 结论：**软件接口验收通过；真实 ESPHome / ESP32 硬件验收未执行**
- 原因：用户明确说明当前没有真实 ESP32 和相关传感器
- 安全边界：Home Assistant 写操作保持关闭，未开放无关控制权限，未修改 Tool Executor 或 Safety Policy 语义

## 1. 验收范围

本报告区分两类结果：

1. **Mock 软件链路**：验证 Arvuno 自有 Observation Pipeline、状态估计和时间/质量语义。
2. **Home Assistant Demo 软件链路**：验证真实 HA REST Adapter 到 Device Registry、Observation Pipeline 和 State Estimation 的软件接口。
3. **真实 ESPHome / ESP32**：全部标记为未执行，不使用 Mock 或 HA Demo 结果替代。

本次没有采购设备，没有修改业务代码、数据库迁移、依赖、前端页面、适配器或安全执行链路。

## 2. 隔离执行环境

为避免影响日常数据库，验收使用独立临时目录和端口：

- SQLite、日志和备份目录均指向 Windows 临时目录下的 `arvuno-ars026-20261104-095442`。
- 后端使用端口 `8001`。
- AI Provider 使用 `mock`。
- Home Assistant 写开关为 `false`。
- 仅在进程环境变量中扩展 HA Demo allowlist，未修改 `.env`。
- 进程内 allowlist 覆盖：
  - `sensor.outside_temperature`
  - `sensor.outside_humidity`
  - `binary_sensor.movement_backyard`
  - `light.bed_light`

空数据库按 Alembic 迁移链升级到当前 head，覆盖 Phase 2、ARS-02 Spatial Model、Observation Model、Observation Pipeline 和 State Estimation 迁移。后端随后重启一次，重启后观测和状态读模型继续可查询。

## 3. 软件接口验收结果

### 3.1 Mock Adapter

| 项目 | 结果 | 说明 |
| --- | --- | --- |
| Adapter 健康 | 通过 | `/api/system/status` 返回 `mock=healthy` |
| Device Registry | 通过 | 同步 6 台 Mock 设备，全部在线 |
| Observation Pipeline | 通过 | Mock 状态转换进入 Observation，不直接依赖 Repository 以外的写入路径 |
| 来源身份 | 通过 | Mock Adapter 形成独立 `adapter` source；观测通过 `source_id` 与 Entity 关联 |
| 时间语义 | 通过 | Mock 无可靠采集时间时 `observed_at=null`，记录 `observed_at_source=poll_clock`，不伪造采集时间 |
| 温度标准化 | 通过 | raw `24.50 C`、normalized `24.50 °C` |
| 湿度标准化 | 通过 | raw `55 %`、normalized `55 %RH` |
| 质量标记 | 通过 | 因缺少可靠采集时间标记 `warning`，未静默视为普通高质量观测 |
| State Estimation | 通过 | 温度和湿度在新鲜窗口内为 `observed`，证据可追溯 Observation、source、rule 和有效期 |
| 采样节流 | 通过 | 轮询 30 秒、温湿度最小保存间隔 60 秒；相同数值按策略每分钟保存一次 |

### 3.2 Home Assistant Demo

| 项目 | 结果 | 说明 |
| --- | --- | --- |
| HA 连接 | 通过 | `http://localhost:8123` 可达，token 有效，`home_assistant=healthy` |
| Device Registry | 通过 | 只同步进程 allowlist 内 4 个实体，未导入 HA 全量实体 |
| Observation Pipeline | 通过 | HA REST 状态经统一 Adapter 映射进入 Observation |
| 来源身份 | 通过 | HA Adapter 形成独立 `adapter` source，Entity 保留 Arvuno 内部实体 ID |
| 时间语义 | 通过 | 保留 HA `gateway_state_clock` 时间，记录 `observed_at_uncertainty_ms=1000` |
| 延迟/过期处理 | 通过 | Demo 实体的网关时间明显落后，观测为 `warning`，State Estimate 为 `stale` |
| 温度 | 通过 | HA raw `15.60 °C`，估计 `15.6 °C`，状态 `stale`，证据排除原因为 `evidence_expired` |
| 湿度 | 通过 | HA raw `54 %`，normalized `54 %RH`，估计 `stale` |
| Motion | 通过 | HA raw `detected`，normalized `True`，估计 `stale` |
| Actuator 观测 | 通过 | `light.bed_light` 产生 `actuator_state` 和 availability 观测；本项只验证只读链路 |

### 3.3 状态估计与环境上下文

查询时点状态：

- State Estimate 总数：23。
- 状态分布：`observed=2`、`stale=18`、`unknown=3`。
- 目标分布：entity=20、space=3。
- Context v2 quality：`stale_count=9`、`unknown_count=3`、`conflict_count=0`、`unavailable_count=0`。
- HA 温度证据包含 `source_id`、`observation_id`、`observed_at_source=gateway_state_clock`、`weight` 和 `exclusion_reason=evidence_expired`。
- Mock 温度证据包含 `source_id`、`observation_id`、`observed_at_source=poll_clock`、`weight`、rule 和有效期。

一致性检查：

| 检查 | 结果 |
| --- | --- |
| `/api/devices` 设备总数 | 10 |
| `/api/devices` 在线数 | 10 |
| `/api/system/status` 设备总数 | 10 |
| `/api/system/status` 在线数 | 10 |
| `/api/environment` 在线数 | 10 |
| unavailable 数量 | 0 |
| Adapter 状态 | `mock=healthy`、`home_assistant=healthy` |

`/api/environment` 继续提供兼容的设备在线性摘要；Context v2 基于 State Estimation 输出空间质量。当前隔离数据库尚未把设备绑定到空间，因此 Context v2 root 下 entities 为空、空间级温度/湿度/occupancy 为 `unknown`，这是空间归属缺失时的正确保守结果，不是状态估计错误。

### 3.4 Tool Registry 与安全边界

1. `get_environment_state` 通过 `/api/tools/get_environment_state/execute` 执行：
   - 状态：`completed`
   - 风险：`read_only`
   - 授权：`allowed`
   - 返回 root 空间 temperature、humidity、occupancy 为 `unknown`
   - 返回相关 coverage 为 `blind`
   - 未绕过 Tool Registry、Safety Policy 或 Tool Executor
2. `control_device` 尝试关闭 HA Demo `light.bed_light`：
   - 结果：请求被拒绝
   - 错误码：`STATE_CONFLICT`
   - 错误信息：`Device write operations are disabled.`
   - 结论：未向 Home Assistant 发送写命令，写关闭边界保持有效

### 3.5 回归与静态检查

| 检查 | 命令/范围 | 结果 |
| --- | --- | --- |
| 后端全量回归 | `python -m pytest` | `228 passed`，1 个既有 Starlette TestClient deprecation warning |
| Ruff lint | `python -m ruff check .` | 通过 |
| Ruff format | `python -m ruff format --check .` | 158 个文件已符合格式 |
| Alembic 启动迁移 | 隔离空 SQLite 升级到 head | 通过 |
| 重启恢复 | 同一隔离 SQLite 重启后查询 | 通过 |
| 前端构建 | 未执行 | ARS-02.6 未修改前端代码，不属于本阶段验收项 |

## 4. 真实 ESPHome / ESP32 验收

以下项目均因没有物理硬件而**未执行**。它们不能由 Mock、HA Demo、自动化测试或本报告第 3 节结果替代。

| 序号 | 真实硬件验收项 | 结果 |
| --- | --- | --- |
| H1 | ESP32 / ESPHome 节点连接 Wi-Fi | 未执行 |
| H2 | Home Assistant 发现 ESPHome 设备 | 未执行 |
| H3 | Home Assistant 读取真实传感器状态 | 未执行 |
| H4 | Arvuno 获取对应真实 HA 设备和实体 | 未执行 |
| H5 | Observation Pipeline 接收真实设备观测 | 未执行 |
| H6 | 真实来源身份正确 | 未执行 |
| H7 | 真实采集时间 / 接收时间正确 | 未执行 |
| H8 | 真实单位正确并完成标准化 | 未执行 |
| H9 | 真实数据更新后 State Estimation 刷新 | 未执行 |
| H10 | 真实设备断线产生正确状态 | 未执行 |
| H11 | 真实设备恢复后重新同步 | 未执行 |

真实硬件执行时还必须记录：

1. ESPHome 节点型号、传感器型号和固件版本。
2. HA 实体 ID、device class 和单位。
3. ESPHome、HA 和 Arvuno 的时间戳差异。
4. Arvuno Observation 的 raw/normalized、unit、quality、freshness 和来源。
5. State Estimate 的输入观测、规则、状态变化和有效期。
6. 断线开始、检测到 unavailable、恢复后重新同步的时间线。
7. Wi-Fi 信号、轮询间隔、SQLite 写入量和保留清理结果。

## 5. 风险和未确定事项

1. HA Demo 不提供 ESPHome discovery、Wi-Fi、真实传感器时钟和真实断线/重连行为，因此不能证明硬件路径。
2. HA Demo 的 Demo 实体时间长期滞后。系统正确输出 `warning` 和 `stale`，但真实 ESPHome 的 `last_updated` / `last_changed` 稳定性仍需硬件验证。
3. 当前事件型状态在长时间无新 Observation 后可能进入 `stale`。该行为符合“没有新鲜证据就不能宣称确定状态”的保守口径，但真实家庭中 contact/motion/occupancy 的可用性策略需要在 ARS-02.7 最终验收时明确。
4. 本次隔离数据库未绑定设备空间，Context v2 正确返回空间级 unknown/blind；真实硬件验收前应先建立楼层、房间和设备归属。
5. 隐私删除、目标家庭规模 SQLite 长期压测、真实断线补偿和长时间保留清理不属于本次硬件前置软件验收。
6. Observation 的 `external_id` 在无外部观测 ID 时为空；来源身份由 `source_id` + Arvuno Entity ID 表达。真实 ESPHome 接入后需要复验该语义与 HA entity ID 投影的对应关系。

## 6. 结论

ARS-02.6 的**软件接口验收通过**：Mock 与 HA Demo 分别验证了 Device Registry、Observation Pipeline、来源追踪、时间/单位/质量语义、State Estimation 刷新、Context v2、只读 Tool 和写关闭边界。

ARS-02.6 的**真实 ESPHome / ESP32 硬件验收未执行**。在用户提供 ESP32 和相关传感器之前，不得把 ARS-02 标记为包含真实硬件验收完成，也不得据此开放设备写权限。
