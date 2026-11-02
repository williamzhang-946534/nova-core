# 17. 真实 Home Assistant 验收手册（demo 虚拟设备）

本手册用 Home Assistant 的 `demo` 集成虚拟设备完成 Phase 10 中真实 Device Adapter 的验收，无需任何实体硬件。验收对象是 Arvuno 的 Home Assistant Adapter、Device Registry、事件系统与 Tool Executor 之间的真实链路。

## 1. 前置条件

- Windows 10/11 + Docker Desktop（启用 WSL2 后端）。
- 已可运行的 Arvuno 后端与前端（见 README）。
- 已配置真实或 Mock AI Provider（本阶段已配置 DeepSeek）。

## 2. 启动 Home Assistant demo

```powershell
cd deploy\home-assistant-demo
docker compose up -d
```

首次启动约需 1–2 分钟。访问 `http://localhost:8123`，完成首次引导（创建管理员账号）。

`configuration.yaml` 已内置：

```yaml
default_config:

demo:
```

`demo` 集成提供 `light.bed_light`、`light.ceiling_lights`、`light.kitchen_lights`、`switch.ac` 等虚拟实体，行为与真实设备一致。

## 3. 创建长期访问 Token

1. 进入 HA 界面左下角头像 → 个人资料 → 安全 → 长期访问令牌 → 创建令牌。
2. 复制令牌（只显示一次），写入 Arvuno 的 `.env`：

```text
ARVUNO_HOME_ASSISTANT_URL=http://localhost:8123
ARVUNO_HOME_ASSISTANT_TOKEN=<令牌>
ARVUNO_HOME_ASSISTANT_ALLOWED_ENTITY_IDS=["light.bed_light"]
ARVUNO_HOME_ASSISTANT_WRITE_ENABLED=false
```

`WRITE_ENABLED` 必须保持 `false` 完成只读验收。

## 4. 阶段一：只读验收（A3 / A4 / A5）

重启 Arvuno 后端后执行：

```powershell
$env:HA_URL="http://localhost:8123"
$env:HA_TOKEN="<令牌>"
.\.venv\Scripts\python.exe scripts\acceptance\ha_demo_acceptance.py ha
```

验收点：

- A3 连接：HA API 可达，token 有效，allowlist 只导入配置范围内的实体。
- A4 读取：`GET /api/devices` 出现 `light.bed_light` 投影，`GET /api/devices/{id}/state` 返回状态与时间。
- A5 事件：在 HA 界面手动开/关 `light.bed_light`，Arvuno 轮询应在 `/api/events` 产生 `device_state_changed`，并更新 `/api/environment`。

然后验证 Arvuno 侧投影：

```powershell
$env:ARVUNO_API_TOKEN="<Arvuno token>"
$env:ARVUNO_BASE_URL="http://127.0.0.1:8000"
.\.venv\Scripts\python.exe scripts\acceptance\ha_demo_acceptance.py arvuno
```

## 5. 阶段二：写操作验收（A7 / A8）

确认只读验收通过后：

1. 把 `.env` 改为 `ARVUNO_HOME_ASSISTANT_WRITE_ENABLED=true`（生产环境仍会拒绝开启，仅开发验证用）。
2. 重启后端，执行：

```powershell
.\.venv\Scripts\python.exe scripts\acceptance\ha_demo_acceptance.py arvuno --write
```

验收点：

- A7 控制：任务 `completed`，`validation.verified=true`，HA 中 `light.bed_light` 实际状态改变。
- A8 异常：把 allowlist 里的实体在 HA 中设为不可用，或断开 HA，控制应返回失败、不显示成功。

## 6. 事件与自动化复核

- 外部变化（在 HA 界面开关灯）→ `device_state_changed` 事件 + 环境更新。
- Arvuno 自身控制 → 不产生 `device_state_changed`，不触发基于外部状态变化的自动化（避免自触发）。
- 可选：在 Arvuno 建一条"灯亮起时通知"的规则，用 HA 界面开灯验证规则触发。

## 7. 常见问题

| 现象 | 处理 |
| --- | --- |
| 8123 打不开 | 等容器完成启动；`docker compose logs -f homeassistant` 观察日志 |
| token 401 | 令牌复制不完整或已撤销，重新创建 |
| `/api/devices` 无 HA 实体 | allowlist 未匹配、URL 不对，或 `WRITE_ENABLED` 拼写错误 |
| 事件不更新 | 检查 `ARVUNO_DEVICE_POLL_INTERVAL_SECONDS`，默认 30 秒 |
| 写操作被拒 | 确认 `WRITE_ENABLED=true` 且实体在 allowlist 内 |

## 8. 清理

```powershell
docker compose down -v   # 删除容器与数据卷
```

配置目录 `config/` 中的运行数据已被 `.gitignore` 忽略，不会进入版本库。

## 9. 与 Phase 10 报告的对应

读取、低风险写入和断线/重连已完成；`docs/16-phase10-acceptance-report.md` 中的真实 HA 项已更新为"已通过"，证据见其 11.6 和 11.7 节。真实硬件接入路径与本手册完全一致：只需把 allowlist 换成一个真实低风险实体 ID。
