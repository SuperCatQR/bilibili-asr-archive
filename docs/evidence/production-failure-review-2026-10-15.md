生产总追踪单：https://github.com/SuperCatQR/bilibili-asr-archive/issues/458

# UID 23191782 生产运行故障复盘

审计日期：2026-10-15，Asia/Hong_Kong。主要证据为当日 **20:51–21:03 +08:00** 的只读数据库/文件/PID 快照，辅以当日隔离复现及保留的历史记录。以下是时点统计，不承诺之后不变。

## 核心判断和规模口径

流水线没有整体停机。20:51 ASR 为 765 succeeded / 4 running / 95 queued，GPU 100%、31772 MiB；audio 777 succeeded / 87 queued，subtitle 864 succeeded，publish 858 succeeded。下载当时因 ASR backlog=12 触发既定闸门，不能把这个设计行为误报为下载失败。AI 另有六个 running；controller 的 ai_enabled=false 只属于自身范围。

全量采集尚未完成：按目标 UID 过滤为 861 视频/864 分 P，cursor 第 30 页，相对 observed_total=1691 的缺口为 830。全库 870 视频/873 分 P 包含其他样本。动态上游总数不是静态的最终真值。

历史失败共 **887 次 attempts**。当前 failed 为 4 个 ASR job 和 12 个 proofread job。4 条 ASR 失败属于 3 个视频，其中两个视频已有成功替代，未解决的可用 ASR 缺口是 BV1PM411U789/P1。另发现两个已恢复 ASR 的旧校对链未收敛，阻塞 4 个下游任务。

| 类型 | 失败 attempts | 涉及该类型 job | 复盘快照结论 |
|---|---:|---:|---|
| subtitle / OperationalError | 486 | 486 | job 已全部成功，资源永久修复仍需正式激活 |
| publish / OperationalError | 296 | 296 | job 已全部成功，原失败保留 |
| subtitle / auth_error | 83 | 83 | job 已全部成功；曾独立阻塞，不能混归 FD |
| proofread / RevisionValidationError | 10 | 10 | 仍失败，10 条 render 直接受阻，严格拒收正确 |
| proofread / worker_drain_timeout | 4 | 4 | job 已成功，当前没有该类失败阻塞；原始触发缺少进一步证据 |
| ASR / ValueError | 2 | 2 | 同一视频两次失败，首段零时长已捕获 |
| ASR / inference_timeout | 2 | 2 | 原 job 保留 failed，两个视频替代 ASR/发布已成功 |
| proofread / DeepSeekError | 2 | 2 | 一条 content_filter，一条 stop 但空正文；2 条 render 直接受阻 |
| publish / OSError | 1 | 1 | 重试成功，原始消息缺失，不确认原始根因 |
| publish / ValueError | 1 | 1 | 已成功，原始消息缺失，不能套用旧归档时间戳案例 |

以上是按 kind/code 的计数；跨类型可能对应同一视频，失败 attempt 也可能后来成功，**不能相加成失败视频数**。12 个校对失败在 216 成功+12 失败的终态 job 中占 5.26%，这是终态 job 占比，既非模型调用错误率也非全队列失败率。

## 工单及处理顺序

| 优先级 | 工单 | 影响及交付边界 |
|---|---|---|
| P1 | #449 SDK HTTP 客户端 FD 泄漏 | 历史 782 次 OperationalError；恢复已做，永久补丁加载/持续运行验证待闭环 |
| P1 | #453 构建与运行进程版本漂移 | 曾发生缺模块；当前磁盘补丁和内存版本不同，需完整交付/可追踪激活 |
| P1 | #454 全量采集持续无进展 | 第 30 页 13 条 cooldown，约 9h06m 未增加视频，剩余发现受阻 |
| P1 | #455 复制与释放条件耦合 | 515 个在盘、ASR 已完成文件约 8.12 GiB 被非破坏性复制筛选排除 |
| P1 | #452 alignment 零时长首句 | 1 个视频仍无可用 ASR，两次失败；上游 cue 允许非法跨度 |
| P2 | #450 未知异常的安全诊断丢失 | 782 次 OperationalError 和 2 次 ASR ValueError 难以仅凭 attempt 定因 |
| P2 | #451 长音频固定 deadline | 两个约 4h 输入曾被 1800s 上限终止，3600s profile 分别 1843/1946s 成功 |
| P2 | #456 替代 ASR 下游 DAG 未收敛 | 两个 proofread 仍等旧 failed ASR，各阻塞一个 render |
| P2 | #457 provider 中止原因误分类 | 一条 content_filter 被视为 unfinished/truncated，当前源码同样可复现分类缺口 |

建议先完成部署身份和永久 FD 补丁激活的受控验收，同时处理采集无进展、备份复制积压和零时长样本；之后完善恢复 DAG、deadline 与观测。各工单保留自己的独立验收，不以总单关闭代替实际修复。

## 主要故障链

1. **运行资源链**：每 job 新事件循环 → SDK 持有旧循环 HTTP clients → FD 耗尽 → SQLite/文件访问受影响 → 字幕/发布失败 → 下游等待。提升 FD 上限缓解，但当前旧 PID 尚未加载永久清理。安全诊断缺失导致数据库故障容易被误判为损坏/锁冲突。
2. **采集覆盖链**：鉴权曾失效 → 更换凭据后可继续 → 第 30 页持续 rate_limited → watch 反复退避但无进展预算 → 未发现视频不进入音频/ASR 队列。外部限流根因尚无法细化到 IP/账号/接口，不承诺增大等待就能解除。
3. **ASR/质量链**：健康长输入触发固定总 deadline → 建新 profile 重跑成功 → 旧 proofread 仍冻结依赖原失败 job → 阅读稿永久 queued。另一视频的未对齐首句形成 0→0 cue → 入库 ValueError → 原始输出常规路径缺证 → 专用诊断重跑才能定位。
4. **存储链**：非破坏性备份复制错误要求所有消费者成功 → AI queued/失败/旧 ASR 失败都阻止复制 → 源音频持续占盘 → 下载空间/队列闸门可能限制吞吐。能复制的量与能安全释放的量必须分开；515 个文件不能直接作为安全可删清单。
5. **付费产出链**：模型返回结构/引用/段落契约违规，或 content_filter/空正文 → 正确拒收 → proofread failed → render 阻塞；provider 中止分类不足会误导重试。不得自动修引用、删首句、放宽质量规则或无预算重复付费。
6. **交付放大链**：仓库 issue 已完成 → 安装旧包/混合单文件补丁/旧 PID 未重启 → 生产仍保留旧行为或缺模块 → 运维误判已修复。来源版本不明确还使诊断和回滚复杂化。

这些链有交叉但并非单一根因：auth_error 不是 FD 泄漏，content_filter 不是长度截断，空字幕不是静音证明，正常 backlog 闸门不是下载故障。

## 已有工单覆盖与历史边界

- #350 / #310 已覆盖块级校对恢复和显式 repair；本轮 10 条契约拒收（4 条引用、5 条段落格式、1 条字段）补充其生产验收样本，不重复建“缺少校验/缺少修复入口”工单。
- 12 个失败校对 job 共保留 48 次调用，其中 36 次调用成功、12 次失败；返回 usage 合计 1983001 tokens，失败调用合计 453517 tokens。成功块是否可复用需按冻结输入/检查点验证；这些数字不是全部浪费，也不是收费金额。本轮诊断没有发起新的付费模型调用。
- #285 已覆盖 2026-10-09 BV18L4y1E7qs/P2 空字幕正文：一条 zh-CN 非 AI track 的正文为空、四次尝试保留；不能认定音频无声。
- #410 已覆盖质量准入；2026-10-10 旧归档 BV1aU4y1b7mX/P13，transcript=2474，cue131 start 倒退约 17.954s，以及 BV1V1dhBEEYn/P1 cue72，均需保留原证据/hold。旧归档不在当前主机，历史记录不充当当前失败计数。
- #406 已有自动 retention 能力；新单针对生产外部备份 helper 的真实筛选与集成缺口。#365/#366/#367 的状态/分类功能不等于旧包已激活，也不等于未知异常诊断和 DAG 恢复已完全覆盖。
- 较早 HTTP 402、OpenCode 出口访问/端点、GPU 依赖兼容故障有保留记录；当前未发现新增 402 阻塞证据，AI 六个 running 不能作为所有历史网络故障已永久修复的证明。#439 是已关闭依赖兼容回归，正式部署仍需真实 GPU 验收。
- 聚焦 FD 回归 433 passed / 1 skipped；旧 `test_subtitles.py` 导入已移除模块、`test_subtitle_e2e.py` 使用旧 CLI，属于验证迁移缺口，不能声称全量回归绿。这些测试问题未直接作为生产故障根因。

## 完成判定

- [ ] 九个子单有明确修复或运营处置及证据，版本 installed/loaded/production-verified 可核对。
- [ ] 目标 UID 达到经边界核对的完整枚举；风险中断/cooldown 不被报告为完成。
- [ ] 当前唯一未解决 ASR 样本有合规的对齐修复/hold 结论，原始数据和失败不丢失。
- [ ] 两个替代 ASR 的下游按授权策略恢复，历史链明确 supersession。
- [ ] 音频复制积压与释放 blockers 分开度量，跨重启、目标断线和空间不足仍安全。
- [ ] 12 个校对样本按现有恢复预算/严格契约验证；content_filter 单独分类，不以绕过过滤恢复。
- [ ] 新一轮长时运行确认 FD 无持续增长、无新同类 OperationalError，统计区分历史 attempts 与当前阻塞。

## 证据来源及复核方法

当前主机归档 `bilibili-asr-archive/archive/archive.db` 以 `mode=ro` 查询；PID 使用 `/proc/<pid>/fd` 与 limits；文件只检查存在、size/hash；两条长音频已做完整解码。离线复现只运行 synthetic alignment/response envelopes；没有新付费调用。历史 FD/ASR 修复的动作来自同日已保留运维报告，本次复盘没有重排/删除生产任务。

机器证据保存在服务器 `production-ops-23191782/` 与本地 `.tmp/production-issue-audit-20261015/`。公开内容不包含密码、SESSDATA、API key、完整模型正文、音频或原始数据库。

证据文件指纹（原始文件保存在运维目录，没有作为公开附件上传）：

| 文件 | SHA256 |
|---|---|
| `production-issue-audit-20261015.json` | `cbc8fa9522cecb253824a1eef2365da6572e47c046cf9a581acb9a13a1a79e98` |
| `production-issue-dependencies-20261015.json` | `518f5084542abadc05c86c269c5583d08ba996d0556b6a2ceea4ac7c6a1dcb2c` |
| `production-issue-impact-20261015.json` | `0af6345f462c3d2e224314fb4e7e80ff15e08870e38dde25ac83ce7160c42ca5` |
| `production-issue-recovery-chain-20261015.json` | `00593e1c0fda6cd64bc8ee2459437c658a7f797689b142c36338cbd265305f80` |
| `offline-reproduction.json` | `28758c1a5b0624a52cc3cb67cb277707a99217b625c8b16f9c3e4aab94eb63d5` |

## 独立工单详细记录

### [生产复盘/P1][source] 事件循环退出后 SDK HTTP 客户端未释放，耗尽 FD 并级联触发 782 次 OperationalError

https://github.com/SuperCatQR/bilibili-asr-archive/issues/449

## 问题、规模与现状

字幕采集逐 job 使用 `asyncio.run`；Bilibili SDK 全局 `session_pool` / `lazy_settings` 按事件循环保存客户端。循环结束后客户端和底层资源仍被保留，长期驻留的字幕/发布 worker 最终逼近进程 FD 上限，使看似无关的 SQLite/文件操作也失败。

- 17:40 复盘证据：PID 8037 为 **1019 / 1024 FD**，其中 sockets=635、eventfds=379、其他=5；20:51 为 1021 FD，soft limit 已临时提升为 8192。
- 当前归档历史中有 **486 次字幕 OperationalError + 296 次发布 OperationalError = 782 次**，分别涉及 486 和 296 个 job；两类可能对应同一视频，不能当作 782 个不同视频。
- 20:56 核对这些 job 全部已经 `succeeded`，历史失败仍保留。另有 83 次字幕 `auth_error`，是独立鉴权故障，不能用资源泄漏解释。
- 已有兼容清理补丁写入本地和服务器磁盘，但 **PID 8037 尚未重启，仍使用旧内存代码**。提升 FD 上限只是缓解，不能作为根治完成条件。

## 已确认的故障链与证据边界

`每次请求创建事件循环 → SDK 跨循环保留客户端 → sockets/eventfd 累积 → 接近 RLIMIT_NOFILE → SQLite/输出文件操作失败 → subtitle/publish job failed → 下游等待/人工诊断重试`。

受控实验不发任何 HTTP：连续 20 个循环分配 curl transport 后 FD 从 4 升至 24，池中保留 20 个客户端，独立复现生命周期缺陷。受控 SQLite 副本在耗尽 FD 时复现 `OperationalError: unable to open database file`（SQLITE_CANTOPEN=14），释放后同一写入成功并回滚。**生产只保留异常类名，没有原始 message；该 message 是隔离复现，不是找回的生产 traceback。**

16:52:01 仅将原 worker soft limit 从 1024 提到 8192，同一进程随后可成功发布；296 个失败发布重试成功，连同另一条 OSError 共验证 297 个 job、1485 个非空文件。OSError 原始原因缺证，单列待确认。

## 修复范围与验收

- [ ] request owner 在事件循环关闭前关闭自己创建的 SDK 客户端并移除相应池条目；嵌套 scope、预先存在的客户端、取消和失败都保持明确所有权。
- [ ] 使用真实安装 SDK/curl 后端做无网络重复循环与生产受控重启验收；新进程 100 loops 已验证 FD 保持 4、两个池为空，需要将此证据接到正式交付版本。
- [ ] drain 后加载永久补丁并记录 PID/代码版本；ASR lease 和历史失败不被重置。连续运行监测 FD 趋势而不是只看低于新上限。
- [ ] 原始失败保留，区分 auth_error、FD 资源故障及真实数据库损坏；不得把 SQLITE_CANTOPEN 类推成数据库损坏。
- [ ] 聚焦回归已为 433 passed / 1 skipped；ownership 条件反转能使 4 个回归失败。广义旧字幕测试仍存在迁移失配，不能将该聚焦结果描述成全测试通过。

已有详细证据：`docs/evidence/operationalerror-fd-exhaustion-2026-10-15.md`、`publish-diagnostic-20261015/final-report.json`。本单跟踪根因交付及激活；#366/#367 的分类与诊断能力是辅助，不替代资源修复。

## 证据口径

本单来自 UID `23191782` 生产运行复盘。主要只读快照为 **2026-10-15 20:51–21:03 +08:00**，每项另注明证据时间；数量不是实时仪表盘。运行包来自服务器 venv 的 `site-packages`，版本字段为 `0.1.0`，不能据此认定它等于 main。核对时 main 为 `3d5ed3af653c11f6ac4757c8180ebd350df871a3`；本地检查基线为 `e57edff`，另有未提交的请求资源清理补丁。

原始数据库、音频、模型正文和连接凭据未上传。生产 JSON 证据保存在服务器 `production-ops-23191782/` 及本地 `.tmp/production-issue-audit-20261015/`；本单内列出可以公开复核的计数、标识和合成复现。保留旧 attempts、冻结输入和 retry holds。

### [生产复盘/P2][diagnostics] ASR 子进程与通用异常只保留类名，丢失 SQLite/校验阶段诊断

https://github.com/SuperCatQR/bilibili-asr-archive/issues/450

## 问题与影响面

生产 `OperationalError` 与 ASR `ValueError` 的 attempt 多为 `result_json={}`。在没有 errno、SQLite 错误码、失败阶段、段序号或关联运行证据时，资源耗尽、路径/权限、锁竞争、音频损坏和模型输出非法难以区分。这放大了故障排查时间，也容易触发不必要的整段 GPU 重跑。

20:51 快照：782 次 OperationalError、2 次 ASR ValueError。它们体现相同的诊断盲区，不表示 784 个视频。原始消息不能从历史记录逆向恢复；本轮是借助 FD 实验及一次专用 ASR 捕获才确认部分原因。

## 故障链与源码核查

`原始失败 → asr/session.py 子进程消息仅发 error_type（最多 64 字符）/通用 executor fallback 仅保存类名 → attempt.result_json={} → 无法按原因采取恢复动作 → 人工修改诊断入口/付出重推理成本`。

当前本地 `asr/session.py` 的未知异常分支和通用工作流 fallback 仍需要覆盖。#366/#367 已建立已知业务错误的稳定分类和结构化诊断；本单是其**未知异常及跨进程传输缺口**，不是声称已有能力不存在。

## 建议交付与验收

- [ ] 建立白名单、限长、限深度诊断结构，至少记录 phase、异常类型、允许的 errno / sqlite_errorcode / sqlite_errorname、run/job/attempt 关联及可安全公开的失败 ordinal。
- [ ] 子进程 IPC 与 executor fallback 都传递经过统一过滤的字段；不能直接保存 `str(exc)`、完整 traceback、HTTP 头、prompt、文件正文或 `.env`。
- [ ] 捕获前后都受 lease/commit guard 控制，失败和取消仍有正确终态；诊断持久化自身失败有独立最小信号。
- [ ] 合成复现覆盖 FD 耗尽 SQLite、路径/权限、锁竞争、零时长段、进程硬退出；显示可区分原因，同时注入秘密标记验证无泄漏。
- [ ] 历史缺证明确为 `unavailable`，不得把隔离复现的错误文本写回历史 attempt 冒充当时证据。

证据：`production-issue-dependencies-20261015.json` 的 `runtime_extracts` / `failed_attempt_details`；FD 复现和 ASR 零 cue 复现见关联生产工单。影响是观测/恢复可靠性，尚无证据证明数据库内容损坏。

## 证据口径

本单来自 UID `23191782` 生产运行复盘。主要只读快照为 **2026-10-15 20:51–21:03 +08:00**，每项另注明证据时间；数量不是实时仪表盘。运行包来自服务器 venv 的 `site-packages`，版本字段为 `0.1.0`，不能据此认定它等于 main。核对时 main 为 `3d5ed3af653c11f6ac4757c8180ebd350df871a3`；本地检查基线为 `e57edff`，另有未提交的请求资源清理补丁。

原始数据库、音频、模型正文和连接凭据未上传。生产 JSON 证据保存在服务器 `production-ops-23191782/` 及本地 `.tmp/production-issue-audit-20261015/`；本单内列出可以公开复核的计数、标识和合成复现。保留旧 attempts、冻结输入和 retry holds。

### [生产复盘/P2][asr] 固定 1800 秒整段推理上限会终止可正常完成的四小时音频

https://github.com/SuperCatQR/bilibili-asr-archive/issues/451

## 已复现的规模与恢复

生产冻结 profile=1 使用 `inference_timeout_seconds=1800`。两条约四小时输入被终止，但新建 3600 秒 profile 后都能完成，证明至少这两次不能直接诊断为模型卡死或坏音频。

| 视频/P | part | 音频长度 | 原 job / 耗时 | 替代 job / 耗时 |
|---|---:|---:|---|---|
| BV1ck4y1N7pQ/P1 | 460 | 14450.840 s | d481ac0f-784c-4753-8dde-6a75fe86f7f6 / 1801 s，超时 | cdae00eb-29c0-4676-8cf5-e909280a750b / 1843 s，成功 |
| BV1TG411M7KG/P1 | 675 | 14653.515 s | 1de28014-a66d-4602-8997-4f53ccca1c59 / 1800 s，超时 | 67c2f590-5a16-4a0a-ab7c-a0974ddbaafa / 1946 s，成功 |

两个源文件均通过完整 AAC 解码及 SHA256 校验。替代结果分别 2012 / 2198 段，无空文本、非法区间、倒退 start；后者 coverage=0.999980026，发布成功。原失败 job/attempt 均保留，不能通过清掉历史使面板归零。

## 故障链、规模边界

`长输入 + 有限吞吐 → 整段总耗时超过固定 1800 s → supervisor 终止仍可能健康的进程 → 已消耗 GPU 计算未产出完整转录 → 人工新 profile 重跑 → 旧下游仍可能阻塞`。

第二条成功 RTF≈0.1328，高于固定预算允许的≈0.1228；第一条仅超过旧预算 43 s。4 worker 竞争是运行上下文，但没有实验可以把超时精确归因于竞争比例。只确认这两个样本，不能承诺所有长音频在 3600 s 内完成。重跑消耗了额外计算时间，不能将 wall time 直接折算 GPU 独占时长。

## 修复方向与验收

- [ ] 区分整段总预算、启动/预热预算、阶段无进展 watchdog；duration/profile/硬件/并发的预算推导应可解释、有限上界并冻结入配置。
- [ ] 调度前指出输入长度与现有 deadline 风险，允许显式建立新 profile；不原地篡改旧输入，不禁用 watchdog 或无限重试。
- [ ] 长输入健康推进可完成；真正停滞依然会被终止并封存 run/attempt。边界样本及多 worker 情景纳入验收。
- [ ] 替代 ASR 的发布、校对/文档依赖与音频备份资格一起核对，成功 ASR 不代表整个交付链已经恢复。

#230 解决的是超时退出后 run 的终态遗留；本单关注**预算误杀健康长输入**，与其范围不同。证据：`asr-timeout-repair-BV1ck4y1N7pQ-20261015.json`、`asr-timeout-BV1TG411M7KG-success-20261015.json`、`production-issue-dependencies-20261015.json`。

## 证据口径

本单来自 UID `23191782` 生产运行复盘。主要只读快照为 **2026-10-15 20:51–21:03 +08:00**，每项另注明证据时间；数量不是实时仪表盘。运行包来自服务器 venv 的 `site-packages`，版本字段为 `0.1.0`，不能据此认定它等于 main。核对时 main 为 `3d5ed3af653c11f6ac4757c8180ebd350df871a3`；本地检查基线为 `e57edff`，另有未提交的请求资源清理补丁。

原始数据库、音频、模型正文和连接凭据未上传。生产 JSON 证据保存在服务器 `production-ops-23191782/` 及本地 `.tmp/production-issue-audit-20261015/`；本单内列出可以公开复核的计数、标识和合成复现。保留旧 attempts、冻结输入和 retry holds。

### [生产复盘/P1][alignment] 未对齐文本可生成 0→0 cue，单视频两次 ASR 均在入库校验失败

https://github.com/SuperCatQR/bilibili-asr-archive/issues/452

## 生产症状与范围

`BV1PM411U789` P1，part=661，音频 6371.230 s / 23442918 bytes，SHA256=`a41e3e3ad39a7c211f0af67faa77519dbfa1731158a4a6a4cea8f6f8836c6e6d`。源文件完整解码和 hash 校验通过，不能诊断为音频损坏或无声。

原 job=`50858dcd-8eb5-4fa5-b447-c4d2be6fce34`，attempt=`a0e661fa-a35f-42d0-a7d5-3e445ecb6220`，851 s 后仅记录 `ValueError`。专用诊断 job=`d08c2af5-dcfa-4a12-bd5a-cdbf6b9428e7` 再次失败，捕获到 1179 个原始 segments，其中第一段 start=0、end=0、文本 7 字符；仅这一段区间非法，校验文本为 `end_ms must be at least 1`。coverage≈0.998733751，不能用覆盖率良好代替区间合法性。

20:51 四个 ASR failed job 实际属于三个视频：两个超时视频已有成功替代，**真正尚未得到可用 ASR 的是本视频**，并非四个视频都未完成。

## 可以确认与尚不能确认的因果

当前 `asr/alignment.py` 的 `_thread_text` 对未匹配字符使用零跨度 anchor，`_aligned_cues.close` 在没有前一 cue 可合并时仍可输出该段。离线合成复现，无网络/模型调用：

```python
from bili_asr.asr.alignment import _thread_text, _aligned_cues
_aligned_cues(_thread_text("未对齐开头。", []))
# [{'start': 0.0, 'end': 0.0, 'text': '未对齐开头。'}]
```

已证明源码可以产生该类非法 cue，也证明生产最终输出存在此 cue；尚未保存生产对应的全部 aligner units，**不能断言原始对齐器为何没有给首句时间**。需补齐匹配/对齐证据再归因。

旧安装 runtime 在构造 TranscriptSegmentRecord 时先失败，原始输出未走当前源码的 `preserve_inference/assess_output`。#410 已处理早期质量准入；本单关注上游 alignment 的零时长产出及这个真实样本，部署激活另单跟踪。

## 验收与恢复边界

- [ ] 未对齐首句、完全空 units、部分 units 和跨 chunk 边界都有明确诊断与原始文本/时间证据，区分 inference 完成和 transcript 可用。
- [ ] 不以删除首句、盲目 +1ms、排序/clamp 或绕过 WebVTT/质量门禁伪造成功；修复需验证音频和对齐，有依据地重新对齐或明确拒收/hold。
- [ ] 原始失败、完整 raw 输出及冻结 profile 保持可追溯；成功修复生成新身份，并验证 intervals、覆盖、全文保留及最终发布。
- [ ] 现有 coverage≈99.87% 的结果仍会被非法 interval 拒收；后续 AI 不消耗在未通过准入的输入上。

诊断 profile 只将 timeout 从 1800 改为 1801 来取得新任务身份并捕获输出，这不是修复。原始正文只在私有证据中保存，不贴到 issue。证据：`asr-diagnostic-BV1PM411U789-20261015.json`、私有 `asr-raw-BV1PM411U789-20261015.json`、`offline-reproduction.json`。

## 证据口径

本单来自 UID `23191782` 生产运行复盘。主要只读快照为 **2026-10-15 20:51–21:03 +08:00**，每项另注明证据时间；数量不是实时仪表盘。运行包来自服务器 venv 的 `site-packages`，版本字段为 `0.1.0`，不能据此认定它等于 main。核对时 main 为 `3d5ed3af653c11f6ac4757c8180ebd350df871a3`；本地检查基线为 `e57edff`，另有未提交的请求资源清理补丁。

原始数据库、音频、模型正文和连接凭据未上传。生产 JSON 证据保存在服务器 `production-ops-23191782/` 及本地 `.tmp/production-issue-audit-20261015/`；本单内列出可以公开复核的计数、标识和合成复现。保留旧 attempts、冻结输入和 retry holds。

### [生产复盘/P1][deployment] 已关闭修复未等于运行进程生效：安装包、磁盘补丁与内存代码缺少可核验版本

https://github.com/SuperCatQR/bilibili-asr-archive/issues/453

## 已发生的问题与影响

生产当前执行 venv 的 `site-packages/bili_asr`，版本只标 `0.1.0`，部署目录没有可识别 commit/deployment manifest，也不是可直接核对 HEAD 的 Git checkout。仓库的修复关闭状态无法证明生产加载了它们。

已确认的具体差异：

1. 安装 runtime 的 ASR handler 未见当前源码的 `preserve_inference` 路径；零时长段在构造记录阶段直接抛 ValueError，损失自动保留 raw 的机会。
2. 请求资源清理补丁已写服务器磁盘，新进程 100 loops 验证通过，但常驻 PID 8037 仍加载旧代码，依靠提升 FD 上限运行。
3. **2026-10-15 13:24:50 +08:00** 采集恢复时实际出现 `ModuleNotFoundError: No module named 'bili_asr.source_observations'`，watch 随后 `needs_attention`。说明单文件复制存在模块边界不兼容；之后已恢复可运行状态，不能把此错误描述成当前仍持续。
4. 已知错误分类/恢复功能在源码存在，旧生产 attempt 仍只记录 generic 类名；必须逐功能验收，不能整体推断 main 的全部修复都缺失。

## 故障链与规模

`仓库完成修复 → 旧 wheel/运行包或局部文件热补丁 → 新旧模块混合/进程未重新加载 → ImportError 或旧行为继续 → 运维按仓库状态误判修复完成 → 同类故障继续积累`。

影响横跨 metadata、subtitle/publish、ASR admission、editorial diagnostics 和 retention 的运行版本确认，不等于这些功能现在全部故障。20:51 ASR 4 running、GPU 100%、subtitle/publish 没有当前失败，说明流水线仍部分健康。需对真实 worker 而非本地源码作验收。

## 建议交付与验收

- [ ] 交付不可变构建，记录 source SHA、wheel SHA、依赖锁/实际安装、模型 revisions、DB contract、配置摘要；兼容热补丁有单独 overlay 标识和回滚包。
- [ ] 每个受管 PID 暴露启动时间、加载构建版本、角色、ready/draining/degraded；磁盘文件 hash 不冒充内存已激活。
- [ ] 对完整候选包做 import、DB 兼容、无网络 fixture、真实 GPU 小样本及长样本的分阶段验收，避免再单文件覆盖新版模块到旧包。不能只凭 `pip check` 证明 GPU 栈兼容，参考 #439。
- [ ] 制定排空、lease 收敛、备份、切换、失败回滚和重启验收流程；不覆写原 attempts、冻结输入和 retry holds。
- [ ] 明确部署 #410、#366/#367、#406、#350 的真实验收状态；交付清单区分 source-delivered、installed、loaded、production-verified。
- [ ] 汇总外部 controller 与独立 AI scheduler 的角色范围：当前 controller 的 ai_enabled=false 与 DB 六个校对 running 共存，不能将单 controller 开关当作全系统 AI 状态。

#300 已涉及部署清单/ready；本单补充**真实混装失败、磁盘与进程分离及这轮修复落地**的生产闭环，不重开旧设计。20:51 模块 hash 证据：workflow_runtime.py=`ba04512360d8046884eca6608984a93a08c505c164df51fd7509d31ba40a9835`；asr/session.py=`37b2748a2df827ccefbca79cd7f55a4484123cd6ea1b1bb2878d14f6d050ba39`。证据：`production-issue-audit-20261015.json`、`production-issue-dependencies-20261015.json`、metadata 对应时间日志。

## 证据口径

本单来自 UID `23191782` 生产运行复盘。主要只读快照为 **2026-10-15 20:51–21:03 +08:00**，每项另注明证据时间；数量不是实时仪表盘。运行包来自服务器 venv 的 `site-packages`，版本字段为 `0.1.0`，不能据此认定它等于 main。核对时 main 为 `3d5ed3af653c11f6ac4757c8180ebd350df871a3`；本地检查基线为 `e57edff`，另有未提交的请求资源清理补丁。

原始数据库、音频、模型正文和连接凭据未上传。生产 JSON 证据保存在服务器 `production-ops-23191782/` 及本地 `.tmp/production-issue-audit-20261015/`；本单内列出可以公开复核的计数、标识和合成复现。保留旧 attempts、冻结输入和 retry holds。

### [生产复盘/P1][ingestion] UID 采集在第 30 页持续限流，九小时无进展且缺少持久无进展预算

https://github.com/SuperCatQR/bilibili-asr-archive/issues/454

## 规模和当前阻塞

目标 UID `23191782`，20:54 按 UID 精确过滤为 **861 个视频 / 864 个分 P**。上游已观测总数 1691，cursor.next_page=30；数据库全库的 870 视频/873 分 P 包含非目标样本，不能用全库数报告目标进度。

目标已发现数约占该上游快照的 50.92%，差值 **830（49.08%）**。这是相对于 `observed_total` 的待核对缺口，**不是已证明永久漏采 830 个**；上游列表会变动，最终全量完成需边界核对。

watch 从 **11:18:27 到 20:24:29 +08:00** 的 13 条 cooldown 记录均为 page=30、videos=861、reason=rate_limited；退避已升到 3600 秒，期间还发生一次重启/恢复并重置短退避。两个端点之间约 9 小时 6 分无发现进展。最后状态 cooldown，但 DB cursor_state=ready、cursor_error=null，仅说明可续跑，不能解释为全量任务健康或完成。

## 故障链与确认边界

`B站 rate_limited → 当前页终止、exit 2 → 外部 watch 900/1800/3600 s 后重试同页 → 连续失败但缺少跨重启无进展预算和升级动作 → 剩余视频无法发现 → 其音频/ASR 永远不会进入队列`。

之前 auth_error 与 rate_limited 都有出现；凭据更换后曾从第 11 页推进到第 30 页，但后续仍限流。现有证据不能判定是 IP、账号、接口或请求分布中的哪一个因素，也不能从 generic `rate_limited` 反推精确 HTTP/API code。增加等待不保证解除风控。

## 建议交付与验收

- [ ] 跨进程重启持久保存最后进展时间、连续失败数、累计退避、页/边界、上游分类、策略版本和下次动作；重启不自动清零无进展预算。
- [ ] 区分 resumable、cooldown、degraded/needs_attention、verified complete；可续跑不等于完成，失败页计数不当作已成功采集页。
- [ ] 在可配置无进展阈值后给出明确升级/人工动作，保留有限、可取消的尝试；credential 预检、每操作分类和共享请求预算可观测，不堆叠无界重试。
- [ ] 在正常受支持访问条件下按共享来源风险预算恢复；验证阶段保留请求时间/分类和进展证据，不尝试绕过验证码或风控。
- [ ] 正常恢复后核对动态列表边界、去重和观测总数变化，再声明 UID 全量完成；保留原 run/page 失败证据。

#255 是较早的单次真实 rate_limited，#305 处理动态分页完整性，#306 处理操作级 retry。本单新增的是本轮**持续无进展的监督预算与全量交付阻塞**，不将外部限流本身伪装成已找到的代码根因。证据：`metadata-resume-watch-state.json`、`production-issue-dependencies-20261015.json` 的 13 条 cooldown 记录和对应 metadata 日志。

## 证据口径

本单来自 UID `23191782` 生产运行复盘。主要只读快照为 **2026-10-15 20:51–21:03 +08:00**，每项另注明证据时间；数量不是实时仪表盘。运行包来自服务器 venv 的 `site-packages`，版本字段为 `0.1.0`，不能据此认定它等于 main。核对时 main 为 `3d5ed3af653c11f6ac4757c8180ebd350df871a3`；本地检查基线为 `e57edff`，另有未提交的请求资源清理补丁。

原始数据库、音频、模型正文和连接凭据未上传。生产 JSON 证据保存在服务器 `production-ops-23191782/` 及本地 `.tmp/production-issue-audit-20261015/`；本单内列出可以公开复核的计数、标识和合成复现。保留旧 attempts、冻结输入和 retry holds。

### [生产复盘/P1][backup] 非破坏性音频复制被所有后续任务状态阻塞，515 个已完成 ASR 文件约 8.12 GiB 无法入选

https://github.com/SuperCatQR/bilibili-asr-archive/issues/455

## 当前行为、规模与风险

生产使用外部 `audio-backup-local.py` 将音频备份到本机指定目录。候选 SQL 要求 ASR succeeded，并且同音频关联的**所有** workflow job 都 succeeded；因此尚未运行的 proofread/render、cancelled job 和已有成功替代的旧失败 ASR 都能阻止非破坏性的备份复制。

20:54 候选核算：有成功 ASR 的 766 个音频对象，仅 218 个符合当前 SQL，548 个排除。阻塞状态包括 proofread queued=530、failed=12、running=6、cancelled=1、render queued=548/cancelled=1、旧 ASR failed=2；这些是重叠集合，不能相加。

20:56 进一步核对实体文件：

- 服务器实际存在 568 个音频对象，9831810864 bytes。
- 其中 **515 个已成功 ASR、实体仍存在但被复制候选排除**，共 **8717169887 bytes ≈ 8.12 GiB**。
- 另有 211 个实体已不在服务器，对应逻辑大小 5551844200 bytes；已有删除报告确认之前逐一检查并删除 211 个已验证备份文件，不能将缺失实体直接当数据丢失。
- 20:51 数据盘总量 50 GiB、剩余 14.679 GiB。上述 8.12 GiB 是被阻止复制的源数据体量，**不等于现在可以安全立即释放的空间**。

两次 SQL 快照在持续运行中采集，分母会变化，不应混用成静态等式。

## 故障链

`复制与释放条件混用 → AI queued/失败或历史失败阻止复制 → 本机备份滞后于 ASR → 源音频持续占数据盘 → 下载闸门/磁盘压力降低管线吞吐`。

实际删除已有一轮人工校验报告；本单关注外部部署脚本与正式 retention 的接入缺口，不声称项目没有备份/retention 功能。#406 已交付相关能力，需要落到当前生产。

## 修复范围与验收

- [ ] 分离复制资格、校验收据和源副本释放资格。ASR 完成且源身份稳定时可做非破坏性复制；需要音频的当前消费者、hold、修复任务用 pin/fence 阻止不安全释放，而非阻止增加副本。
- [ ] 历史失败是否阻塞释放根据实际消费者和显式 supersession 决定，不能因同 part 存在永久 failed 行就永远失去备份资格；也不能忽略仍引用旧输入的真实消费者。
- [ ] 接入 artifact catalog/版本化 manifest/hash/verified receipt，重启后可恢复，目标不可达、复制不完整、磁盘不足和校验失败不会删除源副本。
- [ ] 用户已给定备份目标和释放已验证源音频的运行政策，应让政策可持久、可审计地执行，不靠再次临时手工扫文件。
- [ ] 对 queued AI、失败后成功替代、cancelled 旧链、活跃 ASR、唯一可用副本、目标断线分别验证；公布 copy backlog 和 release blockers 各自数量。

证据：外部 helper 的 `QUERY`、`production-issue-dependencies-20261015.json` 的 backup_candidate_counts、`production-issue-impact-20261015.json` 的 audio_inventory、`delete-verified-audio-report.json`。原始目录和 hash 在私有运维证据保存。

## 证据口径

本单来自 UID `23191782` 生产运行复盘。主要只读快照为 **2026-10-15 20:51–21:03 +08:00**，每项另注明证据时间；数量不是实时仪表盘。运行包来自服务器 venv 的 `site-packages`，版本字段为 `0.1.0`，不能据此认定它等于 main。核对时 main 为 `3d5ed3af653c11f6ac4757c8180ebd350df871a3`；本地检查基线为 `e57edff`，另有未提交的请求资源清理补丁。

原始数据库、音频、模型正文和连接凭据未上传。生产 JSON 证据保存在服务器 `production-ops-23191782/` 及本地 `.tmp/production-issue-audit-20261015/`；本单内列出可以公开复核的计数、标识和合成复现。保留旧 attempts、冻结输入和 retry holds。

### [生产复盘/P2][workflow] 替代 ASR 已成功但原校对依赖仍指向失败 job，两个视频四个下游任务永久等待

https://github.com/SuperCatQR/bilibili-asr-archive/issues/456

## 已确认的阻塞与规模

2026-10-15 **21:03:18 +08:00** 只读检查每个相关 part 的全部 job 和依赖；两个超时输入已通过新 profile 重新 ASR 并发布，但没有对应新 proofread/render 链。

| part / 视频 | 原失败 ASR | 成功替代 ASR | 仍 queued 的 proofread | 仍 queued 的 render |
|---|---|---|---|---|
| 460 / BV1ck4y1N7pQ P1 | d481ac0f-784c-4753-8dde-6a75fe86f7f6 | cdae00eb-29c0-4676-8cf5-e909280a750b | ca0e7f63-3118-4148-be00-09a4822910f8 | 1e1fc980-8d21-4f68-b079-9219bad5cbdc |
| 675 / BV1TG411M7KG P1 | 1de28014-a66d-4602-8997-4f53ccca1c59 | 67c2f590-5a16-4a0a-ab7c-a0974ddbaafa | 47e45f98-8f79-46ad-ad87-0b20e5c2aa5f | a688e305-f74d-4b9f-9666-4e8534dca713 |

两个 proofread 的 payload.asr_job_id 及 workflow_job_dependencies 均指向**原失败 ASR**；attempt_count=0。仅这两个 part 就有 **2 个直接阻塞校对 + 2 个间接阻塞文档**。发布成功不代表阅读稿恢复。原有失败记录应该保留，问题不是历史行本身。

## 故障链和责任边界

`原 ASR 超时 → 运维修复新建 ASR profile/job → 只规划了 ASR，proofread_jobs=0/document_jobs=0 → 成功结果与原冻结 proofread 依赖无关联 → 原链永远不可领取 → status 仍只表现 queued → 备份资格还可能被旧链阻塞`。

`workflow_planning.editorial_specs` 和输入哈希本来就按 ASR job 身份冻结，这是正确的可追溯语义。不能自动把旧 payload 改成新 job。缺口是**显式恢复操作的下游对账与完成判定**；本单不声称普通 scheduler 应自动改写输入，也不要求自动开启未授权 AI。

## 修复与验收

- [ ] 提供恢复 plan/dry-run，列出成功替代、仍引用旧 job 的消费者、受影响文档、预算与备份阻塞；明确区分 producer recovered / delivery recovered。
- [ ] 在既有 AI 政策授权下，按成功替代 ASR 建立新的冻结 proofread/render 身份，并显式记录 supersedes / recovery link。若 AI 暂停，则记录明确待恢复动作。
- [ ] 原链不篡改历史 payload/attempt；按显式规则退休/标记 superseded，避免永久 queued 伪装成普通 backlog。
- [ ] 操作幂等；二次执行、进程中断、并发 scheduler 不重复付费/提交，不绕过质量 gate 或 lease。
- [ ] 用这两个真实 part 验证完整链能恢复，保留两次原超时证据。status 同时显示直接/间接阻塞和旧链替代状态。

#365 已提供失败与历史区分，本单处理的是**成功替代后的实际 DAG 收敛**。证据：`production-issue-recovery-chain-20261015.json`；第一条恢复报告中明确 plan proofread_jobs=0 / document_jobs=0。

## 证据口径

本单来自 UID `23191782` 生产运行复盘。主要只读快照为 **2026-10-15 20:51–21:03 +08:00**，每项另注明证据时间；数量不是实时仪表盘。运行包来自服务器 venv 的 `site-packages`，版本字段为 `0.1.0`，不能据此认定它等于 main。核对时 main 为 `3d5ed3af653c11f6ac4757c8180ebd350df871a3`；本地检查基线为 `e57edff`，另有未提交的请求资源清理补丁。

原始数据库、音频、模型正文和连接凭据未上传。生产 JSON 证据保存在服务器 `production-ops-23191782/` 及本地 `.tmp/production-issue-audit-20261015/`；本单内列出可以公开复核的计数、标识和合成复现。保留旧 attempts、冻结输入和 retry holds。

### [生产复盘/P2][editorial] content_filter 与未知 finish_reason 被统一判为截断，恢复策略缺少准确终止原因

https://github.com/SuperCatQR/bilibili-asr-archive/issues/457

## 真实故障与规模

12 个失败 proofread 中有两条 provider 输出问题，其余 10 条是严格响应契约拒收。provider 两条分别为：

1. BV1FbX3YMEb9 P1，job=`4f3ebb71-0423-4b82-af7e-d8f1f89d64d6`，call=`6f421b24edcb45d4a6afa48445d835c3`，chunk=`9f62b38e15ed5404:1010-1051`。原响应 **finish_reason=content_filter**，输出正文为空；provider usage prompt=10305、completion=16673、reasoning=15100。旧 runtime 仅记 DeepSeekError，回放消息为 `output is truncated or unfinished`，length_exceeded=false。不能将它说成长上下文截断或推断提高 max_tokens 能解决。
2. BV1z7ryYeEti P1，job=`8d88a696-701b-42c2-a5c5-76656d32b3e8`，call=`016db633e3a746aab2b063362a985717`，finish_reason=stop，但无正文；usage completion=reasoning=7639。可确认响应没有可用稿件，不能由此断定网络没返回或音频无声。

两条各直接阻塞一条 render。usage 是返回计数，不是实际收费凭证；不据此估计金额。

## 当前源码仍可复现的缺口

`deepseek.parse_response` 将任何非 stop 理由映射为 `deepseek_output_truncated` / `unfinished_output`，仅保存 length_exceeded 布尔值，没有保存原始受控 finish_reason。合成 envelope 在当前源码离线回放：

```python
{"choices": [{"finish_reason": "content_filter", "message": {"content": ""}}]}
# error_code=deepseek_output_truncated, length_exceeded=False
# 未知 reason 也走同一分类
```

`length`、内容过滤、其他 provider 中止原因的后续动作不同。现在仍拒绝无效输出是正确行为；需要改善的是分类和恢复决策，而不是放宽输出门禁。

## 验收与边界

- [ ] 以有限枚举区分 length、content_filter、tool_calls/unsupported、未知中止与 stop-but-empty，并在 safe diagnostics 记录经过白名单归一化的理由；未知原始字符串不能无限长入库。
- [ ] content_filter 明确进入需审阅/终止政策，不被当作可通过加 token 或原样自动重试治愈的截断；不要尝试规避 provider 过滤。
- [ ] 空输出和 provider 中止仍保留原 request/response、usage、call/chunk 身份；受预算/取消/lease 约束，成功检查点不无谓重跑。
- [ ] 离线 envelope 回放覆盖 stop-valid、stop-empty、length、content_filter、未知及缺失 reason，status/next action 与语义一致；不需要新增付费调用验证分类。
- [ ] 旧 attempt 不回填伪造分类，可以通过关联的保留 envelope 输出 derived diagnostic 并注明回放来源。

本单补充 #366/#367 的非 stop 理由细分；#350 的有限块恢复与 schema 拒收是相关但不同问题。证据：`production-issue-impact-20261015.json` 的 editorial_failure_safe；`failed-editorial-inspection-20261015.json`；`offline-reproduction.json`。

## 证据口径

本单来自 UID `23191782` 生产运行复盘。主要只读快照为 **2026-10-15 20:51–21:03 +08:00**，每项另注明证据时间；数量不是实时仪表盘。运行包来自服务器 venv 的 `site-packages`，版本字段为 `0.1.0`，不能据此认定它等于 main。核对时 main 为 `3d5ed3af653c11f6ac4757c8180ebd350df871a3`；本地检查基线为 `e57edff`，另有未提交的请求资源清理补丁。

原始数据库、音频、模型正文和连接凭据未上传。生产 JSON 证据保存在服务器 `production-ops-23191782/` 及本地 `.tmp/production-issue-audit-20261015/`；本单内列出可以公开复核的计数、标识和合成复现。保留旧 attempts、冻结输入和 retry holds。


已有校对恢复工单的补充证据：https://github.com/SuperCatQR/bilibili-asr-archive/issues/350#issuecomment-6193345654
