# 32. ARS-05 Multimodal Perception Acceptance Report

- 日期：2026-11-06
- 分支：`main`
- 验收基线：ARS-05 工作区实现；本报告生成时 ARS-05 代码尚未提交
- 验收范围：ARS-05.1 多模态观测接入、ARS-05.2 多模态融合与隐私治理、ARS-05.3 语音交互体验、ARS-05.4 最终验收
- 最终结论：**条件通过 / 不关闭**

## 1. Executive Summary

ARS-05 的按需图像、OCR、语音转写、语音播报、音频事件、Provider 调用记录、时空 Fusion、授权、脱敏审计、物理删除和本地处理边界已经完成工程实现并通过隔离回归。视觉和音频输出只能作为带置信度、模型版本和来源引用的候选观测进入既有 Observation Pipeline；STT 是对话数据而不是环境事实；TTS 不产生 Observation。Fusion 保留单模态来源，重复和冲突只标记，不覆盖原始记录，也不把时空相关性升级为因果结论。

本轮验收发现并修复了一个真实缺陷：Provider 元数据中的 `timeout_ms` 之前没有实际生效。修复后视觉、OCR、STT、Audio Event 和 TTS 调用都受超时控制；超时会返回 `MULTIMODAL_PROVIDER_TIMEOUT`，调用记录标记为 `timeout`，敏感媒体和 TTS 输出会被清理，Capture Session 进入 failed。补充测试还确认普通 Provider 崩溃会记录 `MULTIMODAL_PROVIDER_FAILED` 并物理清理媒体。

条件通过只适用于 Mock Provider 和按需采集架构。本轮没有真实摄像头、真实麦克风、真实视觉 / STT / TTS / Audio Event 模型、真实云端 Provider、真实浏览器语音端到端或生产数据保留合规验收。另外，`purge_expired` 的服务和测试可用，但应用当前没有常驻后台保留清理调度器。因此 ARS-05 不关闭，也不能把 Mock 验收解释为真实感知能力验收。

## 2. Validation Environment

验证使用隔离临时 SQLite 数据库和受控临时媒体目录，没有修改当前开发数据库、运行环境或真实设备。当前开发库保持 ARS-04 head `a7d4f83c1092`；ARS-05 两个迁移只在隔离空库验证，应用启用多模态表前必须显式迁移。

| 检查 | 结果 |
| --- | --- |
| ARS-05 专项回归 | 首次 27 passed / 1 failed；修复超时状态与断言后 28 passed |
| Backend full regression | 351 passed，1 个既有 FastAPI / Starlette TestClient deprecation warning |
| Backend lint | `ruff check arvuno_core` 通过 |
| Backend format | `ruff format --check arvuno_core` 通过，175 files already formatted |
| Alembic heads | 单 head：`e5f1a2b3c4d5` |
| Alembic current | 本地开发库保持 `a7d4f83c1092`，本次未迁移 |
| Alembic empty upgrade | 隔离空库升级到 `e5f1a2b3c4d5` 通过 |
| Frontend typecheck | `tsc --noEmit` 通过 |
| Frontend format | Prettier check 通过 |
| Frontend build | Vite build 通过；保留既有 JS bundle 大于 500 kB warning |

重点测试文件：

- `backend/tests/test_multimodal_observation_access.py`
- `backend/tests/test_multimodal_fusion_privacy.py`
- `backend/tests/test_voice_interaction.py`

## 3. Defects Found During Acceptance

### 3.1 Provider timeout 未强制执行

验收前，`timeout_ms` 只作为 Provider 元数据存在，Provider 调用没有统一等待上限。这不是权限绕过，但违反故障隔离要求，慢 Provider 可能长期占用请求或处理路径。

修复内容：

1. Vision、OCR、STT、Audio Event 和 TTS Provider 调用统一使用 `asyncio.wait_for`。
2. 超时返回 `MULTIMODAL_PROVIDER_TIMEOUT` 和 HTTP 504。
3. Analysis 超时将 Invocation 标记为 `timeout`，清理媒体并失败 Capture Session。
4. TTS 超时删除输出并失败 Capture Session。
5. 新增超时测试确认数据库状态、存储对象、Observation 数量和 API 错误码。

### 3.2 超时状态被外层失败处理覆盖

修复 timeout gate 后第一次测试发现：内层已正确把 Invocation 写成 `timeout`，但外层 `MultimodalError` 处理又把它改写为 `failed`。这会让运维和审计把限流性问题误判为普通 Provider 崩溃。

修复内容：外层错误处理保留 `MULTIMODAL_PROVIDER_TIMEOUT` 的终态，不再重复降级；普通失败仍然标记 `MULTIMODAL_PROVIDER_FAILED`。

### 3.3 补充普通 Provider 故障证据

原实现覆盖了授权缺失、上传拒绝、Fusion 范围错误和超时，但缺少本地 Provider 崩溃的直接验收证据。本轮新增测试确认 Provider 崩溃返回 502 / `MULTIMODAL_PROVIDER_FAILED`，Invocation 记录 failed，媒体物理清理，且不产生 Observation。

## 4. Acceptance Matrix

| 验收项 | 结论 | 验收说明 |
| --- | --- | --- |
| 图像输入与识别 | 条件通过 | PNG 上传、MIME 魔数校验、Capture Session、Consent、Provider Invocation、Extraction、Observation artifact link 和敏感媒体清理通过。视觉模型当前是 Mock，只验证契约，不验证真实场景识别准确率 |
| 视觉对象不伪装成事实 | 通过 | Vision object 输出保持 `candidate`、置信度小于 1，映射为 `object_presence` Observation；测试确认没有创建 Entity 或永久物品身份 |
| OCR | 条件通过 | Mock OCR 输出可进入候选结果并参与敏感数据删除验证。没有真实 OCR、真实文档样本和识别质量验收 |
| 语音输入与输出 | 条件通过 | STT transcript 保留模型版本和 instruction 分类，但不产生 Observation；TTS 生成私有音频，不产生 Observation。当前 Provider 是 Mock，真实语音准确率未验收 |
| 语音意图与确认 | 条件通过 | 只有显式 `is_instruction=true` 进入 Agent Runtime；非指令、空转写和唤醒词不匹配都不会进入 Agent。任务确认使用 task ID + confirmation token，语音内容不能推断确认。真实浏览器 / 麦克风端到端未验收 |
| Audio Event | 条件通过 | 授权短时音频可输出 `candidate_only` 事件 Observation，不直接推断事故、身份或执行设备动作。真实事件检测模型未验收 |
| 多模态来源关联 | 通过 | Fusion 在时间 / 空间 / 授权范围内保留 sensor、vision 和 extraction 各自来源、模型、质量和关联 ID。结果不物化为新事实表，`causal_claim=false` |
| 重复与冲突处理 | 通过 | 相同值标记 duplicate candidate，不同值标记 conflict candidate；原始 Observation 和模型候选不会被覆盖 |
| 数据访问授权 | 通过 | 缺失、撤销、过期和跨环境 grant 分别被拒绝；Fusion API 无认证返回 401，非法时间范围返回结构化错误 |
| 授权撤销 | 通过 | Processing consent 撤销后状态为 revoked，关联私有输出被删除；后续访问按 scope / expiry / active 状态拒绝 |
| 敏感数据删除 | 通过 | 敏感 OCR 原图、敏感 STT 音频、提取结果和存储对象通过隔离测试确认物理删除；审计 JSON 中不包含 OCR / transcript 内容 |
| 保留过期 | 条件通过 | `purge_expired` 能按保留时间物理删除媒体并记录 `retention_expired`。但应用没有自动后台调度器，当前依赖显式调用或未来任务接入 |
| 云端 / 本地边界 | 条件通过 | 当前授权模型只接受 `local`，默认能力目录为本地 Mock，`cloud_processing_enabled=false`，Invocation 记录 `sent_media_to_external=false`。没有生产云端 Provider 可验证真实传输、保留和合规声明 |
| 故障与超时 | 通过 | Mock 超时和 Provider 崩溃均有测试；返回结构化错误、记录 Invocation 状态、清理媒体并失败 Capture Session。真实 SDK 的不可取消阻塞行为仍未验证 |
| ARS-02 World Model 兼容 | 通过 | 多模态环境事实必须经 Observation Pipeline；没有新增平行事实源或直接写 State Estimate / Entity。ARS-02 至 ARS-04 全量回归继续通过 |
| 真实摄像头与麦克风 | 未验收 | 本轮没有执行真实硬件、操作系统授权弹窗、浏览器兼容性、噪声环境和设备矩阵测试 |

## 5. Architecture And Privacy Verification

### 5.1 Source Traceability

图像和音频从 Capture Session 进入，媒体本体保存于受控私有文件目录，SQLite 只保存元数据和引用。Provider Invocation 保存 capability、provider、model id / version、processing location、输入摘要、请求摘要、状态和错误码。Extraction Result 保存 schema version、置信度、confidence level、语言、备选结果和有效期。 Observation artifact link 把候选结果回连到既有 Observation。敏感记录清理后，剩余引用只能表示媒体不可用，不能重新还原内容。

### 5.2 Candidate Semantics

Vision scene、object 和 audio event 结果都必须经过 Provider Result 校验和 Observation Pipeline，不会直接创建 Entity、覆盖设备状态或写入 State Estimate 的 observed 值。模型置信度只是排序和质量提示，不等于现实确定性。STT transcript 是 Conversation / Agent 输入数据；只有满足 ARS-03 来源规则时才可能成为 Memory candidate，本阶段不会自动升格为长期事实。

### 5.3 Privacy Boundary

Camera capture、microphone capture、continuous video analysis 和 cloud processing 的公开能力状态默认为 false。上传、处理和 Fusion 分别需要显式、匹配、未撤销且未过期的授权；授权检查覆盖 environment、modality、purpose、space、provider 和 processing location。审计记录保存动作和脱敏元数据，不保存媒体字节、完整 OCR 或 transcript。

物理删除会先删除受控存储对象，再更新数据库中的 `storage_key`、`content_available` 和 `purge_status`。隔离测试验证文件不可访问、接口返回 404、提取结果被删除、审计不含敏感文本。删除后的 Observation 或 Conversation 遵循既有自身策略，不会被伪造成从未发生过。

### 5.4 Failure Semantics

Provider timeout 与 Provider crash 分别记录，不共享同一个模糊错误。超时调用标记 `timeout`，普通失败标记 `failed`，两者都会触发媒体清理和 Capture Session failed。错误响应用统一 code，不携带原始媒体、完整 transcript 或 OCR 文本。Mock 异步 Provider 可以被取消；真实 SDK 可能存在进入不可取消阻塞调用后的残留工作，这必须在真实 Provider 阶段重新验证。

## 6. Real Hardware / Real Model Test Record

本节单独记录：**未执行**。

1. 没有真实摄像头硬件、摄像头权限弹窗、浏览器 `getUserMedia` 设备矩阵或真实光照 / 遮挡 / 距离样本测试。
2. 没有真实麦克风硬件、操作系统麦克风授权、环境噪声、远场语音、口音和延迟测试。
3. 没有真实本地或云端 vision、OCR、STT、TTS、Audio Event 模型。
4. 没有生产云端数据发送范围、供应商保留、训练用途、区域、合规和中断恢复验收。
5. 没有真实浏览器语音交互完整手工验收；前端状态机只通过代码和构建检查。
6. 没有持续唤醒词监听；当前唤醒词模块只在单次转写后判断。

上述结果不能用 Mock 测试替代。

## 7. Unimplemented Or Not Accepted Capabilities

1. 真实视觉、OCR、STT、TTS 和 Audio Event Provider 未接入。
2. 真实摄像头、麦克风、浏览器矩阵和操作系统权限流程未验收。
3. 独立后台唤醒词、持续麦克风采集、持续视频分析未实现。
4. 声纹识别、人脸识别、人员追踪、情绪识别和生物特征身份库未实现。
5. 机器人感知、主动导航采集和真实 Active Perception 硬件接入未实现。
6. 自动后台保留清理调度器未实现；只有可显式调用的 `purge_expired` 和测试覆盖。
7. 生产云端 Provider、云 fallback、配额重试、供应商合规和升级路径未验收。
8. 真实浏览器语音端到端体验、多浏览器 / 移动端矩阵和可访问性验收未完成。
9. 语义级多模态实体对齐仍不是完整能力；当前 Fusion 主要是确定性时间 / 空间 / 关联证据组织，不能把识别标签自动绑定为永久物品身份。
10. 真实模型下的 Provider cancellation、部分输出、流式失败、重试和超时残留行为未验证。
11. 生产长期保留、冷存储、备份 / 恢复和大规模媒体生命周期演练未执行。

## 8. Inherited Risks

ARS-02 的隐私删除端到端、目标规模压测、备份恢复、真实 ESPHome / ESP32 扩展和真实 AI Provider 缺口仍未全部关闭。ARS-03 的语义检索、自动压缩、长期知识提炼、多用户隔离和真实程序验证链路未完成。ARS-04 的 AI Planner / 评估器、多步与非设备计划、Proactive Level 3 / 4、感知执行集成、真实 Observer 和真实授权界面也未完成。

这些遗留项会直接影响真实多模态数据的长期治理、解释、主动响应和执行闭环。ARS-05 条件通过不解除上述前置风险。

## 9. Final Verdict

ARS-05 达到 **Mock / 按需架构条件通过**。当前代码可以作为接入真实 Provider 和真实硬件前的受控基础：默认关闭敏感能力，模型输出保持候选语义，隐私授权和物理删除边界已经回归。

ARS-05 不关闭。后续必须先完成真实摄像头 / 麦克风与真实模型验收，再评估云端 Provider；后台保留清理调度器和真实浏览器语音体验也必须在真实使用验收中复验。所有第 6、7 节缺口不得被本报告的条件通过掩盖。
