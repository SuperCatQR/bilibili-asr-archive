---
plan_id: e2e-23191782-store-writeback-chain
title: "E2E: store-driven chain on the GPU host — caption/audio admission, ASR→store write-back convergence, reader exits"
type: verification/report-only
status: draft
target_ref: 1e756df
compute_host: chosenecho@192.168.3.21 (WSL2)
report_path: .mstar/workflows/e2e-23191782-store-writeback-chain/reports/e2e.md
created_at: 2026-10-03
author: project-manager
---

# E2E 计划（草案）：store 驱动链 — 字幕/音频准入 · ASR→store 写回收敛 · 读者出口

> 这是 **独立 E2E 验证**（`mstar-e2e`），不是开发迭代的一部分，也 **不** 进入任何开发 plan 的
> Acceptance Criteria。它只在操作者明确授权后执行；本文是待批准的草案。

## 1. 为什么是这一次

三个事实决定了这套场景，而不是别的：

1. **写回是全新的、从未在真机验证过。** `feat(asr): write local ASR transcripts back to the store (R14)`
   于 **2026-10-02** 落地（`11374d1` + `aee6f2e`），而最近一次完成的 E2E 在 **2026-10-01** 收口
   （`e2e-23191782-love-items-dual-route`）。**没有任何一次真机运行覆盖过这条写回路径。**
2. **它恰好是被放弃的那条链的修复。** `e2e-23191782-queue-ssot-chain` 于 2026-09-29 被操作者放弃
   （`status: stopped`，`reports/` 为空，一个场景都没跑），标题写的就是这条链：
   「caption-bearing vs caption-less admission、audio→GPU ASR→bundle、reader exits、store convergence」。
   当时链路是断的；现在缺口视图 + 写回都已在 HEAD。**这次是把它补跑。**
3. **静态阅读与真机证据存在未闭合的分歧点。** issue `I-000067`（high）断言
   「ASR 阶段写完 bundle 却不写 `transcripts` 行」——静态复核判定该 issue 在 `1e756df` 已 **stale**
   （`cli/asr.py:290` + `coordinator.py:990`，各由测试钉住），但这只是"读代码的结论"。
   本次运行是它的 **真机证伪/证实**。

`I-000102`（medium）另记一笔：**on-hardware 人工验收从未交付**。该笔默认仍不闭合，除非操作者启用
§7 的 S11。

## 2. 授权（执行前必须逐条确认）

| # | 授权项 | 状态 |
|---|---|---|
| A1 | 在 `192.168.3.21` 上运行真实 Bilibili API 调用（`fetch-meta`/`probe-subs`/`harvest-subs`/`download-audio`） | ☐ 待确认 |
| A2 | 在 AMD RX 7800 XT 上运行真实 ASR 推理（Qwen3-ASR-1.7B + ForcedAligner-0.6B） | ☐ 待确认 |
| A3 | 写根 **仅** `<RUN>`（§3）与既有 `$P/.venv` 的 `__pycache__` | ☐ 待确认 |
| A4 | **S0 检出同步**：把算力机 `main` 从 `d41c257` 换到 `1e756df`。这会替换工作树内容；未提交的 `asr.py` 热词补丁先存为证据文件再丢弃 | ☐ 待确认 |
| A5 | 不新增依赖、不装包、不跑 pytest 全量、不碰 `uv.lock` | ☐ 待确认 |

> **A4 是硬前置。** 算力机当前 `main = d41c257`（2026-09-26），**早于整条 store 驱动队列**：
> 没有 `src/bili_asr/cli/` 包（只有单文件 `cli.py`）、没有 `services/queue_source.py`、
> 没有 `v_missing_audio`/`v_missing_transcript` 视图、`asr --help` 里 **没有** `--queue-source`。
> 在 `d41c257` 上本计划的 S4–S7 全部无法成立。
> 若操作者 **拒绝 A4**，则 S4–S7 记为 `blocked`（缺失前置＝检出不含被测能力），
> 运行仍可完成 S1/S2/S3 三个场景并产出报告——**blocked 是合法且确定的结论，不是失败**。

## 3. 环境与判定基准（已实测）

- **算力机**：`192.168.3.21`，WSL2 `DESKTOP-HHFROLO`，Ubuntu 24.04.1，kernel `6.18.33.2-microsoft-standard-WSL2`，24 GB RAM
- **GPU**：AMD Radeon RX 7800 XT，`gfx1101`，ROCm `/opt/rocm-7.2.1`，`torch 2.9.1+rocm7.2.0.git7e1940d4`
- **解释器**：`$P/.venv/bin/python`（3.12.3）— `transformers 5.16.1`、`accelerate 1.15.0`、`soundfile 0.14.0`、`soxr 1.1.0`、`numpy 1.26.4`
  - ⚠️ `/root/gpu-venv` **没有 `accelerate`**，`device_map=` 加载路径会失败。**所有场景只准用 `$P/.venv/bin/bili-asr`。**
  - 该 venv 是 `.pth` 指向 `src/` 的 editable 安装 ⇒ **纯代码同步不需要重装**（已实测确认）。
- **模型**：`$P/models/Qwen3-ASR-1.7B-hf`、`$P/models/Qwen3-ForcedAligner-0.6B-hf`（共 5.6 GB）
- **凭证**：`/root/.config/bili-asr/session.env`（键 `BILI_SESSDATA`）/ 备用 `/root/.bili-sessdata`。
  `--sessdata` 接受 **值本身**，不是路径（`config.py:131 resolve_sessdata`）；留空/缺省回退 `BILI_SESSDATA`。
  **报告、日志、证据文件一律不得出现凭证值**（只记 presence）。
- **路径变量**（后文统一使用）：
  - `C=/root/workspace/bilibili-asr-archive`（算力机 checkout 根）
  - `P=$C/bilibili-asr-archive`（产品包根）
  - `RUN=/root/e2e-asr/store-writeback-chain`（**唯一授权写根**）
  - `ARCH=$RUN/archive`（`--archive-root`）· `ART=$RUN/artifacts`（`--artifact-root`）· `EV=$RUN/evidence`
- **通道**（远端登录 shell 是 `cmd.exe`，bash 必须走 stdin，禁止 `;` 串联到 cmd 层）：
  ```bash
  ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
      chosenecho@192.168.3.21 "wsl -e bash -s" <<'EOF'
  <bash>
  EOF
  ```
- **每个 `bili-asr` 调用前必须设的环境块**（无一处持久化在 shell profile 里）：
  ```bash
  export HSA_ENABLE_DXG_DETECTION=1
  export HF_HUB_OFFLINE=1
  export BILI_ASR_MODEL=$P/models/Qwen3-ASR-1.7B-hf
  export BILI_ASR_ALIGNER_MODEL=$P/models/Qwen3-ForcedAligner-0.6B-hf
  export BILI_ASR_DEVICE=cuda
  set -a; . /root/.config/bili-asr/session.env; set +a   # 提供 BILI_SESSDATA
  ```
  （变量名以 `asr.py:88-96` 为准；历史坑 `BILI_ASR_ALIGNER` 是错的，正确名是 `BILI_ASR_ALIGNER_MODEL`。）

## 4. 场景表

结果词汇严格限定 `passed | failed | not-run | blocked`，每场景恰好一个。证据 = 逐字命令 + 逐字输出（落入 `$EV/`）。
只读查库用 python（算力机上 **没有 `sqlite3` CLI**）：
`python -c "import sqlite3;c=sqlite3.connect('file:$ARCH/archive.db?mode=ro',uri=True);..."`

| ID | 场景 | 断言的期望 | 证据 |
|---|---|---|---|
| **S0** | 检出同步到基准（授权 A4） | `HEAD==1e756df`；`git status --porcelain` 为空；`bili-asr asr --help` 出现 `--queue-source`；`derive-manifest` 子命令存在 | 补丁文件 `$EV/s0-dirty-asr.patch`；`s0-identity.txt`（`rev-parse HEAD`、`bili-asr --help` 子命令计数=24） |
| **S1** | 环境能力门（两条臂都是断言） | 裸 `check-asr-env` → **exit 1**（`dxg-detection FAIL` + `device-probe FAIL`）；带 `HSA_ENABLE_DXG_DETECTION=1` → **exit 0**，输出 `device ok … arch=gfx1101 vram_gb=15.8` | `s1-bare.txt` / `s1-dxg.txt`（含 exit code）。这同时把 `I-000118` 的文档矛盾钉成证据 |
| **S2** | 全新 store 引导 + 元数据入库 | `fetch-meta --mid 23191782 --start-page 5 --limit-pages 2 --resume` 后 `archive.db` 存在；`video_parts` ≥ 57（实测页 5=29 行、页 6=29 行）。**页 6 已知首轮易挫**（13/13 `shape_error`+`risk_interrupted` 后重试成功）⇒ 允许重试一次并记录两次输出 | `s2-fetch.txt`；`s2-counts.txt`（`videos`/`video_parts`/`ingestion_runs` 计数） |
| **S3** | **字幕臂准入**：带 AI 字幕的 part | `harvest-subs --bvid <CAP_BV> --archive-root $ARCH` 后该 part 出现 `transcripts` 行 `source_kind='subtitle-ai'`；`v_missing_subtitle`=0；并且它 **不在** `v_missing_audio`、**不在** `v_missing_transcript` | `s3-harvest.txt`；`s3-store.txt`（该 part 的 transcript 行 + 三个视图计数） |
| **S4** | **音频臂准入（顺序断言）**：无字幕 part | **前置**：`v_missing_audio` 该 part = **0 行**（从未尝试）；`harvest-subs --bvid <AUD_BV>` 记录 `no-subtitle` 尝试后 → **= 1 行**；且该 part 无 `transcripts`、无 `part_audio_objects` | `s4-pre.txt` / `s4-harvest.txt` / `s4-post.txt`（两态对比是核心证据） |
| **S5** | 音频下载（字节 + store 对象） | `download-audio --bvid <AUD_BV>:p0 --archive-root $ARCH --artifact-root $ART` 后：`part_audio_objects` +1（`acquisition_source='download'`）；产物文件存在且 >0 字节；`v_missing_audio` 该 part=0；`v_missing_transcript` 该 part=**1** | `s5-download.txt`；`s5-pao.txt`；`s5-bytes.txt`（`stat`） |
| **S6** | **头条：ASR → 归档 + 写回 → 收敛** | 见下方 §4.1 明细 | `s6-asr.txt`（wall time）、`s6-store.txt`（全部断言 SQL 的逐条输出）、`s6-bundle.txt` |
| **S7** | 重跑不再花钱 | 同命令重发 → stdout `asr: queue empty (no parts need transcription)`、**exit 0**；**没有**新的 `acquisition_runs(kind='asr')` 行；没有新 attempt 行；wall time < 10 s（模型未加载） | `s7-rerun.txt`；`s7-norun.txt`（前后 run 计数对比） |
| **S8** | 读者出口 | `status` 该 part 计为已转写；`search-index` 后 `search <ASR 文本中的独有字符串>` **能命中该块**；`verify` **exit 0**；`coverage --strict` 的 exit 与 `defect_count`/`backlog_count` 记录在案 | `s8-status.txt` / `s8-search.txt` / `s8-verify.txt`（含 exit code）/ `s8-coverage.txt` |
| **S9** | 发布幂等 | 首次 `publish-transcripts --bvid <AUD_BV> --limit-parts 1` 产出 bundle（含 `.bundle-ready`）；**第二次** 输出含 `already_published` 且既有 bundle **未被替换** | `s9-first.txt` / `s9-second.txt`；`stat` 前后 mtime/大小 |
| **S10** | 热词装载态（as-shipped） | 基准树上 `DEFAULT_HOTWORDS == ()`；`MEASURED_HOTWORD_CANDIDATES` 存在；不设 `BILI_ASR_HOTWORDS` 时两遍热词路径 **inert** | `s10-hotwords.txt` |

### 4.1 S6 断言明细（收敛是本计划的核心）

命令：

```bash
$P/.venv/bin/bili-asr asr --bvid <AUD_BV>:p0 \
    --archive-root $ARCH --artifact-root $ART --no-keep-audio
```

**前置断言**（运行前）：该 part 无 `asr-local` 行；`v_missing_transcript` 该 part = 1。

**后置断言**（逐条必须成立，缺一即 `failed`）：

1. `transcripts` 恰好新增 **1** 行，`source_kind='asr-local'`，`version=1`，
   `language` 非空（来自 provenance），`content_sha256` 为 64 位小写十六进制；
2. `transcript_segments` 该 `transcript_id` 行数 **> 0**，`ordinal` 从 0 连续，
   每行 `end_ms > start_ms`；
3. `asr_models` 出现对应 `(model_name, revision)` 行（`transcripts.model_id` 外键要求，`database.py:1192-1201`）；
4. `acquisition_runs` 新增 1 行 `kind='asr'`、`selector_kind='bvid'`、`selector_target=<AUD_BV>`；
5. `acquisition_attempts` 新增 1 行，`outcome='stored'`，`transcript_id` 指向上面的行，
   且 `run_id` 与第 4 条一致（写回与尝试证据同事务）；
6. **收敛**：`v_missing_transcript` 该 part = **0**；`v_part_pipeline.pipeline_state = 'transcribed'`；
7. **归档**：artifact root 下四个族（`srt`/`txt`/`md`/`raw`）产出且 `.bundle-ready` 存在。

> 断言 1 是 `I-000067` 的真机证伪点；断言 6 是"写回是否真的收敛视图"的证明；
> 断言 5 是"写回不是孤儿行、带了 attempt 证据"的证明。

**功耗预算**（来自上次真机实测，可复用）：2598 s 音频 → 372 s；5112 s → 649 s；6395 s → 903 s。
即 **≈0.14 s 音频/秒**。本场景选 **最短** 的候选 part 以压预算，**上限 30 min wall**，超时按 `failed` 记录并保留已产出证据。

### 4.2 候选稿件与臂的选取（不臆造 BV 号）

页 5–6 实测 4 条稿件带 `ai-zh`：`BV1BdtazGEBE:p0`(6395 s)、`BV1vNTqzFEve:p0`(5112 s)、
`BV1Y7M4zNEfF:p0`(2598 s)、`BV1zz5zzFENq:p0`(2087 s)。**哪些 part 真的没有字幕，未测。**

选取规则（先探测、后定臂，`probe-subs` 是只读的、不记录尝试）：

1. `probe-subs --bvid <候选> --limit-parts 1 --archive-root $ARCH` 逐个探测候选；
2. `<CAP_BV>` := 探到可用字幕轨的第一条（优先上面 4 条中已实测带 `ai-zh` 者）；
3. `<AUD_BV>` := 探到 **无字幕** 的第一条，**且必须与 `<CAP_BV>` 不同 part**；
4. 若候选里找不到无字幕 part ⇒ **S4–S7 记 `blocked`**，理由写"授权候选集内无 caption-less part"，
   并把探测矩阵作为证据返回。**不得**改用 manifest 路径（`--queue-source manifest`）绕过。

> 为什么不得用 manifest 绕过：`_todo_for_bvid`（`cli/_shared.py:108-133`）不做状态/字幕过滤，
> 在 manifest 路径下**已持有 transcript 的 part 仍可被选中**，会污染 S3/S4 的准入断言。
> 本次运行全程只用默认 store 路径。

## 5. 明确排除（不授权即不做）

- `run --scope pending` 协调器多阶段全链（GPU 开销成倍）、`campaign`、`schedule`、`export`、`recover`、`evaluate-concurrency`
- `--queue-source manifest` 全部臂（回滚路径，故意不测）
- **pytest 全量套件**：E2E 授权 ≠ 测试套件授权，且算力机不做开发
- 任何 `pip`/`uv` 安装、`uv.lock` 重生成、依赖升级（`I-000136`：任何锁重生成会静默拉入 PyPI CUDA torch）
- 任何写根之外的写入；任何删除操作

## 6. 预算与停机条件

**预估 wall**：S0 ≈5 min，S1 ≈2，S2 ≈3–8（含页 6 重试），S3 ≈2，S4 ≈3，S5 ≈1–5，
S6 ≈5–15（GPU），S7 ≈1，S8 ≈2，S9 ≈1，S10 ≈1 ⇒ **合计 ≈30–50 min**（不含首次模型加载）。

**立即停机（记 `blocked`/`failed`，不重试、不绕路）**：

- 凭证失效（登录要求 / 鉴权错误）→ `blocked`；**绝不换账号重试**
- 设了 `HSA_ENABLE_DXG_DETECTION=1` 仍无 GPU → `blocked`
- 任何联网抓模型的迹象（`HF_HUB_OFFLINE=1` 下仍访问网络）→ `failed`，逐字记录报错
- Bilibili 风控/限流响应 → 该场景停放，记录原始响应，**不得连击**
- 需要写 `$RUN` 之外、或需要删除/覆盖任何既有产物 → 停下等授权

## 7. 可选扩展：S11（默认 `not-run`，操作者显式启用才做）

`I-000102` 要求的"真机重跑四件产物 + 人工抽检 ≥5 个校对块"至今未交付。
要闭合它需要 **同一 part 同时拥有字幕与 ASR 两份文本**——而 store 路径按设计
**永不**把有字幕的 part 送进音频队列。因此 S11 必须显式指定绕行方式并单独授权：

- 做法：对 `<CAP_BV>:p0`（S3 已产出 `subtitle-ai`）用 `download-audio` + `asr` 强制取音频与转写，
  再跑 `proofread --bvid <CAP_BV>`；
- 需要操作者决策：是否允许对已有字幕的 part 强制走音频（这是**故意偏离**默认队列语义的测试装置）；
- 若启用，追加 `S11-proofread.txt` + `S11-inspection.md`（≥5 块人工判定记录）。
- **不启用时**：`I-000102` 不因本次运行闭合，报告中如实写 `not-run`。

## 8. 交付物

1. `{WORKFLOW_DIR}/e2e-23191782-store-writeback-chain/reports/e2e.md` — 按
   `mstar-e2e/references/report-template.md`：Scope / Results 表（每场景一行，`passed|failed|not-run|blocked`）/
   Evidence / Findings and handoff / Not verified / Completion recommendation。
2. `$RUN/evidence/` — 全部逐字命令与输出（**不含凭证值**）。
3. 失败项的 bounded follow-up 建议；不得自动重开或阻塞其它 workflow。

**报告结论与产品结论分开写**：全部场景拿到确定结果 ⇒ 验证运行 `completed`；
其中若有 `failed` ⇒ 那是**产品**失败，不改变"这次验证已跑完"。

## 9. 执行方式（批准后）

- PM 注册独立 workflow：`type: plan`、`delivery_kind: verification/report-only`、
  `completion_policy` = 「无分支无 PR；交付物是本 workflow 自己的报告」。
- PM 派发 **`@ops-engineer`**：`Execute as: ops-engineer`、`Task category: ops`、
  `Delegation: forbidden`、`Skill presets: none`；只执行本表已命名场景。
- 只读座位（如需并行核证）用 read-only 委派；**不进入** QA、不插入 iteration phase、不做 QC tri-review。
- ops 只报结果，**Done 状态由 PM 独占**；执行者不得自标 Done。

## 10. 开放问题（需操作者回答）

| # | 问题 | 影响 |
|---|---|---|
| Q1 | 授权 A4（把算力机 `main` 换到 `1e756df`）？ | 拒绝 ⇒ S4–S7 blocked；未提交热词补丁将只存为证据文件 |
| Q2 | 是否启用 S11 / `I-000102`？ | 决定本次是否附加人工抽检腿 |
| Q3 | 写根确认只用 `/root/e2e-asr/store-writeback-chain`（不写 `/mnt/e`）？ | 决定证据与产物的留存位置 |
| Q4 | 是否顺手把 `HSA_ENABLE_DXG_DETECTION=1` 持久化进算力机 profile（`I-000118`）？ | 该动作属环境变更，不在本计划写入范围内，需单独授权 |
| Q5 | 候选集沿用页 5–6（近 57 个 part），还是换页/换量级？ | 决定 S2 的抓取范围与噪声面 |
