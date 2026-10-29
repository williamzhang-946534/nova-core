# 07. 设备适配层设计

## 目标

设备适配层负责将外部设备平台转换为 Arvuno 的统一设备接口。它是 Home Assistant 与 Arvuno 核心领域之间的防腐层。

Agent、Task System 和 Tool Executor 不允许直接调用 Home Assistant API。

## 责任边界

| 能力 | 归属 | Arvuno 处理 |
| --- | --- | --- |
| 设备发现、集成和协议适配 | Home Assistant | 不实现 |
| 完整设备注册和配置 | Home Assistant | 不复制 |
| 当前状态查询和设备控制 | Home Assistant | 通过 Adapter 标准化 |
| 完整设备历史和统计图表 | Home Assistant | 不复制 |
| 基础自动化和场景 | Home Assistant 优先 | 不做通用替代品 |
| Arvuno 设备 ID、别名、权限和能力摘要 | Arvuno | 保存轻量投影 |
| 任务、工具和审计记录 | Arvuno | 独立保存 |

## 核心接口

第一阶段定义以下异步接口：

```python
class DeviceAdapter(Protocol):
    adapter_id: str
    version: str

    async def health_check(self) -> AdapterHealth: ...

    async def get_devices(self) -> list[Device]: ...

    async def get_device(self, external_id: str) -> Device: ...

    async def get_state(self, external_id: str) -> DeviceState: ...

    async def execute_action(
        self,
        external_id: str,
        action: DeviceAction,
    ) -> ActionResult: ...

    async def subscribe_events(
        self,
        subscriber: DeviceEventSubscriber,
    ) -> SubscriptionHandle: ...
```

该代码是接口规范，不代表当前阶段应实现业务代码。

## 标准模型

### Device

| 字段 | 说明 |
| --- | --- |
| external_id | 适配器内唯一 ID |
| name | 设备名称 |
| device_type | Arvuno 标准类型 |
| area | 区域 |
| capabilities | 能力列表 |
| risk_level | 默认风险 |
| is_online | 在线状态 |
| metadata | 平台元数据摘要 |

### DeviceType

第一阶段建议类型：

- `light`
- `switch`
- `sensor_temperature`
- `sensor_humidity`
- `sensor_motion`
- `sensor_contact`
- `climate`
- `media_player`
- `unknown`

后续可以扩展，但 `unknown` 不允许执行动作。

### DeviceState

| 字段 | 说明 |
| --- | --- |
| external_id | 设备外部 ID |
| state | 标准状态 |
| attributes | 标准属性 |
| raw_state | 原始状态摘要 |
| observed_at | 观察时间 |

标准状态示例：

- `on`
- `off`
- `unavailable`
- `unknown`
- `open`
- `closed`
- `detected`
- `clear`

### DeviceCapability

| 字段 | 说明 |
| --- | --- |
| capability | 能力类型 |
| actions | 支持动作 |
| parameters | 参数 Schema |
| risk_level | 风险等级 |
| requires_confirmation | 是否需要确认 |

### DeviceAction

| 字段 | 说明 |
| --- | --- |
| action | 标准动作名 |
| parameters | 已校验参数 |

标准动作示例：

- `turn_on`
- `turn_off`
- `toggle`
- `set_brightness`
- `set_temperature`
- `read_state`

### ActionResult

| 字段 | 说明 |
| --- | --- |
| success | 是否调用成功 |
| action_id | 动作执行 ID |
| external_id | 设备 ID |
| message | 结果说明 |
| error | 标准错误 |

### AdapterHealth

| 字段 | 说明 |
| --- | --- |
| status | healthy / degraded / disconnected |
| adapter_id | 适配器 ID |
| detail | 状态说明 |
| checked_at | 检查时间 |

## Home Assistant Adapter

### 配置

```text
ARVUNO_HOME_ASSISTANT_URL=https://home-assistant.local
ARVUNO_HOME_ASSISTANT_TOKEN=<local-token>
ARVUNO_HOME_ASSISTANT_TIMEOUT_SECONDS=10
```

配置只通过环境变量或本地配置文件读取，不得写入源码。

### REST API 使用

第一阶段优先使用：

- `GET /api/states`：获取实体状态。
- `GET /api/states/{entity_id}`：获取单个实体状态。
- `POST /api/services/{domain}/{service}`：调用服务。
- `GET /api/`：健康检查。

### WebSocket API 使用

用于订阅状态变化：

1. 建立 WebSocket 连接。
2. 认证。
3. 按配置的实体类型和实体 ID 过滤后订阅 `state_changed` 事件。
4. 将事件转换为 `device_state_changed`。
5. 断线后使用退避策略重连。

如果第一阶段暂不启用 WebSocket，可以用轮询作为降级方案，但事件模型必须保持一致。

### 实体映射

| Home Assistant | Arvuno |
| --- | --- |
| `entity_id` | `external_id` |
| `attributes.friendly_name` | `Device.name` |
| `state` | `DeviceState.state` 标准化结果 |
| `entity_id` domain | `DeviceType` 推断依据 |
| `attributes` | `DeviceState.attributes` |
| `area_id` / area attribute | `Device.area` |
| service call | `DeviceAction` |

类型映射示例：

| Home Assistant domain | Arvuno DeviceType |
| --- | --- |
| `light` | `light` |
| `switch` | `switch` |
| `sensor` + temperature class | `sensor_temperature` |
| `sensor` + humidity class | `sensor_humidity` |
| `binary_sensor` + motion class | `sensor_motion` |
| `binary_sensor` + opening class | `sensor_contact` |
| `climate` | `climate` |
| `media_player` | `media_player` |

无法识别的实体映射为 `unknown`，默认禁止执行动作。

### 服务映射

| Arvuno Action | Home Assistant Service |
| --- | --- |
| `turn_on` | `homeassistant.turn_on` 或域专属服务 |
| `turn_off` | `homeassistant.turn_off` 或域专属服务 |
| `toggle` | `homeassistant.toggle` 或域专属服务 |
| `set_brightness` | `light.turn_on` + `brightness_pct` |
| `set_temperature` | `climate.set_temperature` |

服务映射必须集中在 Adapter 内，不泄漏到 Agent。

## 错误模型

| 错误 | 场景 | 处理 |
| --- | --- | --- |
| `AdapterUnavailableError` | Home Assistant 无法连接 | 标记适配器降级 |
| `AdapterTimeoutError` | 请求超时 | 不重试写操作，除非有明确幂等设计 |
| `DeviceUnavailableError` | 设备状态为 unavailable | 拒绝控制 |
| `DeviceNotFoundError` | 实体不存在 | 同步轻量设备投影并提示配置错误 |
| `ActionUnsupportedError` | 能力不支持 | 拒绝执行 |
| `InvalidActionParameterError` | 参数非法 | 返回 422 |
| `ActionFailedError` | 平台返回失败 | 记录错误并验证状态 |
| `AuthorizationError` | Token 无效 | 停止请求并提示配置错误 |

## 超时与重试

只读操作：

- 默认超时 10 秒。
- 可以有限重试。

写操作：

- 默认超时 10 秒。
- 不自动重试，除非动作有平台提供的幂等 ID。
- 超时后必须读取状态验证，不能直接判定成功。

## 事件转换

Home Assistant `state_changed` 转换为：

```json
{
  "event_type": "device_state_changed",
  "source": "home_assistant",
  "subject_type": "device",
  "subject_id": "arvuno-device-id",
  "payload": {
    "previous_state": "off",
    "current_state": "on",
    "attributes": {}
  },
  "correlation_id": null
}
```

传感器更新可映射为 `sensor_updated`，设备不可用映射为 `device_unavailable`。

## Device Registry

Registry 负责将 `external_id` 转换为 Arvuno `device_id`。

职责：

1. 同步配置范围内允许 Arvuno 使用的设备投影。
2. 保存设备能力摘要。
3. 保存区域和别名。
4. 保存设备启用状态和默认风险等级。
5. 提供设备查询和外部 ID 到 Arvuno 设备 ID 的映射。

Registry 是轻量投影，不是设备管理平台。它不负责：

- 实时通信。
- 设备发现。
- 协议配置。
- 设备配网和生命周期管理。
- 完整设备历史。

## 状态验证

设备控制后必须执行验证：

1. 记录执行前状态。
2. 记录预期状态。
3. 调用 `get_state` 读取实际状态。
4. 比较实际状态与预期状态。
5. 记录验证结果。
6. 超时或状态不一致时标记验证失败。

验证结果存入 `tool_executions.validation`。

## Mock Device Adapter

必须实现与 Home Assistant Adapter 相同的接口。

能力：

- 内置虚拟灯、开关、温湿度传感器、门窗传感器。
- 支持状态查询。
- 支持低风险开关动作。
- 支持模拟离线。
- 支持模拟超时。
- 支持模拟动作失败。
- 支持主动触发状态变化事件。

用途：

- 没有真实设备时验证完整闭环。
- 测试权限、风险、任务状态和结果验证。
- 前端开发环境。

## 适配器生命周期

```text
加载配置
→ 初始化 Adapter
→ health_check
→ 同步设备
→ 建立状态订阅
→ 运行中监控
→ 断线重连
→ 关闭释放资源
```

## 未来扩展

### MQTT Adapter

新增 `adapter_id = mqtt`，实现同一接口，映射 topic、payload 和设备能力。

### ESP32 自定义传感器

可以通过 MQTT Adapter 接入，或在确实必要时实现独立 Adapter。

### 机器人

机器人不在当前 Device Adapter 设计中预留接口。未来如果评估机器人，必须先通过独立架构决策定义安全能力、动作风险和紧急停止策略，不能复用普通设备接口。

## 设计约束

1. 不把 Home Assistant entity_id 暴露给 Agent 作为主要设备 ID。
2. 不把 Home Assistant 状态字符串直接作为任务结果。
3. 不在 Agent Prompt 中要求模型拼 Home Assistant 服务调用。
4. 不让前端直接调用 Home Assistant。
5. 不支持未识别设备的动作执行。
6. 不自动重试非幂等写操作。

## 第一阶段验收

1. Home Assistant 健康检查可用。
2. 能只同步配置范围内允许 Arvuno 使用的实体，而不是 Home Assistant 全部设备。
3. 能读取设备状态。
4. 能订阅或轮询状态变化。
5. 能执行低风险动作。
6. 能验证执行后状态。
7. 超时、离线和无权限场景有明确错误。
8. Mock Adapter 能替代真实 Home Assistant 跑通核心测试。
