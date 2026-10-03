---
plan_id: caption-exhaustion-attestation
project: _default
status: draft
created_at: 2026-10-03
execution_mode: inline
plan_parallelism: serial
---
# Plan caption-exhaustion-attestation — Make a part's caption exhaustion attestable so an unseen inventory cannot admit a part to the paid branch

**Main worktree branch**: `main`（control root 驻留分支；本 plan 不切换。**重新观察于 2026-10-03 21:57**：原记录为 `dev` —— 并行会话移动了共享 control root（reflog `dev → e2e → main → thinking → main`），root 已稳定驻留 `main` 逾 4 小时，故按契约 §2.3 step 2 重新观察并记录，非静默编辑）

## Status
- **Priority**: P1
- **Effort**: S–M
- **Risk**: MED（触及队列准入视图，影响面已知且被具名）
- **Confidence**: HIGH（现象真机复现；修法已由 architect 轮收敛，见 `{ITERATION_DIR}/iter-2026-10-asr-success-attestable/specs/architect-decisions.md` D10）
- **Fingerprint**: e2e-2026-10-03/caption-empty-inventory
- **Depends on**: none（与 `asr-coverage-attestation` 无代码依赖；两者是同一方向的两条 leg）
- **Category**: bug
- **Evidence**: `bilibili-asr-archive/src/bili_asr/services/subtitle_ingest.py:424-433`（`_probe_part`）、`:438-487`（`_acquire_part`）；`src/bili_asr/sources/bilibili_api_gateway.py:924-941`（`get_subtitle_tracks` 的契约原文）；`src/bili_asr/storage/schema-transcripts.sql:185-222`（`v_missing_audio` 准入谓词）
- **Planned at**: commit `0773650`, 2026-10-03
- **Captured issue**: `I-000187`

## Problem

一个**空字幕清单**会被记为持久的 `no-subtitle`，即使凭据有效、且清单只是**这一次没看见**。而 `no-subtitle` 正是 `v_missing_audio` 准入**付费分支**（下载音频 + GPU ASR）的凭据。

本机实测（算力机 `192.168.3.21`）：

| 时刻 | 命令 | 结果 |
|---|---|---|
| 选片时 | `probe-subs --bvid BV1YFEUzpEsT` | `probe … tracks=0` / `(no subtitles visible)` / `failed=0` |
| 同上（第二 part） | `probe-subs --bvid BV1qR7az2EzY` | 同样 `tracks=0` / `failed=0` |
| 数分钟后 | `harvest-subs --bvid <两者>` | **两条都存下 `subtitle-ai ai-zh v1`**（`no-subtitle=0`） |
| 再数分钟后 | `probe-subs`（复探） | `tracks=1`、`track ai-zh ai 中文` |

**同一 part、同一命令、只差时间，答案翻转。** 对照：`BV1aAhLzsENb:p0` 三次探测都是 `tracks=0`——那一个是真的没字幕。**所以单次探测区分不了"真的没有"与"这次没看见"。**

### 契约里写着这个混淆

`get_subtitle_tracks` 自己的 docstring（`:927-933`）：

> *An inventory the credential in effect could not see is an empty tuple — never a ``not_found`` failure and never a placeholder track.*

**"看不见"与"不存在"被压成同一个返回值**，而只有后者可以安全地当作耗尽。两条命令对同一现象的处理还不一致：`_probe_part` 把 `GatewayError` 单独处理（`error_code` 上浮），`_acquire_part` 把 `GatewayNotFound` 与"无匹配轨道"都归入 `_record_captionless_part`。

### 与既有 `I-000041` 的关系（必须写清，否则会误判已覆盖）

`I-000041`（high，open）把空清单归因于**失效的 SESSDATA**。本条的实测是**在凭据有效的情况下**（`probe-subs` 自报 `sessdata: present`，`harvest-subs` 随后成功取回字幕）。**两者是同一现象的不同成因，修 `I-000041` 关不掉本条。**

### 为什么值得 P1

后果是**花钱**：一次瞬时空清单就让一个其实有字幕的 part 进入"下载音频 + GPU ASR"。本会话已为这样一个 part 付过 GPU 时间（`BV1aAhLzsENb:p0` 的 S7/S6 真机跑）。同时它与 `I-000188` 是同一失效类的两面——一个是"没覆盖却说成功"，一个是"没看见却说耗尽"。

## Current state (excerpt — 动手前须对 live code 复核)

`subtitle_ingest.py`，两条路径的分歧点：

```python
# _probe_part  :424
try:
    tracks = await self._gateway.get_subtitle_tracks(item.bvid, item.cid)
except GatewayError as error:
    return SubtitleProbePart(work_id=item.work_id, tracks=(), error_code=error.code)
return SubtitleProbePart(work_id=item.work_id, tracks=tuple(tracks))

# _acquire_part :438
try:
    tracks = await self._gateway.get_subtitle_tracks(item.bvid, item.cid)
except GatewayNotFound:
    return self._record_captionless_part(run_id, item, "not_found", started_at)
except GatewayError as error:
    return self._record_failed_part(run_id, item, error, started_at)
track = select_subtitle_track(tracks, languages)
if track is None:
    # Either nothing was visible or nothing matched the requested languages …
    return self._record_captionless_part(run_id, item, None, started_at)
```

**注意 `track is None` 那支的注释自己承认了混淆**（"Either nothing was visible or nothing matched…"），而两种成因**记的是同一个 outcome**。

准入谓词（`schema-transcripts.sql:185-222`，`v_missing_audio`）：

```sql
JOIN subtitle_attempts AS latest ON latest.video_part_id = vp.video_part_id AND latest.recency = 1
...
AND latest.outcome IN ('no-subtitle', 'failed')
```

即：**最新一次**字幕尝试是 `no-subtitle` 或 `failed`、且无 `transcripts` 行、且无音频证据 → 进入付费分支。

### 具名的消费方（改前必须逐一复核）

| 消费方 | 位置 |
|---|---|
| `download-audio` 的取活 | `cli/_shared.py:161`（`_store_audio_todo`） |
| `asr` 的取活 | `cli/_shared.py:196`（`_store_transcript_todo`，读 `v_missing_transcript`） |
| `status` 展示 | `cli/status_cmd.py:65-66` |
| `pilot` 分支 | `cli/pilot.py:347`, `:578-581` |
| `queue` 注释所述的取反语义 | `cli/queue.py:256`, `:394` |
| `asr` store 源 | `cli/asr.py:128` |

## Invariant restored (target state, not the line moved)

**一次空清单不足以把一个 part 判为"字幕已耗尽"。**

修法的**具体形态**已由 D10 收敛、并经 **D11（操作者裁决 2026-10-03）改定载体**：

- **成因仍在记录层可区分，但不新增任何 `error_code` 取值。** 既有 `CHECK`
  （`schema-transcripts.sql:88-91`）只允许 `no-subtitle` 携带 `NULL` 或 `'not_found'`，
  且 schema 走 `CREATE TABLE IF NOT EXISTS`，既有库不重访该约束；扩宽词汇需要迁移故事，
  正是本仓“可重建、无就地迁移”决策要避开的。故 D10 提出的 `inventory-empty` /
  `no-language-match` **不落地为新的 `error_code` 值**。
- **载体改为 manifest 行上的观测计数**（D11 指定的「非 `error_code` 载体」）。实测依据：
  `validate_manifest_record` 末尾是 `return dict(entry)`（`manifest.py:105`），**不拒绝未知键**，
  故为零 DDL 改动。既有 `error_code IS NULL` 的历史行继续按“未佐证”处理（D10 的保守语义不变）。
- 准入谓词 `v_missing_audio` 的改写据此重写：indefinite 的判定读 manifest 侧的计数，
  而非 `error_code` 取值。

必须满足（不变）：
## Contracts to preserve (name these in the task report)

- `get_subtitle_tracks` 的契约原文（"empty tuple — never `not_found`"）：**改修法不得悄悄改这条契约**；若必须改，作为 spec 变更显式提出并说明消费方。
- `v_missing_audio` 的**既有语义基线**（其 SQL 注释 `:177-184` 记录了为什么 audio 证据只认 `part_audio_objects`、以及"探测尝试会反转信号"的理由）——改动须与那段理由一致，不得与之矛盾。
- `acquisition_attempts` 的 outcome 词汇与 `record_acquired_transcript` 的原子性契约。
- `_record_captionless_part` 与 `_record_failed_part` 的既有用途（`failed` 也进准入谓词，改语义时不要把失败误当耗尽）。

## Conventions to follow

- 本仓的注释记录**测量**（"measured:"）而非复述代码；新增注释同风格，并在此处给出本次实测的出处路径。
- 视图/SQL 改动须与既有迁移策略一致：**本仓 schema 可重建、无就地迁移**（上一迭代既有决策）；若需改视图定义，按"重建"路径处理并说明。
- 新增 outcome / error_code 词汇前，先列出全部**读取方**（上表）与**写入方**。

## Tasks

### Task 1 — 让耗尽判定可证实（Effort: S–M）

**Files**
- Modify: `bilibili-asr-archive/src/bili_asr/services/subtitle_ingest.py`
- Modify（D11 改定载体）: `bilibili-asr-archive/src/bili_asr/manifest.py`（观测计数字段，零 DDL）、`bilibili-asr-archive/src/bili_asr/services/subtitle_ingest.py`（记录成因）、`bilibili-asr-archive/src/bili_asr/storage/schema-transcripts.sql`（**仅当**准入谓词必须读 manifest 时，按重建路径处理并升级确认）
- Modify: `bilibili-asr-archive/tests/test_subtitles.py` / `tests/test_subtitle_cli.py` / `tests/test_storage_queue_gaps.py`（按现有覆盖选择）

**Change**
1. 按 D10 的语义 + D11 的载体实现：使"空清单"与"确无字幕"在**记录层**可区分（经 manifest 侧计数，**不新增 `error_code` 取值**），并让准入依新语义判定。
2. 让两条命令（`probe-subs` / `harvest-subs`）对同一现象给出一致答案（同义或可区分，但不得一个说"没有"、另一个说"有"却不留痕迹）。
3. 逐一复核上表六个消费方，在 task report 中具名说明各自受影响与否。
4. 保持"真的没字幕"仍能进入付费分支（见 Invariant 第三条）。

**In scope**: 上述文件；`bilibili-asr-archive/tests/` 中相关测试文件
**Out of scope**: `I-000041`（失效凭据路径——不同成因，另行处理）、ASR 覆盖率（另一 plan）、`I-000166` 的 run id

### Task 2 — 钉住翻转（Effort: S，同一轮）

加 witness，**离线可跑**（fake gateway）：

1. 构造"gateway 返回空清单"的场景，断言：该 part **不**进入 `v_missing_audio`（D10：单次观测不满足 `>= 2`）。
2. 构造"gateway 明确无轨道"（真耗尽）的场景，断言：该 part **仍**进入付费分支——防止过度修复。
3. 断言 `probe-subs` 与 `harvest-subs` 在**同一 fake 输入**下给出一致结论。
4. 记录 red/green 对：修复前第 1 条必须失败（以本会话的 tracks=0 → 字幕存下 的实测序列为 fixture 依据）。

## STOP conditions

- 若 `v_missing_audio` 的谓词与上方 excerpt 不再一致，STOP 并报告。
- 若修法必须**改 schema 且需要迁移**，STOP —— D11 已给出零 DDL 的载体（manifest 行），若实现中发现仍须迁移，说明载体选错或约束另有拦截，须先升级而不是自行迁移。
- 若发现"真的没字幕"的 part 会因为新语义被永久挡在付费分支外，STOP 并把两个方案代价报给 architect。
- 若 `I-000041` 的修复正同时改同一段代码（活跃迭代中），STOP 并回报冲突——**不要**与另一个 plan 并行改同一路径。

## Drift check

- 复核 `subtitle_ingest.py` 两条路径的行号与结构；
- 复核 `v_missing_audio` / `v_missing_transcript` 的谓词文本；
- 复核上表六个消费方仍存在且语义未变；
- 复核 `I-000041` 的状态是否已从 open 变化（若已修，重新评估本条是否仍独立）。

## Done criteria

- [ ] Task 1、Task 2 完成，Task 2 的 witness 在修复前**确实红**（保留 red/green 证据）
- [ ] 既有测试套件全绿（含 `test_subtitles.py`、`test_subtitle_cli.py`、`test_storage_queue_gaps.py`、`test_cli_queue_source.py`）
- [ ] 六个消费方逐一具名复核并记录
- [ ] "真耗尽仍进付费分支"有断言保护
- [ ] task report 记录：修法、D10 的选择依据、red/green、未做的部分与理由

## Verification notes

- 契约层 witness 必须**离线可跑**（fake gateway；不依赖 B站凭据与网络）。
- 真机复现通道（若需）：算力机 `192.168.3.21`，`probe-subs --bvid <bv>`（注意 `--bvid` 与 `--limit-parts` **互斥**，且 `probe-subs` 是只读命令）；凭据在 `/root/.config/bili-asr/session.env`。
- 本会话原始证据：`/root/e2e-asr/asr-two-video-batch/evidence/{probe2-matrix,harvest,reprobe,reprobe-store}.txt`

## Engine lifecycle ownership

plan 状态、snapshot 更新、QC/QA 与 Done 由 PM（coordinator）拥有；实现者不得自标 Done。
