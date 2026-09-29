# E2E Verification Report — 未明子 season 7686105 through the ASR chain

## Scope

- **Workflow / plan:** `e2e-23191782-season-7686105` (verification-only; `type: plan`)
- **User authorization and permitted side effects:** explicit operator request — first
  "跑未明子的50个视频", then narrowed by URL to the season collection
  (`https://space.bilibili.com/23191782/lists/7686105?type=season`, "把这个系列视频全跑了").
  Permitted: download audio for that season, transcribe on the target GPU, write the archive
  root on the target host. Not permitted and not done: product-code change for the run itself,
  production deploy, media redistribution.
- **Target build / ref:** target repo fast-forwarded `bc425f6` → **`9c385cc`** (today's four
  residual fixes plus the `check-asr-env` subcommand). Interpreter `/root/gpu-venv`
  (torch 2.9.1+rocm7.2.0 — the pair `check-asr-env` verifies); the repo's own `.venv` is broken
  (torch 2.14 build aborts in the device probe, and `bili_asr` is not installed there).
- **Actual environment / device / session:** WSL2 `DESKTOP-HHFROLO` (6.18.33.2-microsoft-standard-WSL2),
  device **AMD Radeon RX 7800 XT, gfx1101, 15.8 GB VRAM, HIP 7.2.26015**, `HSA_ENABLE_DXG_DETECTION=1`,
  archive root `/root/e2e-asr/e2e50`, run log `/root/e2e-asr/logs/full-20260917-174448.log`.
- **Assigned scenario IDs:** A1–A6 (below).

## Results

| Scenario | Expected | Actual | Outcome | Evidence |
|---|---|---|---|---|
| **A1** host self-check | `bili-asr check-asr-env` exits `0` on the target GPU | five stages `ok`; `device ok name=AMD Radeon RX 7800 XT arch=gfx1101 vram_gb=15.8`; `asr-env: verified`; exit 0 | **passed** | see Evidence §A1 |
| **A2** one item end-to-end | download → GPU ASR → 4 artifacts + marker → audio reclaimed | `BV1RFoxBqEzo:p0` (43.7 min): `archived (asr)`; raw/txt/md/srt + `.bundle-ready` (5 files); `audio/` empty afterwards | **passed** | Evidence §A2 |
| **A3** whole season archived | all parts of season 7686105 archived, 4 artifacts each | **in progress** — 39 parts seeded (36 videos / 76.6 h); 2 of 39 archived at the time of writing; run PID 10649 | **not-run (in progress)** | Evidence §A3 |
| **A4** provenance identity + VAD keys | frontmatter carries the declared model id and the 3 capture keys | `asr_model_name: "FunAudioLLM/Fun-ASR-Nano-2512"` (not `[redacted]`); `asr_vad_segments: 157`, `asr_vad_captured_s: 2324.12`, `asr_vad_captured_ratio: 0.887` | **passed** | Evidence §A4 |
| **A5** quality signals reachable | `coverage --quality` reports the content codes; the doubt's location is readable | deferred to A3 completion (report is per archived row); the low-confidence locations are present in the frontmatter (`asr_low_confidence_at`, 13 entries) | **not-run** | pending |
| **A6** audio reclaimed per row | `audio/` does not accumulate | `audio/` holds only the in-flight item; the archived row's file is gone | **passed** (per A2) | Evidence §A2 |

## Evidence

### §A1 — the GPU self-check through the shipped subcommand

    $ cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive
    $ HSA_ENABLE_DXG_DETECTION=1 VENV=/root/gpu-venv PYTHONPATH=$PWD/src \
        /root/gpu-venv/bin/python -m bili_asr check-asr-env
    check: dxg-detection ok
    check: rocm-loader-path ok
    check: torch-present ok
    check: hsa-runtime ok
    check: device ok name=AMD Radeon RX 7800 XT arch=gfx1101 vram_gb=15.8 hip=7.2.26015-fc0010cf6a
    asr-env: verified
    EXIT=0

This is the invocation the README and `specs/01-gpu-enablement.md` D1.2 publish. It **did not
exist as a subcommand** before this run: every documented call answered
`invalid choice: 'check-asr-env'` (the P1+P2 pass replaced the docs without implementing the
command). The gap was closed as part of unblocking this E2E — see Findings F1.

### §A2 — one item, full pipeline

    $ /root/e2e-asr/tools/run_e2e.sh pilot 1
    pilot: selected 1 rows (--n 1; includes pagelist siblings)
    pilot: model constructions=1 for 1 asr item(s)
    VB1RFoxBqEzo:p0: archived (asr)
    pilot terminal: VB1RFoxBqEzo:p0: archived (asr)

Artifacts (5 files, 4 types + marker):

    transcripts/raw/BV1RFoxBqEzo.p0.json
    transcripts/md/2026-04-22_BV1RFoxBqEzo.p0_【哲学进阶】现代哲学《第一哲学沉思录》第十三讲 第六个沉思（1）.md
    transcripts/srt/BV1RFoxBqEzo.p0.srt
    transcripts/srt/BV1RFoxBqEzo.p0.srt.bundle-ready
    transcripts/txt/BV1RFoxBqEzo.p0.txt

Text sample (opening), matching the title's subject (第六个沉思):

    讲这个第六个层次啊，论物质性东西的存在，论人的灵魂和肉体之间的实在区别。
    那么上一讲他已经证明了呃物质性东西的本质了，现在要开始去论证这个物质性东西的存在了。

Measured decode rate on the batched GPU path: `rtf_avg` 0.152–0.176, i.e. **~6× realtime**.

### §A3 — the season run (in progress)

    $ /root/e2e-asr/tools/run_e2e.sh seed
    seed: season 7686105 '合集·哲学进阶•现代哲学' total=36
    seed: rows=39 skipped=0
    $ /root/e2e-asr/tools/run_e2e.sh menu
    rows=39 work_ids=39
    status: {'needs_audio': 39}
    audio=76.6 h
    >45min: 38

    $ /root/e2e-asr/tools/run_e2e.sh run        # detached, PID 10649
    run: scope=pending selected 38 row(s)

Measured at 17:51: item `BV13SdhB1E7i:p0` downloaded (63 MB), ASR forward pass at
`rtf_avg: 0.176` (174 segments, then 154). Manifest at that moment:
`{'needs_audio': 37, 'archived': 1, 'audio_ok': 1}`.

**Projected wall clock for the full season: ~12–15 h** (76.6 h of audio ÷ ~6× realtime,
plus download and per-item overhead). The run is detached under `nohup` and survives the
SSH session.

### §A4 — provenance and the capture keys

    asr_vad_segments: 157
    asr_vad_captured_s: 2324.12
    asr_vad_captured_ratio: 0.887
    asr_mean_confidence: 0.782
    asr_low_confidence_cues: 13
    asr_low_confidence_at: [142.52, 381.16, 862.17, 870.82, 938.32, 945.88, 1113.37, 1486.5, 1542.77, 1689.14, 1774.28, 1776.6, 2002.89]
    asr_model_name: "FunAudioLLM/Fun-ASR-Nano-2512"
    asr_model_revision: ""
    asr_device: "cuda"
    asr_language: "中文"
    asr_hotwords: "未明子,主义主义,...,理念性,ITEM,AITEM,International Employment Matters Tribunal,International,Employment,Tribunal"
    asr_local_source: "configured-local"

Three observations worth recording:

1. The **declared identity occupies the `model_name` slot** — the reason this run sets
   `BILI_ASR_MODEL_ID`. The deleted 2026-09-12 batch recorded `[redacted]` for the same
   checkpoint because that variable was unset; the declaration is what makes the archive
   name its producer.
2. The **capture trio is present** (the keys `quality-signal-merge` added), and the ratio
   0.887 is computed against the row's own `duration_s`.
3. `asr_low_confidence_at` carries **13 positions**, so the doubt is locatable from the
   artifact alone — the closure this run's A5 half exercises.

## Findings and handoff

### F1 — `bili-asr check-asr-env` did not exist (found and fixed while unblocking this run)

- **Impact:** every GPU self-check invocation published by the README and `specs/01-gpu-enablement.md`
  D1.2 failed with `invalid choice: 'check-asr-env'`. The check itself existed only as
  `scripts/check_asr_env.py`, which the docs no longer told anyone to run — the P1+P2 pass
  (`bc425f6`) replaced a documentation defect with a missing-command defect.
- **Repair:** implemented the subcommand (`src/bili_asr/cli.py`), which resolves the checkout's
  script and passes its exit status through; three tests added. Shipped in `9c385cc`, deployed
  to the target, and verified there (§A1).
- **Owner:** resolved in this run; no remaining action.

### F2 — repo `.env` carries a malformed credential line (data defect, not code)

- **Impact:** `bilibili-asr-archive/.env` line 1 is `BILI_SESSDATA=# 优先…本文件。` — the value is a
  Chinese **comment** — and the real cookie sits on line 2 with **no key**. Any naive export
  (`grep -oP 'BILI_SESSDATA=\K.*'`, a `.env` loader that takes the first match, `source`-based
  readers keyed on that line) puts non-ASCII text into the `Cookie` header, which `requests`
  rejects with `UnicodeEncodeError: 'latin-1' codec can't encode characters`. The pinned client
  surfaces that as `finger/spi bootstrap transport error`, i.e. it looks like a network problem
  and cost real debugging time.
- **Working source:** `~/.config/bili-asr/session.env` (222-char ASCII cookie), which the driver
  sources and validates (it refuses a non-ASCII value rather than sending it).
- **Proposed repair:** fix `.env` so the variable holds the cookie (or delete the file and rely on
  `session.env`). **Owner:** operator — it is a local credential file, not a tracked artifact.
  Not changed here because editing a credential file is outside the E2E's authorization.

### F3 — the ASR chain has no manifest bootstrap from the SQLite archive

- **Impact:** `fetch-meta` populates `archive.db` (60 videos / 63 parts collected here), but the
  ASR/pilot chain reads `manifest/manifest.jsonl`, and no shipped command bridges them — stated
  as intended in README §Workflow ("the subtitle step … feeds nothing below it … the legacy chain
  keeps its own harvest"). Running *any* corpus through ASR therefore needs a hand-built manifest.
- **This run's bridge:** `/root/e2e-asr/tools/seed_season.py` (deployed, 200 lines). It enumerates
  one named season through the pinned client's own risk-controlled path and writes `needs_audio`
  rows with **per-part** duration/cid from the pagelist — it never invents metadata. It is E2E
  scaffolding, not a product path.
- **Proposed follow-up (not authorized here):** either a `manifest` projection command from
  `archive.db`, or documenting the bridge as the supported bootstrap. **Owner:** PM, next
  planning round.

### F4 — multi-part durations needed the pagelist, not the season field

- **Impact:** the season's `duration` describes the whole archive; using it per part overstated
  `BV19hG56hEfV`'s three parts as 291 min each (real: 119.1 / 100.8 / 71.4) and `BV1N25V6JEu9`'s
  as 219.9 (real: 131.3 / 88.6). Caught before the full run by comparing against
  `x/player/pagelist`.
- **Repair:** the seeder reads per-part durations; the manifest was re-seeded from scratch
  (39 rows / 76.6 h, `>45min: 38`). **Owner:** done in this run.

### F5 — credential exposure through argv (avoided)

- **Impact:** an early driver revision passed `--sessdata "$BILI_SESSDATA"`, which makes the cookie
  visible in `ps` to every process on the host. Observed live in this run.
- **Repair:** the driver exports `BILI_SESSDATA` and passes no `--sessdata`; verified the client
  reads the environment (`cli._resolve_sessdata`). **Owner:** done in this run.

## Not verified

- **A3 completion** — the season run is ~2 of 39 items in at the time of writing; it needs 12–15 h.
  The final artifact count, the per-row provenance of the remaining 38, and the season-wide
  quality report are **unverified** until it finishes.
- **A5** — `coverage --quality` over the finished season (needs A3).
- **Subtitle-branch coverage** — the pilot reported `missing branch coverage: subtitle`; the
  season's videos expose no captions, so the smoke offers no subtitle-path evidence. Not a defect.
- **Bilibili risk control** — `fetch-meta` met `rate_limited` on some pages and recovered on
  retry (cursor-safe). Item downloads may hit the same; the run's `RiskBudgetExhausted` path is
  the resume mechanism and was not exercised end-to-end here.
- **293-minute-class items** — the longest seeded part is 219.9 min; nothing yet proves the
  single-pass decode holds for the ~5 h recordings elsewhere in the channel (they are not in
  this season).

## Completion recommendation

- **Assigned 6, passed 4 (A1, A2, A4, A6), in progress 1 (A3), not-run 1 (A5)** — A5 is gated on
  A3 by construction (it reads the finished archive).
- **Product result:** the deployed build (`9c385cc`) performs an end-to-end transcription on the
  target GPU **correctly**: declared provenance, capture keys, located doubt, reclaimed audio,
  and a text body that matches its title's subject.
- **Workflow lifecycle:** `running` → recommend `completed` once A3/A5 are read off the finished
  archive; the run itself needs no further intervention beyond monitoring.
- **Monitor:** `ssh chosenecho@192.168.3.21 'wsl -e bash -s'` then
  `tail -f /root/e2e-asr/logs/full-20260917-174448.log`; progress via
  `/root/e2e-asr/tools/run_e2e.sh menu`.

---

## Addendum — run stopped by operator (2026-09-17 21:42)

The operator stopped the season run ("停止跑"). Stopped at **3 h 39 min elapsed**: **14 of 39 parts
archived**, 24 still `needs_audio`, 1 `audio_ok` (`BV1NRDNBUE5e:p0` — its 58 MB audio is retained so a
resume reuses it instead of re-downloading). `SIGTERM`, process exited in 2 s; no `bili_asr` or
`run_e2e.sh` processes remain.

**Archived (14 parts, 1 437 min ≈ 24.0 h of audio):**

| work_id | min | | work_id | min |
|---|---|---|---|---|
| BV1RFoxBqEzo:p0 | 43.7 | | BV1N25V6JEu9:p0 / :p1 | 131.3 / 88.6 |
| BV19woxBTEyT:p0 | 71.8 | | BV1H69sB6EeF:p0 | 114.5 |
| BV19hG56hEfV:p0 / :p1 / :p2 | 119.1 / 100.8 / 71.4 | | BV1KL9tBsEao:p0 | 100.0 |
| BV19woxBKEnb:p0 | 122.8 | | BV18XXcBnEz6:p0 | 123.0 |
| BV19woxBKEhL:p0 | 145.5 | | BV13SdhB1E7i:p0 | 125.9 |
| BV189EN6jEEE:p0 | 152.5 | | (plus the A2 probe item) | |

**Integrity of what was archived — clean.** `bili-asr verify --trusted-local` checked all 39 rows and
reported **zero defects among the 14 archived rows**; the 25 `retryable_incomplete` rows are exactly the
unprocessed remainder (24 `needs_audio` + 1 `audio_ok`), which is the code's classification for
not-yet-finished work, not corruption. Artifact counts are exact: 14 md + 14 raw + 14 txt + 14 srt +
14 `.bundle-ready`.

**Resumable.** `run_e2e.sh run` picks up from the manifest; `verify` exit 1 here reflects the incomplete
remainder, not a broken archive.

### A3 / A5 disposition

| Scenario | Disposition |
|---|---|
| **A3** whole season archived | **partially verified / stopped** — 14 of 39 parts (36%). The 14 completed parts are fully verified (4 artifacts + marker each, zero defects) |
| **A5** season-wide quality report | **not-run** — needs a finished archive; the per-row signals it would summarise are present in every archived md (`asr_mean_confidence`, `asr_low_confidence_cues`, `asr_low_confidence_at`, the three `asr_vad_*` keys) |

### F6 — `verify` reports `structural_input_error` on any normally-updated manifest (new, low)

Found while checking archive integrity after the stop.

- **What:** the manifest is append-only by design — `ManifestStore.upsert` appends a row per state
  transition, so one part legitimately produces `needs_audio` → `audio_ok` → `archived` lines. The
  projection takes the latest row (correct) but also emits `manifest_duplicate_work_id`.
  `coverage_report.py` knows that diagnostic (L76, L325 — it classifies it as a *record*-kind fact),
  while `integrity.py`'s vocabulary does **not** list it, so the `else` branch maps it to
  `structural_input_error`. Measured here: 15 of 39 work_ids have multiple lines (up to 3), so
  `verify` emits `structural_input_error` for an archive whose inputs are entirely normal.
- **Impact:** misleading diagnostics only — no false defect *code*, no data consequence. But
  `structural_input_error` reads like input corruption and would send an operator hunting for a
  damaged sidecar that does not exist. It is also an inconsistency between two readers of the same
  sidecar.
- **Not fixed in this run:** operator instruction was to stop ("停止跑"); this scope is
  verification-only, so no product change is authorized inside it.
- **Proposed repair:** add `manifest_duplicate_work_id` to `integrity.py`'s recognised list and map it
  to a diagnostic that says what it is (or drop it there, since the append-only history is by design —
  the same call `coverage_report` already made). **Owner:** next plan touching
  `src/bili_asr/integrity.py`.
- **Registered** as `e2e-23191782-season-7686105 · R2` in
  `{PROJECT_DIR}/_default/residuals.json` (severity **high**, `decision: defer`), by operator decision
  on 2026-09-17. Severity raised from the first draft's "low": the decisive probe above shows
  `verify` returns `defects: 0` with `EXIT=1` on a single healthy archived row, so the command's
  success path is unreachable for real archives — a broken public contract on the integrity gate, not
  misleading wording.

---

## Transcript quality assessment (14 archived parts, 25.2 h audio, 2026-09-17)

Measured on the 14 archives the stopped run produced: **18 287 cues, 424 188 characters, 25.2 h of
audio** (all pulled to the workstation for analysis; the raw sidecars carry per-cue confidence).

### Structural integrity — clean

| Check | Result |
|---|---|
| Zero-length cues / non-monotonic / malformed | **0 / 0 / 0** |
| SRT structure (index, timestamp, text on all 14 files) | **14/14 valid, 18 287 blocks** |
| Cue-text repetition runs (hallucination loops) | max run = **2** (none) |
| Cue overlaps | 7 total, **max 30 ms** |
| Cues > 60 characters | 421 (2.3%), longest 83 |

The 7 sub-frame overlaps are the only blemish, and they are what trips the **zero-tolerance**
`overlap` defect code — which is why `coverage --quality` calls 5 of the 14 rows invalid
(`valid_work_items = 9`) for a 10–30 ms boundary touch. The overlong cues are the shaper absorbing
undersized cues into the previous one, aggravated by English passages (the 60-character ceiling
counts Latin letters).

### Confidence — calibrated for language switching, blind to homophones

Per-item mean confidence **0.739 – 0.808** (median 0.782); distribution across all cues:
`>0.8` 54.1% · `0.6–0.8` 36.2% · `0.4–0.6` 7.0% · `≤0.4` 2.7%.

Low-confidence cues are **not spread randomly**: their median Latin-character ratio is **42.9%**,
against **0.0%** for every other cue. The model's own score tracks exactly where it is decoding
English (these lectures read Hegel's *Logic* aloud in translation). The signal the iteration added is
therefore meaningful, and `coverage --quality --format csv` — the surface this run's Task 3 added —
prints all 501 doubtful positions across 14 rows on stderr, e.g.
`coverage: BV13SdhB1E7i:p0 low-confidence at 470.7s, 1416.22s, …`.

### Content — the Chinese is good, with one systematic term defect

Sampled read of the Descartes lecture (BV19woxBKEhL, 145.5 min) reproduces the 5th Meditation
faithfully: 山与谷, 带翅膀的马, 完满性, 存在性, 领会 all correct, punctuation natural, fillers
preserved. Hegel terms carried by the hotword list render **perfectly**: 定在 145 (0 wrong),
理念性 69 (0), 自为 34 (0), 环节 394 (0), 知性 56 (0), 绝对 212 (9).

**`扬弃` (sublation) is the exception, and it is systematic:**

| 术语 | 正确 | 误写 | 误写占比 | 在热词表 |
|---|---|---|---|---|
| **扬弃** | 10 | **89** (阳气 62 + 洋气 27) | **90%** | **否** |
| 变易 | 0 | 7 (变异) | 100% | 否 |
| 自在 | 40 | 13 (子在) | 25% | 否 |
| 感性 | 12 | 3 (感兴) | 20% | 否 |
| 实存 | 17 | 3 (时存) | 15% | 否 |
| 定在 / 自为 / 理念性 | 145 / 34 / 69 | 0 / 0 / 0 | 0% | **是** |

`扬弃` is *the* central operation of Hegel's Logic and it lands as its exact homophone `阳气`
(yang-qi, a common word, hence the model's prior) nine times out of ten — worst in
`BV1H69sB6EeF` (《逻辑学》第二讲): 4 correct vs 57 wrong. Terms that are in the hotword list and are
equally homophone-prone (`定在`, `自为`) show **zero** errors, so the mechanism demonstrably works
for this class of mistake; `扬弃` simply is not in the list.

**The confidence signal cannot find this class.** The mis-rendered cues have a median confidence of
**0.776** against 0.812 for the corpus, and only **1 of 78 (1%)** falls at or below the 0.4
threshold: the model is *confidently wrong*. So the two tools split the work:

| Doubt class | Right tool | Evidence |
|---|---|---|
| English passages / unclear audio | `asr_confidence` → `asr_low_confidence_at` → the new stderr line | low-confidence cues carry 42.9% Latin vs 0.0% elsewhere |
| Chinese homophone substitution | `DEFAULT_HOTWORDS` (not confidence) | 扬弃: 90% wrong at confidence 0.776; in-list peers: 0% wrong |

**Actioned (commit `757baa1`):** six terms added to `DEFAULT_HOTWORDS` — `扬弃`, `自在`, `变易`,
`此在`, `感性`, `实存` — each with the measured error counts in the code comment and the README.
Their *benefit* is unverified until the audio is re-transcribed, so it is registered rather than
claimed: `e2e-23191782-season-7686105 · R3` (low), with 《逻辑学》第二讲 as the sharpest A/B target.

This is also the first *evidence* for the hotword mechanism the corpus has produced. It does **not**
close residual N-4, which tracks the six **Latin** hotwords: this season never speaks
ITEM/AITEM/tribunal, so that row still waits for audio that does — but the in-list Chinese controls
(`定在` 145/0, `自为` 34/0, `理念性` 69/0) do show the list works for the homophone class when the
term is present.

---

## Full artifact audit (2026-09-17, archive root `/root/e2e-asr/e2e50`)

Every artifact the run produced, checked with the product's own contracts rather than re-derived
ones (`archive.archive_bundle_complete`, the writer's own `_confidence_summary` /
`_capture_summary`, `ManifestStore` / `VALID_STATUSES`, `IntegrityVerifier`). Read-only.

### Inventory

| Artifact | Count | Size |
|---|---|---|
| `transcripts/md` | 14 | 1 205 KiB |
| `transcripts/raw` | 14 | 3 006 KiB |
| `transcripts/srt` | 14 | 1 815 KiB |
| `transcripts/txt` | 14 | 1 187 KiB |
| `*.srt.bundle-ready` markers | 14 | 10.5 KiB |
| `manifest/manifest.jsonl` (+ lock) | 2 | 29.4 KiB |
| `coordinator/attempts.jsonl` (+ 2 locks) | 3 | 11.3 KiB |
| `run-ledger.jsonl` (+ lock) | 2 | 4 KiB |
| `archive.db` | 1 | 156 KiB |
| `audio/` (retained for resume) | 1 | 55.8 MiB |

Archive output proper is **7.3 MB** for 25.2 h of audio; the 56 MB is the one in-flight item's audio,
deliberately retained.

### Verdict per contract — all pass

| Check | Result |
|---|---|
| `archive_bundle_complete()` (sha256 publication contract) | **14/14 pass, 0 fail** |
| Marker sha256 recomputed independently of the product function | **0 mismatches** |
| Four-way consistency: `txt == segments_to_txt(raw)`, `md` body `== txt`, `srt == segments_to_srt(raw)`, srt blocks == raw segments | **14 × 4 all exact** |
| md measurement keys recomputed from `raw.json` with the writer's own functions (confidence trio + capture trio) | **all 14 exact** |
| md identity fields vs manifest row (bvid/title/duration_s/work_id/page_index/cid) | **all 14 match** |
| Orphans (on disk, undeclared) / missing (declared, absent) / marker count | **none / none / 14 = 14** |
| `manifest.jsonl` | 68 lines, 39 work_ids, **no invalid status**; `archived 14, needs_audio 24, audio_ok 1` |
| `coordinator/attempts.jsonl` | 40 lines, **0 corrupt**, all `outcome: ok`, no `error_code`; `download 14 / asr 13 / archive 13` over 14 work_ids |
| `archive.db` | `PRAGMA integrity_check: ok`; videos 60, video_parts 63, ingestion_* populated |
| File modes / owner | 70 transcript files all `644`, sidecars `644`, dirs `755`, `root:root` |
| Retained audio integrity | valid m4a, **7126.72 s vs manifest 7127 s**, 65.7 kbps (the preferred 30264→64K stream), so a resume reuses it |
| Timeline | 17:43 → 21:41 (3 h 58 m) |

### Three operational gaps the audit surfaced (none is a transcript defect)

**G1 — `pilot` leaves no attempt records, so `--scope failed` cannot see pilot-archived rows.**
Measured: `BV1RFoxBqEzo:p0`, the item the A2 probe archived through `pilot`, has **`stages=[]`** in
`attempts.jsonl`. `AttemptLedger` is instantiated only in `coordinator.py`; the `pilot` path is its own
in-process loop. That is *within* the documented contract (the knowledge doc scopes the ledger to
"**Run coordinator (`bili-asr run`)**: stage-attempt ledger …"), but it lands exactly on the failure the
same paragraph warns about — "otherwise `--scope failed` silently drops rows". Severity: low
(observability; the archive itself is correct).

**G2 — an externally killed `run` leaves no `run-ledger.jsonl` record.**
The ledger's only row is the pilot's (`exit_code: 1`, "missing branch coverage: subtitle" —
expected: the seeded rows were already past the subtitle decision). The 38-row `run` wrote nothing,
because `_cmd_run` appends its record on the normal exit path and **no SIGTERM/SIGINT handler exists
anywhere in `src/`** — the operator's stop killed it before the append. Consequence: the runs most
worth reviewing later (externally interrupted) are the ones with no run-level record. Note risk-control
interruptions exit normally and *are* recorded. Severity: low; the per-stage truth survives in
`attempts.jsonl`.

**G3 — `meta-cursor.json` is absent, so the pilot's run record carries no cursor snapshot.**
Expected, and a direct facet of the two-stack boundary: the SQLite metadata path never writes that
legacy sidecar. No new entry needed — it belongs in R1's description.

---

## Text-quality pass over all 14 transcripts (2026-09-17)

424 188 characters, 18 287 cues, 25.2 h — every artifact of the run, not a sample.

### Verdict: high quality, with two narrow, mechanistically-located defects

**Per-item metrics are uniform and speak-appropriate** (no outlier that would betray a broken row):

| work | min | cues | chars/min | cues/min | chars/cue | punct/100 | filler % |
|---|---|---|---|---|---|---|---|
| BV189EN6jEEE.p0 | 152.4 | 1922 | 274 | 12.6 | 21.7 | 9.2 | 4.2 |
| BV19hG56hEfV.p0 | 119.1 | 1474 | 301 | 12.4 | 24.3 | 8.8 | 5.4 |
| BV1H69sB6EeF.p0 | 114.5 | 1398 | 289 | 12.2 | 23.7 | 8.1 | 4.3 |
| BV1RFoxBqEzo.p0 | 43.7 | 538 | 270 | 12.3 | 21.9 | 9.6 | 4.5 |
| … (14 rows, full range) | | | 241–329 | 11.0–12.7 | 21–27 | 7.8–9.7 | 4.1–5.4 |

**Topicality: 13/14 confirm the transcript belongs to its lecture** — checked against content words
rather than title metadata (which a lecturer never speaks): the Descartes lectures carry
上帝 172/108/55, 存在性 35, 完满 105/17, 山 18 / 谷 11, 怀疑 48; the Hegel lectures carry 黑格尔 31/18/10,
定在 36/15, 扬弃, 无限 226/159/134/112, 理念 156. `BV1RFoxBqEzo` opens on exactly its title's subject
("论物质性东西的存在，论人的灵魂和肉体之间的实在区别"). The single `?` is `BV189EN6jEEE`
(什么是观念论): 观念论 23, 范畴 5, with 康德/先验 absent — the lecture is about 观念论 broadly, so the
absence is not evidence of a mismatch.

**Pathology scan — all zero:** consecutive identical punctuation, single-character cues, unpaired
quotes/brackets, `U+FFFD`, control characters, hallucination boilerplate (点赞/订阅/字幕组/…).

**The 11 same-character runs are natural speech, not artifacts** — 不不不不不不 (emphatic refusal),
哈哈哈哈哈哈哈 (laughter), 得得得得 (tutting), 哒哒哒哒 (a sound effect), 收收收, 最最最最熟悉, 我我我.
Correctly transcribed disfluency.

**Mixed-language cues read naturally** (1 632 of 18 287, 8.9 %): `还是啊，whatever啊，就是那个`,
`可以理直话嗯，intelligible。是吧。`, `那个DNA、RNA什么蛋白质什么性状就会不稳定嘛。`

### Defect 1 — Latin tokens glue inside a cue (26 cues, 0.14 %) → registered as R6

    asME IDEAIn contrast to determine…      bothAND SO…
    negationIT IS DETERMINATOR…             questionITSELF SORT OF PUZZLE…
    the question is anITEM ONE              THE ITEMthat's the question…

**Mechanism, located in the writer:** `_token_cues` assembles the cue with
`text = _clean_text(pending + "".join(parts))`, while the space-repair rule lives in `_join_text`,
which is called from exactly two places — `hand_back()` (returning a closing mark) and the
undersized-cue absorption path. Intra-cue concatenation is the third place the rule is needed and
does not have it. `_join_text`'s own docstring already names the phenomenon ("Nano emits an English
phrase as several tokens and does not always carry the leading space"). Chinese is unaffected, which
is why 13 of 14 items show none; the 26 are concentrated in the English-quote-heavy Logic lectures.

### Defect 2 — the Latin hotwords corrupt English quotes (9 of which 8 are low-confidence)

`ITEM`/`AITEM` appear **inside Hegel passages being read aloud**, where the original was almost
certainly another English word:

    THE ITEMthat's the question is anITEM ONE          conf 0.404
    This is expressed in the finite on the AITEM.这个ITEM是   conf 0.470
    EMERGE IN THE ABSTRACT SIGNIFICANCE OF ITEM NOTHING     conf 0.275
    S呃，AITEM determined B啊。                              conf 0.033
    就是WHAT IS POSITIVE ITEM                              conf 0.040
    In accessible AITEM distance outside                   conf 0.239
    AS A PREDEAL ITEM                                      conf 0.257
    IT REMAINSTHE OTHER ITEM REMAINS                       conf 0.375

**8 of the 9 sit below `LOW_CONFIDENCE`** (0.033–0.375). The spelled-out phrase is *not* implicated:
"International Employment Matters Tribunal" appears 3× and is genuine each time (he is explaining the
name), and the 5 Chinese-narration occurrences are mostly genuine too (he discusses his own project).
This updates **N-4** with both halves of the answer it asked for: the entries reach the transcript
(yes) and they measurably hurt (yes, in English-quote passages; the bare acronyms, not the phrase).

### The distinction that matters for the hotword strategy

| Error class | Reachable via `asr_low_confidence_at`? | Measurement |
|---|---|---|
| Chinese homophone substitution (扬弃 → 阳气/洋气) | **no** — confidently wrong | 1 of 78 cues ≤ 0.4; median 0.776 vs corpus 0.812 |
| Unclear audio / English passages | **yes** | low-confidence cues carry 42.9 % Latin vs 0.0 % elsewhere |
| Hotword over-application in English quotes | **yes** | 8 of 9 ≤ 0.4 |

So the two instruments divide cleanly: **confidence catches what the model doubts** (English quotes,
including hotword interference), and **the hotword list is the only lever for what it does not doubt**
(Chinese homophones). Neither instrument covers the other's class.

---

## A/B: do the bare ITEM/AITEM acronyms capture English shards? (2026-09-17)

Executed per `.mstar/plans/20260917-hotword-acronym-precision.md` (T3), after T1 removed the two
entries (`ef5e1e8`). **Two fresh archive roots on the target GPU host, one row each, same audio, same
model, same device** — the old arm re-adds the acronyms through `BILI_ASR_HOTWORDS=ITEM,AITEM`, so the
only difference between the arms is those two prompt terms:

    new: 33 条 | ITEM=False AITEM=False | 尾 3 条: ['International', 'Employment', 'Tribunal']
    old: 35 条 | ITEM=True  AITEM=True  | 尾 3 条: ['Tribunal', 'ITEM', 'AITEM']
    仅 old 独有: ['AITEM', 'ITEM']

Both readings come from each bundle's own `asr_hotwords` frontmatter, not from the invocation.

### Result — the removal is confirmed

| Measure | new (no acronyms) | old (pre-change list) |
|---|---|---|
| `ITEM` / `AITEM` occurrences | **0 / 0** | **6 / 4** |
| affected cues | 0 | 5 |
| low-confidence cues (`≤0.4`) | **33** | 39 |
| mean confidence | **0.751** | 0.747 |
| VAD segments / capture ratio | 218 / 0.910 | 215 / 0.912 |
| cues / txt length | 878 / 25 491 | 879 / 25 397 |

**Identical-character ratio between the two transcripts: 0.9606** — above the ≥95 % bar the plan fixed
in advance, so the removal does not disturb the Chinese text.

### The five known suspect cues, arm against arm

| t | new | old |
|---|---|---|
| 611 s | `啊，thenThat's the question is anI的问啊` (0.396) | `…is anITEM ONE啊` (0.392) |
| 1329 s | **`This is expressed in the finite on the other hand.`** (0.568) | `…on the AITEMond.这个AITEMISA` (0.415) |
| 3093 s | `就变成他的assess为他本质。` (0.713) | `就变成他的item思维的本质。` (0.691) |
| 4060 s | **`Idea Moments。`** (0.662) | `ITEM MOVEMENTS。` (0.647) |
| 4126 s | `They are not real movements.…` (0.797) | identical (0.797) |

Two of the five improve *substantively* rather than merely losing the acronym: 1329 s recovers the real
English phrase **"on the other hand"**, and 4060 s recovers **"Idea Moments"** (Hegel's *ideal
moments*). The other three remain hard passages — the acronym was **capturing** existing confusion, not
creating it — and no cue regresses.

### One honest qualification of the original claim

D4 of the plan said the season run's nine occurrences were 8-of-9 below `LOW_CONFIDENCE`. In this
narrower controlled run the ratio does not reproduce: of the 5 ITEM-bearing cues, **2 are ≤ 0.4**
(0.085, 0.392) and 4 of 5 sit below the part's own 0.747 mean. The **direction** holds — acronym-bearing
cues score low — but the specific 8-of-9 count came from a different, larger sample. Recorded because
the plan's decision rules were written before the run, and a number that does not reproduce should not
be quietly dropped.

### Disposition

Per the plan's pre-written rules this is the **"confirms removal"** branch (old arm has the occurrences,
new arm has none, all suspect cues resolve, transcripts ≥95 % identical), so **N-4 closes** — both
halves of its question answered — and the Chinese half of the hotword question is untouched by this run:
`R3` stays open, since `BV19hG56hEfV.p2` contains neither `扬弃` nor `阳气`.
