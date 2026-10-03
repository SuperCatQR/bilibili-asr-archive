# 下一迭代方向候选 —— 登记（未锁定）

> **状态：candidates registered, not locked。** 本文档只做两件事：把 2026-10-03 这一轮真机验证挖出的方向按可执行性排序，并说明**为什么现在不开迭代**。方向锁定的决定权在操作者；`/iteration-start` 会在 Phase 1 用 grill-me 收敛成单一方向并落 compass。
>
> 记录时间 2026-10-03。所有条目都以 store 里已登记的 issue 为准（`disposition=open`），不重复登记。

## 为什么现在不开迭代（阻塞事实）

**`iter-2026-10-ledger-integrity` 仍然 active**：

```
plans: caption-writeback-guard(Todo) journal-replay-integrity(Todo)
       asr-run-id-uniqueness(Todo) journal-compaction-lifecycle(Todo)
```

再起一个迭代会让 `status.json` 出现**两条活跃生命周期**，而引擎在这种状态下会拒绝一切需要工作流绑定的操作（本会话实测过 `workflow.selection.unbound-multi-active`：`writes pause until then`）。更实际的是：**这一轮查出的大部分东西，已经属于那个迭代了**——见下方 A 组。

## A. 已被活跃迭代覆盖（不要重复规划）

这一轮独立挖出的四个高危项，与 `iter-2026-10-ledger-integrity` 的四个 plan 是**同一批**：

| 本轮发现 | issue | 活跃迭代对应 plan |
|---|---|---|
| `kind='asr'` run 永不结束、selector 记错、language 落 `und` | `I-000182`(medium) / `I-000183`(low) / `I-000184`(low) | `asr-run-id-uniqueness`（同一条 write-back 链） |
| caption write-back 在 success guard 内 | `I-000165` | `caption-writeback-guard` |
| journal 回放被 `str.splitlines()` 截断 | `I-000164` | `journal-replay-integrity` |
| journal 无 compaction、`save()` 顺序反 | `I-000167` / `I-000170` | `journal-compaction-lifecycle` |

**结论**：A 组不需要新迭代，需要的是把 `I-000182`/`183`/`184` 三个小项**并入**活跃迭代对应的 plan 验收面（或在其 plan 收口时作为同族残余处理）。这是 `iter-2026-10-ledger-integrity` 的收尾工作，不是新方向。

## B. 未规划、且值得成为下一迭代方向

### B1（推荐，high）— 空字幕清单不得被当作"字幕耗尽"

- **issue**：`I-000187`（high，2026-10-03 本轮真机测得）
- **实测证据**：`BV1YFEUzpEsT:p0` 与 `BV1qR7az2EzY:p0` 在选片时都被 `probe-subs` 报 `tracks=0 / (no subtitles visible) / failed=0`；随后 `harvest-subs` 为两条**都存下了 `subtitle-ai ai-zh`**；几分钟后复探变成 `tracks=1 track ai-zh ai 中文`。对照 `BV1aAhLzsENb:p0` 三次探测都是 `tracks=0`（真的没有）。**同一 part、同一命令、只差时间，答案翻转。**
- **为什么是 high**：`no-subtitle` 是进入**付费分支**（下载音频 + GPU ASR）的入场券——`v_missing_audio` 只认"最新尝试为 `no-subtitle`/`failed` 且无音频证据"。一次瞬时空清单，就能让一个其实有字幕的 part 走完整条 GPU 路径。本轮**已经为这样一个 part 付过 GPU 时间**。
- **与 `I-000041` 的关系（必须写清，否则会误以为已覆盖）**：`I-000041` 把空清单归因于**失效的 SESSDATA**；`I-000187` 是**凭据有效时**测到的同一现象。**只修 `I-000041` 关不掉 B1。** 网关自己的契约就把混淆写在明处：*"An inventory the credential in effect could not see is an empty tuple — never a `not_found` failure"* —— "看不见"与"不存在"压成同一个返回值。
- **建议做法方向**（供 grill 收敛，不是 lock）：让"空且未验证"不再等于"已耗尽"；或把该次观测记为可区分状态（如伴随 `unverified` 类错误码），使**单次空清单不能持久地把一个 part 判为无字幕**；并让 `probe-subs` 与 `harvest-subs` 对同一 part、同一时刻给出**一致**答案。
- **规模**：S（1 个业务 plan）。`bilibili-asr-archive/src/bili_asr/services/subtitle_ingest.py:424-433`（`_probe_part`）、`:438-487`（`_acquire_part`）、`src/bili_asr/sources/bilibili_api_gateway.py:924-941`（`get_subtitle_tracks`）、`src/bili_asr/storage/schema-transcripts.sql:185-220`（`v_missing_audio`）。

### B1b（强烈推荐，high）— ASR 转写必须声明覆盖范围，不得静默成功

- **issue**：`I-000188`（high，2026-10-03 校对链 E2E 测得）
- **实测**：`BV1YFEUzpEsT:p0` 的归档转写为 **13 段、跨度 0.0–59.0 s**，而解码音频 **73.561 s**（新下载全长，`_read_audio` 复测一致），**20% 的语音未被触及**；`video_parts.duration_ms=74000`。同一 p0 的 store 尝试为 `outcome=stored`、bundle 为 `archived`、四族产物齐全、**无 error_code、无告警**。
- **归因（逐步实测，非推理）**：① 不是下载——新下载 303,078 B / 73.561 s；② 不是 token 预算——`_MAX_NEW_TOKENS_PER_AUDIO_SECOND` 8→32（588→2352 tokens）输出**逐字节相同**；③ 不是静音——跳过区 −27.0 dB 均值 / −4.0 dB 峰值，对照已覆盖区 −26.0 / −4.0；④ **该区在自身电平下模型输出 0 字符，+20 dB 才出字**，而**真静音对照（67–73.5 s）任何增益都输出 0**、已覆盖区对照正常出字；⑤ 两个增益版本**互相不一致**且都不匹配字幕 → 该区是"难"，**不是**靠调增益可恢复。
- **为什么是 high**：这是**成功外观下的错误归档**——与 `I-000166`（run id 撞键静默跳过写回）、`I-000187`（空清单当耗尽）**同一失效类**：账本说成功，事实不是。
- **附带价值**：唯一发现它的机制是 `proofread` 的 **Guard A**——而这要求两条路线且是 opt-in、且在发布之后。**检测手段不能是校对链**（它需要"有字幕的 part 也跑 ASR"，而 store 路由永不给这个组合）。
- **规模**：S–M（1 个业务 plan）。`src/bili_asr/asr.py:1195-1221`（chunk 循环无覆盖率断言）、`:1097-1100`（预算，已实测排除）。
- **附**：同一轮席位源码核证另发现 `I-000189`（medium，`proofread-merge` 静默丢弃缺行块且仍计入台账、退出 0）与 `T4-F1`（low，spec `proofread.md:27` 措辞过宽）——若开校对方向的迭代，两者是同族残余。

### B2（可选，medium）— 登记系统的"已验证但关不掉"死角

- **issue**：`I-000186`（medium，2026-10-03 本轮登记）
- **实测**：关闭 issue 要过四道门（`authorizeMutation → readScopedSession → assertEngineIssuedSession → liveSnapshotOf/planSessionBinding`），四道全部用真实调用复现过拒绝。**全库 32 条 resolved 全部来自 legacy import，靠活通道关闭的是 0；issue→plan provenance 链接数是 0**。
- **后果**：本轮把 `I-000067`/`I-000149` 证伪得干干净净（12 个 witness 测试 + 真机 S6），**却无法把结论写回 store**——计数永远偏离事实，下一个人会重新审一遍已有定论的东西。
- **注意**：这**不是**产品缺陷，是 harness/注册系统缺陷。是否纳入**产品**迭代需操作者裁决；也可以走 harness 侧渠道单独处理。
- **规模**：S 或跨系统单独立项。

## C. 明确不做（本轮已判定或需操作者输入）

| 项 | 理由 |
|---|---|
| 重开 `I-000067` / `I-000149` | 已证伪 stale（12 个 witness 测试 + 真机 S6）；只差登记动作，见 B2 |
| `I-000039`（123pan 挂载鉴权失败销毁暂存音频） | 该挂载操作者已确认彻底废弃、不再恢复 —— **无修复对象** |
| `I-000136`（锁重生成静默拉 PyPI CUDA torch） | 已有 WARNING 注释与 recipe 兜底；属"流程纪律"，不是代码缺陷 |
| `I-000185`（健康归档上 verify/coverage 退出 1） | 本轮 S8 已判 `failed(partial)`；修法需先定"证据侧车该不该由 CLI 写"的产品决定 |
| `I-000102`(真机人工抽检) | 本轮 S11 已交付（8 块人工判定），可结 |
| 候选集扩页 / 更大语料 | 与 B1 无关，且会放大风控面 |

## D. 操作者需要决定的三件事

1. **是否先收口 `iter-2026-10-ledger-integrity`**（它已有 4 个 Todo plan）。收口后 B1 可以干净地成为下一个迭代的唯一方向（规模 S，符合"小迭代"）。
2. **B1 是否单独立迭代**，还是并入 ledger-integrity 收尾作为第 5 个 plan（会超该迭代已锁的 Scale L 上限 4）。
3. **B2 走产品迭代还是 harness 侧单独处理**。

## 引用

| 内容 | 路径 |
|---|---|
| 本轮真机验证报告（含 5 条 findings 与三份更正） | `.mstar/workflows/e2e-23191782-store-writeback-chain/reports/e2e.md` |
| 本轮 12 个 witness 测试记录（`1e756df`，12 passed） | `.mstar/workflows/e2e-23191782-store-writeback-chain/evidence/logs/pytest-witnesses.txt` |
| 空清单翻转的原始探测记录 | `/root/e2e-asr/asr-two-video-batch/evidence/{probe2-matrix,harvest,reprobe,reprobe-store}.txt`（算力机 `192.168.3.21`） |
| 两条真实视频的 ASR 产物 | `/root/e2e-asr/asr-two-video-batch/artifacts/transcripts/{BV1YFEUzpEsT,BV1qR7az2EzY}.p0/` |
| 上个迭代的锁定记录格式（本文档照其结构） | `.mstar/iterations/iter-2026-10-ledger-integrity/direction-lock.md` |
