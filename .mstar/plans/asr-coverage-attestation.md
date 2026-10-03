---
plan_id: asr-coverage-attestation
project: _default
status: draft
created_at: 2026-10-03
execution_mode: inline
plan_parallelism: serial
---
# Plan asr-coverage-attestation — Make an ASR transcript's coverage attestable so a short decode cannot read as success

**Main worktree branch**: `main`（control root 驻留分支；本 plan 不切换。**重新观察于 2026-10-03 21:57**：原记录为 `dev` —— 并行会话移动了共享 control root（reflog `dev → e2e → main → thinking → main`），root 已稳定驻留 `main` 逾 4 小时，故按契约 §2.3 step 2 重新观察并记录，非静默编辑）

## Status
- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Confidence**: HIGH（缺陷已真机复现并逐步归因；修法已由 architect 轮收敛，见 `{ITERATION_DIR}/iter-2026-10-asr-success-attestable/specs/architect-decisions.md` D8/D9）
- **Fingerprint**: e2e-2026-10-03/asr-coverage-short
- **Depends on**: none
- **Category**: bug
- **Evidence**: `bilibili-asr-archive/src/bili_asr/asr.py:1195-1221`（chunk 循环：`_split_audio` 后逐 chunk 解码，**无任何**覆盖率断言）；`_split_audio` 的 tiling 承诺在 `:665-672`；`budget` 在 `:1097-1100`
- **Planned at**: commit `0773650`, 2026-10-03
- **Captured issue**: `I-000188`

## Problem

ASR 可以在**静默**中产出一条只覆盖部分语音的转写，而归档把它记为成功。

本机实测（算力机 `192.168.3.21`，RX 7800 XT，产品 checkout `1e756df`）：

| 测量 | 值 |
|---|---|
| part | `BV1YFEUzpEsT:p0`，`video_parts.duration_ms = 74000` |
| 归档转写 | **13 段，跨度 0.0 – 59.0 s** |
| 解码音频长度 | **73.561 s**（3,244,032 samples @ 44.1 kHz） |
| **未被触及的语音** | **14.6 s ≈ 20%** |
| 该 run 的记录 | `outcome=stored`、bundle `archived`、四族齐全、**无 `error_code`、无告警** |

**这是"成功外观下的错误归档"**：它与 `I-000166`（run id 撞键静默跳过写回）、`I-000187`（空清单当耗尽）是**同一失效类**——账本说成功，事实不是。

### 归因（逐步实测，不是推理）

1. **不是下载** —— 新下载 303,078 B，`ffprobe` 与产品自身 `_read_audio` 都测 **73.561 s**。
2. **不是 token 预算** —— `_MAX_NEW_TOKENS_PER_AUDIO_SECOND` 8→32（预算 588→2,352 tokens）输出**逐字节相同**（13 段 / 307 字符 / 0.0–59.0 s）。
3. **不是静音** —— 跳过区均值 **−27.0 dB**、峰值 **−4.0 dB**；对照已覆盖区 **−26.0 / −4.0 dB**；停顿仅 0.4–0.6 s。
4. **该区在自身电平下模型输出 0 字符，`+20 dB` 才出字**；而**真静音对照（67–73.5 s）任何增益都输出 0**、已覆盖区对照正常出字。
5. **两个增益版本互不一致**，且都不匹配字幕 → 该区是**难音频**，不是调增益能修的。

所以缺陷**不是**"模型这里不行"，而是**没有任何地方把产出跨度与解码时长作比较**。唯一发现它的机制是 `proofread` 的 **Guard A**——它要求两条路线、是 opt-in、且在发布**之后**。**检测手段不能是校对链。**

### 为什么值得 P1

`asr.py:246` 的既有注释已经承认**相邻**缺陷（截断文件静默解码变短、无比较即检测不到），但把范围限定在**下载截断**；本条是**模型覆盖不足**，同一句"没有任何地方比较"同样成立，且影响面更广（任何语音难度高的片段）。

## Current state (excerpt — 动手前须对 live code 复核)

`bilibili-asr-archive/src/bili_asr/asr.py`，chunk 循环（实测行号，`1e756df`）：

```python
chunks = _split_audio(samples, SAMPLE_RATE, self.config.chunk_seconds)
if not chunks:
    self._last_characters = None
    self._last_transcribed_segments = None
    return []

handle, scratch = tempfile.mkstemp(prefix="bili-asr-chunk-", suffix=".wav")
os.close(handle)
minimum = int(_CHUNK_MIN_SECONDS * SAMPLE_RATE)
pieces: list[dict[str, Any]] = []
for chunk, offset in chunks:
    audio = np.asarray(chunk, dtype=np.float32)
    if audio.shape[0] < minimum:
        audio = np.pad(audio, (0, minimum - audio.shape[0]))
    sf.write(scratch, audio, SAMPLE_RATE)
    text, language = self._transcribe_chunk(models, scratch, bust_cache=bust_cache)
    if not text:
        continue                      # <-- 空转写的 chunk 被静默丢弃
    units = [ ... + offset ... ]
    pieces.extend(_thread_text(text, units))
cues = _aligned_cues(pieces)
```

三个可断言的事实：
- `_split_audio` 承诺 chunk **精确平铺输入**（`:665-672`："no overlap, no gap, nothing dropped and nothing added"），所以**已知**全长样本数与每个 chunk 的 `(offset, length)`。
- `if not text: continue`（`:1211`）丢弃空转写 chunk，**不留任何记录**。
- 产出跨度可由 `pieces`（或最终 `cues`）直接算出，**从未**与 `len(samples)/SAMPLE_RATE` 比较。

## Invariant restored (target state, not the line moved)

**一条 ASR 记录在声称为成功时，必须携带可核验的覆盖范围证据；覆盖显著不足时不得表现为无保留的成功。**

证据的**具体形态**已由 D9 收敛：落在**该 part 的 manifest 行**（`decoded_s` / `produced_s` / `coverage` / `coverage_min`，与既有 `outcome` / `error_code` 并列），**不是**侧车、不新增列。必须满足：

- 可由**存档本身**读出（不能只存在于日志或 stderr）；
- 能被自动化 witness 断言（AC2）；
- 不改变既有合法记录的语义（阈值须让现有整套测试保持绿）。

## Contracts to preserve (name these in the task report)

- `_split_audio` 的 **tiling 承诺**（`:665-672`）——它是本 plan 断言的基石；不得为了覆盖率而破坏它，也不得让 splitter 承担 padding（注释明确说那是 caller 的事）。
- `_read_audio` / `_decode_with_ffmpeg` 的 decode 契约，以及 `asr.py:246` 已记录的"截断不检测"限制——本 plan 修的是**模型覆盖**；若顺手能覆盖下载截断，须**显式说明**并单独断言，不得混为一谈。
- `ASRRunner.release()` 与 `model_constructions` 计数语义（单调、不因 release 重置）。
- `_transcribe_chunk` 的 `bust_cache` 两遍热词契约。
- 既有 `error_code` / outcome 词汇的**消费方**：改词汇前须列出全部读取方（见 Task 1 第 4 步）。

## Conventions to follow

- 日志/异常类名出现在 run ledger 时沿用既有风格（`AudioDecodeError.__doc__` 记录了"coordinator 记录异常类型名或标量 `code`"的约定）。
- 注释风格：本仓的既有注释**记录测量**（"measured:"、"the same was true of…"）而非复述代码；新增注释应同风格。
- `default_config()` 是环境旋钮的唯一入口；新增可调项走同一处，不散落 `os.environ` 读取。

## Tasks

### Task 1 — 定义并实现覆盖率证据（Effort: M）

**Files**
- Modify: `bilibili-asr-archive/src/bili_asr/asr.py`
- Modify: 覆盖率证据的落点（D9 已定为该 part 的 manifest 行，写入方在 `asr.py`；**若实现中确需 schema 改动，须先在 plan 内显式升级确认**）

**Change**
1. 在 `ASRRunner.transcribe` 内计算：`decoded_seconds = len(samples)/SAMPLE_RATE` 与 `produced_span = max(cue.end) - min(cue.start)`（或 `pieces` 等价量），以及**每个 chunk 的产出情况**（尤其 `if not text: continue` 的那一支——它是静默点）。
2. 按 D8/D9 收敛的形态产出证据（标记而非阻断，阈值 `COVERAGE_MIN = 0.97` 及其实测依据见 D9；**不得**自行拍一个魔数）。
3. 保持 tiling 承诺；若需要额外状态，优先放在 runner 的 `_last_*` 一族（既有先例）而非全局。
4. **列出**证据字段/词汇的全部消费方（`grep` run ledger、manifest、bundle 写入方与读取方），在 task report 中具名。

**Interfaces**: `ASRRunner.transcribe(self, audio_path, *, bust_cache=False) -> list[dict]` 的**返回形状**默认不变（调用方依赖）；证据走旁路（D8 已定为**标记而非阻断**，故返回语义不变）；若实现中确需改变返回语义，须在此处显式记录影响面。

**In scope**: `bilibili-asr-archive/src/bili_asr/asr.py`, `bilibili-asr-archive/tests/test_asr_qwen.py`, `bilibili-asr-archive/tests/_asr_fakes.py`（如 fake 需扩展）

**Out of scope**: 提升识别率、调 `_MAX_NEW_TOKENS_PER_AUDIO_SECOND`（已实测排除）、`proofread` 链、`I-000166` 的 run id

### Task 2 — 钉住缺陷类（Effort: S，同一轮）

加一个**不需要真机/GPU**的 witness：

1. 构造"输入全长、模型只覆盖前半"的场景——用 `_asr_fakes.py` 的 fake 或 monkeypatch 让某 chunk 返回空文本（即命中 `if not text: continue` 那一支），或直接让 fake decode 在时间上截断。
2. 断言：**新证据出现且如实反映缺口**（具体断言见 D9 的 witness 两条方向：`p/d = 0.802` → `stored-short`；`p/d = 0.985` → `stored`）。
3. 断言**反面**：一个正常全覆盖的转写**不**产生缺口标记（防止"永远报警"的假修复）。
4. 记录 red/green 对：修复前该断言必须失败（以实测的 73.561 / 0–59.0 比例为基准构造 fixture）。

## STOP conditions

- 若 `asr.py` 的 chunk 循环与上方 excerpt 不再一致（行号或结构变化），STOP 并报告。
- 若修法需要 **schema 改动或迁移**，STOP —— 该决定超出本 plan 的既有 non-goal，须先升级。
- 若覆盖率断言的阈值无法同时满足"抓住 73.561/59.0"与"既有测试全绿"，STOP 并把两个候选阈值与各自代价报给 architect 裁决。

## Drift check

- 复核 `asr.py` 的 `_split_audio` / `_transcribe_chunk` / `transcribe` 三者行号与结构；
- 复核 `_MAX_NEW_TOKENS_PER_AUDIO_SECOND` 是否仍为 8（若已变，重跑预算实验再引用其结论）；
- 复核 `v_missing_transcript` 与 run ledger 的读取方未变。

## Done criteria

- [ ] Task 1、Task 2 完成，且 Task 2 的 witness 在修复前**确实红**（保留 red/green 证据）
- [ ] 既有测试套件全绿（含 `test_asr_qwen.py`、`test_coordinator.py`、`test_cli_asr.py`）
- [ ] 覆盖率证据可从**存档**读出并可被自动化断言
- [ ] 证据字段/词汇的全部消费方已具名
- [ ] task report 记录：修法、阈值依据、red/green、未做的部分与理由

## Verification notes

- 契约层 witness 必须**离线可跑**（CI 无 GPU、无 B站凭据）。
- 真机验证按 **`mstar-e2e`** 单独进行（本会话已证明该通道可用：算力机 `192.168.3.21`，`HSA_ENABLE_DXG_DETECTION=1`，会话 env 在 `/root/.config/bili-asr/session.env`）。
- 实测基准数据：`/root/e2e-asr/asr-two-video-batch/evidence/proofread/{b-align,v-tail-audio,x-gain,u-budget,t-tail}.txt`

## Engine lifecycle ownership

plan 状态、snapshot 更新、QC/QA 与 Done 由 PM（coordinator）拥有；实现者不得自标 Done。
