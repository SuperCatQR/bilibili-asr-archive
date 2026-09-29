# E2E Verification Report — 未明子 six-part local ASR vs the live AI subtitles

> **Workflow:** `e2e-23191782-asr-vs-subtitle-webdav` (`type: plan`, `delivery_kind: verification/report-only`)
> **Status:** scope locked by PM 2026-09-22; execution owned by `ops-engineer`
> **Executor:** `ops-engineer` (PM orchestrates; ops executes and records actual results)
> **This file is the plan AND the report.** PM writes `## Scope` … `## Acceptance criteria`;
> ops fills `## Results`, `## Evidence`, `## Findings and handoff`, `## Not verified`,
> `## Completion recommendation` with what actually happened.

## Scope

- **Workflow / plan:** `e2e-23191782-asr-vs-subtitle-webdav` — an independent E2E verification
  workflow (`mstar-e2e`). Scenarios A0–A8 below are the workflow's plan rows. It is **not** an
  iteration phase, a development plan, or a QA gate, and it changes no product code.

- **User authorization.** Direct operator request 2026-09-22: *“做ASR，把ASR和LIVE AI字幕对比一下”* —
  run local GPU ASR over the six items already in play this day and compare the ASR transcript
  against the live AI subtitle for the same audio. Permitted: bounded metadata enumeration for UID
  23191782, audio download for the six parts, GPU transcription on the target host, publication of
  the ASR bundles to a **new** artifact root, reads of the previously published AI-caption products
  as the comparison reference, reads of the live caption inventory through the gateway, writes to
  the two named roots and the log dir, reading SESSDATA from its existing location **by path only
  (never recorded)**. **Not permitted:** product-code change for the run, production/deploy change,
  destructive cleanup outside the named roots, media redistribution, the project's full local test
  suite, any write to the previous run's artifact root (it is a read-only input here).

- **Target build / ref.** `/root/workspace/bilibili-asr-archive` at `37b0acc` (= `origin/main`,
  fast-forwarded and entry-point-repaired by the PM earlier the same day). Product invoked through
  the editable install: `/root/gpu-venv/bin/bili-asr` (the previous E2E's recorded run entry point)
  or `<product>/.venv/bin/bili-asr`. **A0 records which one this run used.**

- **Environment / device / session.** Target WSL2 `DESKTOP-HHFROLO` (192.168.3.21), AMD Radeon
  RX 7800 XT `gfx1101` (15.8 GB), `/root/gpu-venv/bin/python` 3.12.3, torch `2.9.1+rocm7.2.0.lw`.
  **The GPU gate needs `HSA_ENABLE_DXG_DETECTION=1` exported** — the previous E2E measured that the
  bare `check-asr-env` exits 1 on this host because that variable is not persisted (residual
  `e2e-23191782-subtitle-publish-webdav · R1`). Every ASR command in this run must therefore run
  with the variable exported, and A0 must show both invocations.

- **Roots (all on the target host):**
  | Role | Path | Access |
  |---|---|---|
  | archive root for this run (state, local disk, **fresh**) | `/root/e2e-asr/asr-vs-subtitle` | read/write, created empty |
  | artifact root for this run (products + retained audio, WebDAV) | `/mnt/123pan/bili-asr-e2e/asr-vs-subtitle` | read/write, must exist (create it) |
  | **AI-caption reference** (previous run's published products) | `/mnt/123pan/bili-asr-e2e/subtitle-publish` | **read-only input** |
  | logs | `/root/e2e-asr/logs/asr-vs-subtitle-<UTC-stamp>/` | read/write |

- **The six items** (UID 23191782, single-part, 26 282 s ≈ 7.30 h of audio):
  `BV1BdtazGEBE`, `BV1Y7M4zNEfF`, `BV1vNTqzFEve`, `BV1zz5zzFENq`, `BV11p5qzAE6s`, `BV1iddQYQE7D`
  — all `:p0`.

### Locked premise: the audio branch IS available here, and why (code-derived, asserted live)

The previous run could not exercise the audio branch because its store already held the AI
transcripts: `derive-manifest`'s queue is the store's `v_pending_subtitles` relation — *every part
that holds no transcript and is not `gone`* — and `download-audio --bvid` resolves its selector
through the manifest's effective entries (`_todo_for_bvid`, `cli.py:624-648`), so a caption-bearing
part is legitimately absent from the queue and the command answers `unresolved; not assigned to a
page` (`cli.py:1541`).

This run therefore uses **a fresh root in which the captions are never harvested**. With only
`fetch-meta` in that store, every stored part holds no transcript, so all six enter the derived
queue and the audio → ASR → artifact-root chain runs on them **with no product change and no
override** (this is exactly “Route B” as recorded on residual
`e2e-23191782-longform-pair-webdav · R2`). **A1 asserts the admission before any audio work**; if
any of the six is not in the queue as `needs_audio`, the premise is wrong, the run stops, and the
affected scenarios are `blocked` — never worked around.

The comparison reference is the AI caption the previous run harvested from the live source and
published to `/mnt/123pan/bili-asr-e2e/subtitle-publish` on the same day. A5 adds a **freshness
control** so the label “live” is earned, not assumed.

### Assigned scenarios

| ID | Scenario | Expected |
|---|---|---|
| **A0** | Build identity + the ASR host gate | HEAD `37b0acc…`, `git status --porcelain` = the pre-existing `?? .env.bak-20260917-181947` only; `bili-asr --version` = `0.1.0` from both entry points and the run records which one it used and the resolved `bili_asr.__file__`; `bili-asr check-asr-env` **bare** → record its exit and failing checks; the same command with `HSA_ENABLE_DXG_DETECTION=1` → **exit 0** with the device line naming `AMD Radeon RX 7800 XT` / `gfx1101`; record the torch version and the interpreter path |
| **A1** | Fresh root, bounded enumeration, and **queue admission** | `fetch-meta --mid 23191782 --start-page 4 --limit-pages 3 --archive-root <archive root>` exits 0 (pages 5–6 hold the six, page 4 the walk-up; pages 1–3 were rate-limited at an earlier scope lock — record what they do now if retried); then `derive-manifest --archive-root <archive root>` exits 0 and **all six `bvid:p0` are present in the effective manifest as `needs_audio`** with positive `duration_s`; record the `queue=`/`derived=` counters and the store's `transcripts` count (must be 0 — nothing harvested here). Any of the six missing → **stop and report `blocked`** |
| **A2** | Audio acquisition | `download-audio --missing-subs --bvid <bvid>:p0 --archive-root <archive root> --artifact-root <artifact root>` per item, each exit 0; per row the manifest status reaches `audio_ok`, the audio object exists **under the artifact root** with a byte size, and the row records its path; record per-item download wall time and the total audio bytes |
| **A3** | GPU transcription | `asr --pending --bvid <bvid>:p0 --archive-root … --artifact-root …` per item, each exit 0; per row a stored transcript exists and the run records its `source_kind` (expected an ASR value, **record the actual**), language, model/version identity, segment count > 0 and `content_sha256`; record per-item and total GPU wall time, and the run's own `rtf`/timing figure if the command or the stage ledger reports one |
| **A4** | ASR bundles published to this run's artifact root | `publish-transcripts --bvid <bvid>:p0 --archive-root … --artifact-root <artifact root>` per item, each exit 0; the four families (`srt`, `txt`, `md`, `raw`) **plus** the `.bundle-ready` marker exist under this run's artifact root with byte sizes and a recorded `sha256` per file; and the **previous run's AI products under `/mnt/123pan/bili-asr-e2e/subtitle-publish` are byte-unchanged** (compare against a `sha256` set taken before A2 — that root is a read-only input and the run must prove it) |
| **A5** | Reference integrity + **freshness control** | For each item, locate the AI-caption reference document under the read-only root (the published `transcripts/txt/<bvid>.p0.txt`, with `raw/<bvid>.p0.json` as the structured side) and record its `sha256` and character count. Then re-fetch **one** item's live caption inventory + document read-only through the gateway and compare against the stored reference: same track set, same normalized text. Report the outcome per the measurement (a change is a finding, not a failure of the run) |
| **A6** | The product's own comparison | Per item, one invocation (the flag needs exactly one selected row): `coverage --archive-root <archive root> --artifact-root <artifact root> --scope <bvid>:p0 --trusted-local --quality --reference <AI txt path> --format json` → record `reference.agreement`, `reference.floor`, `reference.compared_chars` (`(asr, reference)`), and whether `reference_disagreement` appears in the row's `content_reasons`. Six invocations, one row each — do not aggregate them into one call |
| **A7** | **Independent** comparison (the verdict must not rest on one reader) | A bounded read-only analysis over the two published `txt` (and `raw` for structure) documents per item, producing per item: (i) character counts on both sides after an explicitly stated normalization; (ii) a **character error rate** by edit distance (state the direction: ASR vs AI caption as the reference); (iii) cue/segment counts and mean cue duration on both sides; (iv) how many of the project's **default hotwords** appear in each side and which appear in exactly one — name the ones that differ; (v) a short aligned excerpt (the opening ~3 cues plus 3 sampled windows from the middle and end) for human spot-check. The script is evidence tooling written under the log dir, **not product code**, and its normalization must be printed with the results |
| **A8** | Readers agree, and the two roots stay separable | `verify --archive-root … --artifact-root … --scope <bvid>:p0 --trusted-local` per item → **zero defects on the six ASR rows**; `coverage --quality --scope <bvid>:p0` per item prints the row; the ASR products exist **only** under this run's artifact root and the AI products **only** under the read-only root (list both inventories); `search` returns text from at least one ASR row; `export --format json --status archived` lists the six and their manifest rows carry the ASR `source` value recorded in A3 — i.e. the ASR rows are distinguishable from the AI rows |

Outcome vocabulary is exactly `passed` / `failed` / `not-run` / `blocked`; a scenario without
determinate evidence is `not-run` or `blocked`, never a claimed pass.

### Acceptance criteria

1. All nine scenarios carry exactly one determinate outcome, each backed by commands with their
   exit codes and observed output.
2. The comparison is delivered per item **and** as a six-row table: the product's `reference.agreement`
   next to the independent CER, both with their definitions and normalization printed.
3. Every product/bundle claim is backed by a path listing with byte sizes and a `sha256` recomputed
   from the on-disk bytes; the read-only reference root is proven byte-unchanged.
4. The GPU gate evidence (A0) shows the variable-set invocation that produced exit 0, since the bare
   one is a known host gap (residual `e2e-23191782-subtitle-publish-webdav · R1`) — the run must not
   present the bare failure as this run's blocker, nor hide it.
5. `## Not verified` names what the run did **not** establish, including any item that failed or was
   skipped, the ASR model's own limits, and the fact that a comparison measures agreement between two
   systems, not ground truth: neither transcript is a human-verified reference.
6. `## Findings and handoff` routes each failure or surprise to a bounded follow-up with reproducing
   evidence. No product repair happens inside this workflow.

## Results

Executed by `ops-engineer` on 2026-09-22 (UTC 11:29:18 → 12:45:26) on the target host
`DESKTOP-HHFROLO` (192.168.3.21, WSL2). Every command below ran as
`ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes -o ConnectTimeout=20 chosenecho@192.168.3.21 'wsl -e bash -s'`
with the script on stdin; the session cookie was loaded with `set -a; . /root/workspace/bilibili-asr-archive/.env; set +a`
and never printed or recorded. Log directory (cited as `$LOG`):
`/root/e2e-asr/logs/asr-vs-subtitle-20260922T1130Z/`.

| Scenario | Expected | Actual | Outcome | Evidence |
|---|---|---|---|---|
| A0 | HEAD `37b0acc…`; `git status --porcelain` = the pre-existing `?? .env.bak-20260917-181947` only; `--version` = `0.1.0` from both entry points; bare `check-asr-env` recorded; same command with `HSA_ENABLE_DXG_DETECTION=1` → exit 0 naming the RX 7800 XT / `gfx1101`; torch + interpreter recorded | HEAD `37b0acce5dbd4e0d0992b69bdce5c8bd4d8e1030`; `git status --porcelain` = `?? .env.bak-20260917-181947` only; both entry points print `bili-asr 0.1.0` and both resolve `bili_asr.__file__` = `/root/workspace/bilibili-asr-archive/bilibili-asr-archive/src/bili_asr/__init__.py`; **this run used `/root/gpu-venv/bin/bili-asr`** on `/root/gpu-venv/bin/python` 3.12.3 with torch `2.9.1+rocm7.2.0.git7e1940d4` (hip `7.2.26015-fc0010cf6a`); **bare** `check-asr-env` → **exit 1** (`dxg-detection FAIL … HSA_ENABLE_DXG_DETECTION=unset`, `device-probe FAIL … torch.cuda.is_available() == False`); same command with `HSA_ENABLE_DXG_DETECTION=1` → **exit 0**, `device ok name=AMD Radeon RX 7800 XT arch=gfx1101 vram_gb=15.8` | **passed** | `$LOG/a0-build-identity.log` |
| A1 | `fetch-meta --mid 23191782 --start-page 4 --limit-pages 3` exits 0; `derive-manifest` exits 0 with all six `bvid:p0` in the effective manifest as `needs_audio` with positive `duration_s`; queue/derived counters and store transcript count recorded; any of the six missing → stop and `blocked` | First `fetch-meta` invocation **exit 2** (`metadata gateway failure (rate_limited)`, `outcome=risk_interrupted`, 1 page, 0 videos, no cursor) — page 4 rate-limited; a bounded retry script (8 attempts, 120 s backoff) succeeded on **attempt 1**: **exit 0**, `collected 3 page(s)`, `outcome=limited`, `cursor: next_page=7`, pages 4/5/6 all `ok`, 90 videos / 90 parts. `derive-manifest` → **exit 0**, `queue=90 derived=90 already_derived=0 chain_owned=0 identity_mismatch=0`; all six present as `needs_audio` with duration_s 6395 / 2598 / 5112 / 2087 / 2408 / 7682; `COUNT(transcripts) = 0` (nothing harvested in this root) | **passed** | `$LOG/a1-fresh-root-enumeration.log`, `$LOG/a1-fetch-meta-retry.log`, `$LOG/a1b-queue-admission.log` |
| A2 | One `download-audio --missing-subs --bvid <bvid>:p0` per item, each exit 0; row reaches `audio_ok`; the audio object exists under the artifact root with a byte size; per-item and total bytes/timings | 6/6 invocations **exit 0**; every row `audio_ok` with `audio_path` = `audio/<bvid>.p0.m4a` under this run's artifact root; per-item wall 1 / 1 / 2 / 2 / 2 / 4 s; total audio **145 596 128 bytes** (9 491 630 → 52 514 154 per item) | **passed** | `$LOG/a2-item1-download.log`, `$LOG/a2-rest-download.log`, `$LOG/a4-artifact-root.sha256` |
| A3 | One `asr --pending --bvid <bvid>:p0` per item with `HSA_ENABLE_DXG_DETECTION=1`, each exit 0; a stored transcript with `source_kind` (record the actual), language, model/version identity, segment count > 0, `content_sha256`; per-item + total GPU wall time and the run's own rtf | 6/6 invocations **exit 0**, every row `archived`; actual `source_kind` = **`asr`**; language = **`''`** (empty, recorded actual); model `FunAudioLLM/Fun-ASR-Nano-2512` revision `''`, device `cuda`, VAD `fsmn-vad` (`vad_max_segment_s=30.0`); segments 1248 / 489 / 952 / 425 / 503 / 1489 (all > 0, srt cue counts equal); per-item `content_sha256` recorded. Wall 377 / 414 / 421 / 741 / 1022 / 1191 s = **4166 s for 26 282 s of audio (raw rtf 0.159)**; the engine's own figures: guard probe `rtf_avg 0.147, time_speech 2086.827, time_escape 306.754`, per-chunk rtf 0.102–0.202. **Time guard not triggered** (first item rtf 0.180 ≪ 0.5) → all six processed. The store's `transcripts` table is caption-only and stays at 0 rows, so the ASR identity is read from the raw sidecar + md frontmatter + manifest row (see `## Findings` F4) | **passed** | `$LOG/a3-probe-BV1zz5zzFENq.log`, `$LOG/a3-asr-batch.log`, `$LOG/a3-asr-batch.sh`, `$LOG/a3-transcript-identity.log` |
| A4 | One `publish-transcripts --bvid <bvid>:p0` per item, each exit 0; four families + `.bundle-ready` under this run's artifact root with byte sizes and `sha256`; the read-only reference root byte-unchanged vs a `sha256` set taken before A2 | 6/6 invocations **exit 0**, but each printed `candidates=0 published=0 already_published=0 failed=0` — the `asr` stage itself had already written the bundles, so the publish command is a no-op in this audio-only root (scope correction below). Artifact root holds **36 files**: 6 audio + 6 srt + 6 `.srt.bundle-ready` + 6 txt + 6 raw + 6 md; every item has all four families **and** the marker; each marker's recorded `sha256` for md/raw/srt/txt equals the `sha256` recomputed from the on-disk bytes (24/24 match). Read-only root: pre-set (30 files) vs post-set vs final-set are **identical**, set-file `sha256 = 099224b4b518bd9542fdb07cc8e95099addd19341a2f9c5c9bd514561a4e66e0` at all three moments | **passed** | `$LOG/a4-publish-and-reference-proof.log`, `$LOG/a4-sha256-and-reference-proof.log`, `$LOG/a4-artifact-root.sha256`, `$LOG/a4-pre-reference-root.sha256`, `$LOG/a4-post-reference-root.sha256`, `$LOG/a4-final-reference-root.sha256` |
| A5 | Locate each item's AI reference (`txt`, `raw` side), record `sha256` + character count; re-fetch **one** item's live caption inventory + document read-only and compare against the stored reference (same track set, same normalized text) | All six references located under the read-only root with `sha256` and byte/char counts recorded (txt 25 256–86 168 bytes, raw 84 397–304 334 bytes). Freshness control on `BV1zz5zzFENq:p0` (cid 29471998505): live inventory exposes **exactly 1 track** (`lan=ai-zh`, `lan_doc=中文`, `ai_status=2`, `type=1`); the live document has **797 cues** → normalized **8173 chars**, **identical** to the stored reference sidecar (`transcripts/raw/BV1zz5zzFENq.p0.json`, `source='subtitle-ai'`, `sha256 0c3e8989…`, 797 segments, 8173 chars). The label "live" is therefore earned for this item | **passed** | `$LOG/a5-reference-integrity-freshness.log`, `$LOG/a5-freshness.py`, `$LOG/a5-live-BV1zz5zzFENq.json` |
| A6 | Per item one `coverage … --quality --reference <AI txt> --format json` (exactly one selected row), recording `reference.agreement`, `reference.floor`, `reference.compared_chars` and whether `reference_disagreement` appears | Six separate invocations. **4 of 6 exit 0**: `BV1Y7M4zNEfF` agreement 0.9556635286972366 floor 0.95 chars (9855, 9903) no disagreement · `BV1vNTqzFEve` 0.9283032256157053 (16851, 16972) **`reference_disagreement` present** · `BV1zz5zzFENq` 0.9506682867557715 (8173, 8287) no disagreement · `BV11p5qzAE6s` 0.9352376798953336 (9091, 9253) **`reference_disagreement` present**. **2 of 6 exit 1** with `coverage: reference too large to compare` and no JSON payload: `BV1BdtazGEBE`, `BV1iddQYQE7D` | **failed** | `$LOG/a6-coverage-reference-six.log`, `$LOG/a6-<bvid>.json`, `$LOG/a6-<bvid>.err` |
| A7 | Bounded read-only analysis over the two published documents per item — normalization printed, character counts, edit-distance CER with the reference side stated, cue counts + mean cue duration, default-hotword presence/one-sided terms, aligned excerpts | Executed by `$LOG/a7-compare.py` (evidence tooling under the log dir, **no product file touched**): all six items compared, full printed output and six-row summary table saved. Cross-check: the independently recomputed product metric equals the product's own `agreement` to the last printed digit for all four comparable items, and the independently computed N1 character counts equal `compared_chars` exactly — the product reader and the independent reader agree on the metric | **passed** | `$LOG/a7-independent-comparison.log`, `$LOG/a7-compare.py`, `$LOG/a7-hotwords.json` |
| A8 | `verify --scope <bvid>:p0 --trusted-local` per item → zero defects on the six ASR rows; `coverage --quality --scope` per item prints the row; ASR products only under this run's root and AI products only under the read-only root; `search` returns text from at least one ASR row; `export --format json --status archived` lists the six **and their manifest rows carry the ASR `source` value recorded in A3** | `verify`: all six `defect_count: 0`, `defects: []` (**zero defects, as required**) but **exit 1** with `authoritative: false` and `diagnostic: missing_attempts_sidecar`. `coverage --quality`: 6/6 exit 0, each prints its row (`status=archived`, `artifact_count=4`, reasons `low_confidence`/`overlong_cue`/`repeated_ngram`±`duplicate_cue`). Inventories are separable (36 files vs 30 files, disjoint roots, no ASR-named artifact under the reference root; both sides' `raw` sidecar `source` = `asr` vs `subtitle-ai`). `search 革命者` returns an ASR row with a snippet (`BV1zz5zzFENq:p0`, exit 0) — but `search … --source asr` / `--source asr-local` / `--source subtitle-ai` all **exit 1** `no matching transcripts found` because the index's `source` column is empty for all 6 rows. `export --format json --status archived` lists the six with all four paths + audio, but carries **no `source` field at all**; the ASR manifest rows omit `source`/`language` while the previous caption run's rows carry `"source": "subtitle-ai"` | **failed** | `$LOG/a8-readers-and-separability.log`, `$LOG/a8-dig-verify-and-search.log`, `$LOG/a8-verify-<bvid>.json`, `$LOG/a8-export-archived.json`, `$LOG/final-integrity-and-source-identity.log`, `$LOG/final-prev-manifest-source.log` |

**Executor's corrections and clarifications to `## Scope`** (recorded by the executor, not the PM):

1. Scope's environment line states torch `2.9.1+rocm7.2.0.lw`; the measured version is **`2.9.1+rocm7.2.0.git7e1940d4`** (hip `7.2.26015-fc0010cf6a`). Same recipe family, different build string.
2. Scope's A3 expects "a stored transcript exists" with `source_kind`/`language`/`model`/`version`/`content_sha256`. **No DB transcript row exists for an ASR product**: `storage/models.py:471-476` defines `ALLOWED_CAPTION_SOURCE_KINDS = ALLOWED_SOURCE_KINDS - {"asr-local"}`, so the `transcripts` table (and `transcript_segments`, `asr_models`, `audio_objects`) stay at 0 rows in this root and `v_pending_subtitles` counts all 90 parts regardless of ASR completion. The A3 fields were therefore read from the archived **raw sidecar** (`source`, `provenance`) and the **md frontmatter** (`asr_model_name`, `asr_device`, VAD stats). The assertion is evidenced, the storage location differs from the wording.
3. Scope's A1 expects `fetch-meta … exits 0`. The first invocation exited **2** (`rate_limited`, nothing stored); the same command in a bounded retry loop exited **0**. Recorded as an actual, not reworded as a pass.
4. Scope's A4 treats `publish-transcripts` as the publishing step. Measured: it is a **no-op** here (six exit 0, `candidates=0` for each) because its range is "every stored part that holds a transcript" and this root has no transcript rows; the `asr` stage had already written all four families + marker. A4's artifact expectation is met by that output.
5. Scope's A8 requires the manifest rows to carry the ASR `source` value from A3. Measured: **they do not** — the ASR archive path writes no `source`/`language` on its manifest row (the previous caption run's rows do). This is the clause A8 fails on; treated as a finding (F2), not worked around.

### Comparison table (A6 + A7)

Six rows, one per item, all produced in this run. `ASR chars` / `AI chars` are the **N1**
character counts — the printed normalization (identical to the product's own
`flatten_reference`: drop `。，？！、；：,?!.;:…—·"'“”‘’（）()《》`, drop all whitespace, lowercase) applied
to both sides; the product's `compared_chars` for the four comparable items are these same two
numbers. `independent CER` = `Levenshtein.distance(ASR_n1, AI_n1) / len(AI_n1)` with the **AI caption
as the reference** and the ASR as the hypothesis (rapidfuzz 3.14.6) — a true edit-distance rate, not
`1 − ratio`. Cue counts are the published SRT cue counts, which equal the `raw` sidecar segment
counts on both sides.

| item | audio | ASR chars | AI chars | product `agreement` (floor) | independent CER | ASR cues | AI cues | hotword diffs |
|---|---|---|---|---|---|---|---|---|
| `BV1BdtazGEBE:p0` | 106.6 min | 22995 | 22460 | **refused** — exit 1 `reference too large to compare` (floor 0.95) | 0.1092 | 1248 (mean 3.98 s) | 2318 (mean 2.38 s) | ASR-only 9: 未明子, 主义主义, 国际劳工仲裁, 马恩牌, 实存, International Employment Matters Tribunal, International, Employment, Tribunal · AI-only 0 |
| `BV1Y7M4zNEfF:p0` | 43.3 min | 9903 | 9855 | 0.9557 (floor 0.95), no `reference_disagreement` | 0.0556 | 489 (mean 4.18 s) | 947 (mean 2.47 s) | ASR-only 2: 黑格尔, 扬弃 · AI-only 0 |
| `BV1vNTqzFEve:p0` | 85.2 min | 16972 | 16851 | 0.9283 (floor 0.95), **`reference_disagreement` present** | 0.0901 | 952 (mean 3.97 s) | 1709 (mean 2.49 s) | ASR-only 8: 未明子, 国际劳工仲裁, 齐泽克, 实存, International Employment Matters Tribunal, International, Employment, Tribunal · AI-only 0 |
| `BV1zz5zzFENq:p0` | 34.8 min | 8287 | 8173 | 0.9507 (floor 0.95), no `reference_disagreement` | 0.0646 | 425 (mean 4.13 s) | 797 (mean 2.50 s) | ASR-only 6: 未明子, 智利, International Employment Matters Tribunal, International, Employment, Tribunal · AI-only 0 |
| `BV11p5qzAE6s:p0` | 40.1 min | 9253 | 9091 | 0.9352 (floor 0.95), **`reference_disagreement` present** | 0.0858 | 503 (mean 3.84 s) | 918 (mean 2.42 s) | ASR-only 2: 国际劳工仲裁, 感性 · AI-only 0 |
| `BV1iddQYQE7D:p0` | 128.0 min | 28320 | 28140 | **refused** — exit 1 `reference too large to compare` (floor 0.95) | 0.0951 | 1489 (mean 4.01 s) | 2918 (mean 2.33 s) | ASR-only 16: 未明子, 国际劳工仲裁, 马恩牌, 智利, 亚美利坚, 黑格尔, 齐泽克, 本体论, 定在, 自为, 此在, 实存, International Employment Matters Tribunal, International, Employment, Tribunal · AI-only 0 |

Reading the table: **the two systems track each other closely but are not interchangeable.** Their
verbatim character error rate is 5.6 %–10.9 % (mean 8.4 %), i.e. roughly 1 character in 12 differs,
and where the product can compare at all its ratio (0.9283–0.9557) sits within ±0.03 of the
independently recomputed product metric — two very different implementations of the same quantity
agree to four decimals, so the ASR transcript really is a close paraphrase of the AI caption rather
than a coincidental match. **Where they diverge:** (a) segmentation, systematically — the AI caption
emits 1.8–2.0× more cues (mean 2.33–2.50 s) than the ASR (mean 3.84–4.18 s), so the ASR side reads as
longer merged utterances; (b) vocabulary, one-sided — the ASR side uses 2–17 of the 33 default
hotwords per item while the AI side uses 0–3, and the AI caption never contains a hotword the ASR
lacks; the sharpest single case is `BV1zz5zzFENq:p0` at t≈525 s, where the ASR (hotword-biased) writes
`他未明子停下脚步` and the AI caption writes `他为你留停下脚步` — the UP's own name is the term the AI
system gets wrong. **What the numbers cannot support:** neither side is ground truth (no human
reference exists for these six items), so CER measures *disagreement between two machine transcripts*,
not accuracy; the two refusal rows have no product comparison and their `reference_disagreement` is
therefore unknown, not absent; and the per-item figures are single-run observations — one ASR pass,
one caption revision, no repeatability study.

## Evidence

Filled by `ops-engineer`. All paths are on the target host `192.168.3.21`. Every command ran over the
one documented channel; `ARCH` = `/root/e2e-asr/asr-vs-subtitle`,
`ART` = `/mnt/123pan/bili-asr-e2e/asr-vs-subtitle`, `REF` = `/mnt/123pan/bili-asr-e2e/subtitle-publish`
(**read-only input**), `LOG` = `/root/e2e-asr/logs/asr-vs-subtitle-20260922T1130Z` (this run's log dir,
created by this run; all raw logs cited below live there). SESSDATA was loaded from
`/root/workspace/bilibili-asr-archive/.env` with `set -a; . …/.env; set +a`; its value is nowhere in
this report or in any log — only the path and a length are ever mentioned.

### Channel and environment identity

```
ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes -o ConnectTimeout=20 chosenecho@192.168.3.21 'wsl -e bash -s' <script-on-stdin
```
`DESKTOP-HHFROLO`, Ubuntu 24.04.1 LTS, kernel `6.18.33.2-microsoft-standard-WSL2`, AMD Radeon RX 7800 XT
`gfx1101` (15.8 GB), `/root/gpu-venv/bin/python` 3.12.3, torch `2.9.1+rocm7.2.0.git7e1940d4`,
hip `7.2.26015-fc0010cf6a`, funasr 1.4.14, rapidfuzz 3.14.6, numpy 1.26.4. Target checkout
`/root/workspace/bilibili-asr-archive` at `37b0acce5dbd4e0d0992b69bdce5c8bd4d8e1030`, product root
`/root/workspace/bilibili-asr-archive/bilibili-asr-archive`. Every ASR invocation exported
`HSA_ENABLE_DXG_DETECTION=1`.

### A0 — build identity and the host gate (`$LOG/a0-build-identity.log`)

```
cd /root/workspace/bilibili-asr-archive && git rev-parse HEAD            # 37b0acce5dbd4e0d0992b69bdce5c8bd4d8e1030  [exit=0]
git status --porcelain                                                   # ?? .env.bak-20260917-181947                [exit=0]
/root/gpu-venv/bin/bili-asr --version                                    # bili-asr 0.1.0                              [exit=0]
/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/bili-asr --version   # bili-asr 0.1.0             [exit=0]
/root/gpu-venv/bin/python -c 'import bili_asr,sys;print(bili_asr.__file__);print(sys.executable);print(sys.version)'
/root/gpu-venv/bin/python -c 'import torch;print(torch.__version__);print(torch.version.hip)'
/root/gpu-venv/bin/bili-asr check-asr-env                                # [exit=1]  bare
HSA_ENABLE_DXG_DETECTION=1 /root/gpu-venv/bin/bili-asr check-asr-env     # [exit=0]  device ok name=AMD Radeon RX 7800 XT arch=gfx1101 vram_gb=15.8
```
Bare-gate failing checks: `dxg-detection FAIL dxg_device=path-exists (not opened) HSA_ENABLE_DXG_DETECTION=unset`
and `device-probe FAIL torch.cuda.is_available() == False`; `rocm-loader-path`, `torch-present`,
`hsa-runtime` all `ok`. **Run entry point: `/root/gpu-venv/bin/bili-asr`.**

### A1 — fresh root, enumeration, queue admission (`$LOG/a1-fresh-root-enumeration.log`, `$LOG/a1-fetch-meta-retry.log`, `$LOG/a1b-queue-admission.log`)

```
mkdir -p /root/e2e-asr/asr-vs-subtitle /mnt/123pan/bili-asr-e2e/asr-vs-subtitle   # both created empty (find → no entries)
set -a; . /root/workspace/bilibili-asr-archive/.env; set +a                      # BILI_SESSDATA loaded (len=222, value not recorded)
bili-asr fetch-meta --mid 23191782 --start-page 4 --limit-pages 3 --archive-root /root/e2e-asr/asr-vs-subtitle
#   attempt 1: fetch-meta: metadata gateway failure (rate_limited); no cursor recorded   [exit=2]
#   retry script $LOG/a1-fetch-meta-retry.sh (8 attempts, 120 s backoff) attempt 1: collected 3 page(s) for mid=23191782 (outcome=limited)  [exit=0]
bili-asr derive-manifest --archive-root /root/e2e-asr/asr-vs-subtitle            # queue=90 derived=90 already_derived=0 chain_owned=0 identity_mismatch=0  [exit=0]
```
Store assertions (read-only SQLite open, `file:…/archive.db?mode=ro`):

| query | result |
|---|---|
| `SELECT COUNT(*) FROM transcripts` | **0** (nothing harvested in this root) |
| `SELECT COUNT(*) FROM video_parts` / `FROM v_pending_subtitles` | 90 / **90** |
| `SELECT page_number,outcome,error_code FROM ingestion_pages` | `(4,risk_interrupted,rate_limited) (4,ok,None) (5,ok,None) (6,ok,None)` |
| `SELECT bvid,page_index,cid,duration_ms FROM video_parts WHERE bvid IN (six)` | BV1BdtazGEBE:p0 cid 31594841414 6395000 · BV1Y7M4zNEfF:p0 30506419561 2598000 · BV1vNTqzFEve:p0 30412768784 5112000 · BV1zz5zzFENq:p0 29471998505 2087000 · BV11p5qzAE6s:p0 29471278516 2408000 · BV1iddQYQE7D:p0 29363077962 7682000 |
| manifest rows for the six | 6 rows `"status": "needs_audio"` with `duration_s` 6395 / 2598 / 5112 / 2087 / 2408 / 7682 |

### A2 — audio acquisition (`$LOG/a2-item1-download.log`, `$LOG/a2-rest-download.log`)

```
bili-asr download-audio --missing-subs --bvid <bvid>:p0 --archive-root /root/e2e-asr/asr-vs-subtitle --artifact-root /mnt/123pan/bili-asr-e2e/asr-vs-subtitle
```
Six invocations, each `[exit=0]`, each printing `<bvid>:p0: audio downloaded -> audio_ok (audio/<bvid>.p0.m4a)`
and `download-audio: 1 audio_ok`; every manifest row reached `status=audio_ok` with its `audio_path`.
Walls: 1 / 1 / 2 / 2 / 2 / 4 s. Audio bytes (sha256 recomputed from the disk):

| file under `$ART` | bytes | sha256 |
|---|---|---|
| `audio/BV11p5qzAE6s.p0.m4a` | 11 389 972 | `ad61d4e46f5c09aa9417bf77b1b56a858353badbd90fa7708a04539b91308751` |
| `audio/BV1BdtazGEBE.p0.m4a` | 52 514 154 | `1dfa531106e28a1bc2f00c2c8a558f2b9fa9c52b34872f345e64d1f5fb983dcb` |
| `audio/BV1Y7M4zNEfF.p0.m4a` | 11 990 340 | `e213bb6f04b1614d7cba611f003caaf36655d900776ad3a2c0c25f81dfbe9c89` |
| `audio/BV1iddQYQE7D.p0.m4a` | 36 438 834 | `8723b98dff52f4c3aac41df4aebcdaac98cef109733a43d120b4f14a49ad4327` |
| `audio/BV1vNTqzFEve.p0.m4a` | 23 771 198 | `fd0b10c87b3ff0de47489d128c3cf9e2030f2298297bc60072b8afd602afd12d` |
| `audio/BV1zz5zzFENq.p0.m4a` | 9 491 630 | `3af3193fca36d24d57801a7550eef55191170cbc00c4d5f4a2481910840f8a24` |
| **total** | **145 596 128** | — |

### A3 — GPU transcription (`$LOG/a3-probe-BV1zz5zzFENq.log`, `$LOG/a3-asr-batch.log`, `$LOG/a3-asr-batch.sh`, `$LOG/a3-transcript-identity.log`)

```
HSA_ENABLE_DXG_DETECTION=1 bili-asr asr --pending --bvid <bvid>:p0 --archive-root /root/e2e-asr/asr-vs-subtitle --artifact-root /mnt/123pan/bili-asr-e2e/asr-vs-subtitle
```
Six invocations, each `[exit=0]`, each printing `<bvid>:p0: archived (asr)` / `asr: 1 archived`
(the guard probe additionally printed `asr: model constructions=1 for 1 asr item(s)`).

| item | audio_s | wall_s | raw rtf | engine figures |
|---|---|---|---|---|
| `BV1zz5zzFENq` (guard probe, first) | 2087 | 377 | **0.180** | `rtf_avg 0.147, time_speech 2086.827, time_escape 306.754` |
| `BV11p5qzAE6s` | 2408 | 414 | 0.171 | per-chunk rtf 0.113–0.202 |
| `BV1Y7M4zNEfF` | 2598 | 421 | 0.162 | — |
| `BV1vNTqzFEve` | 5112 | 741 | 0.144 | — |
| `BV1BdtazGEBE` | 6395 | 1022 | 0.159 | — |
| `BV1iddQYQE7D` | 7682 | 1191 | 0.155 | — |
| **total** | **26 282** | **4166** | **0.159** | batch-only total: 3789 s for 24 195 s |

Bounded-time guard: the measured first-item rtf 0.180 is far below the ~0.5 threshold, so no item was
skipped and the whole queue was processed. Per-item transcript identity (raw sidecar `source` /
`provenance`, md frontmatter, and the sha256 of the archived sidecar recomputed from disk):

| item | `source` | language | model / revision | device | segments | `content_sha256` (raw sidecar) | VAD captured ratio / mean conf |
|---|---|---|---|---|---|---|---|
| `BV1BdtazGEBE:p0` | `asr` | `''` | `FunAudioLLM/Fun-ASR-Nano-2512` / `''` | `cuda` | 1248 | `f71993f8c71a8198c9aaab76ec1c722640789ff5c9e720097722c4951314d826` | 0.822 / 0.802 |
| `BV1Y7M4zNEfF:p0` | `asr` | `''` | `FunAudioLLM/Fun-ASR-Nano-2512` / `''` | `cuda` | 489 | `b4a941e9a43ec2e3ec9a1988c5e005b030fe162f4754123a716b3a6766a242e6` | 0.831 / 0.831 |
| `BV1vNTqzFEve:p0` | `asr` | `''` | `FunAudioLLM/Fun-ASR-Nano-2512` / `''` | `cuda` | 952 | `c50b9f0877131c309eed4ec7b7c1db2ebd63d0be6305b191aa12f065f1cd7b39` | 0.784 / 0.798 |
| `BV1zz5zzFENq:p0` | `asr` | `''` | `FunAudioLLM/Fun-ASR-Nano-2512` / `''` | `cuda` | 425 | `a814d5084ebf092f83a3d4c06fd880a234d7427bb17c354a6a20a68227b38f5d` | 0.908 / 0.823 |
| `BV11p5qzAE6s:p0` | `asr` | `''` | `FunAudioLLM/Fun-ASR-Nano-2512` / `''` | `cuda` | 503 | `06de4e45b3522dddcab36d4609f81ca1b9d4cf30921e60db5871f35f8bf43b2f` | 0.865 / 0.805 |
| `BV1iddQYQE7D:p0` | `asr` | `''` | `FunAudioLLM/Fun-ASR-Nano-2512` / `''` | `cuda` | 1489 | `db012cdc42982bd4c35d51c984dc5ccb3dfb640606d7d7fc5c88960115f35e79` | 0.827 / 0.778 |

Store assertions after A3 (read-only): `COUNT(transcripts) = 0`, `COUNT(transcript_segments) = 0`,
`COUNT(asr_models) = 0`, `COUNT(audio_objects) = 0`, `COUNT(part_audio_objects) = 0`; all six manifest
rows `status=archived` with `srt_path`/`txt_path`/`raw_path`/`md_path` set. The ASR product does not
create DB rows — see `## Findings` F4.

### A4 — bundles and the read-only-root proof (`$LOG/a4-publish-and-reference-proof.log`, `$LOG/a4-sha256-and-reference-proof.log`, `$LOG/a4-artifact-root.sha256`, `$LOG/a4-pre-reference-root.sha256`, `$LOG/a4-post-reference-root.sha256`, `$LOG/a4-final-reference-root.sha256`)

```
bili-asr publish-transcripts --bvid <bvid>:p0 --archive-root /root/e2e-asr/asr-vs-subtitle --artifact-root /mnt/123pan/bili-asr-e2e/asr-vs-subtitle
# each: publish-transcripts: candidates=0 published=0 already_published=0 failed=0   [exit=0]  wall 0 s
find $ART -type f -print0 | sort -z | xargs -0 sha256sum > $LOG/a4-artifact-root.sha256     # 36 files
find $REF -type f -print0 | sort -z | xargs -0 sha256sum > $LOG/a4-post-reference-root.sha256
diff $LOG/a4-pre-reference-root.sha256 $LOG/a4-post-reference-root.sha256    # no output → IDENTICAL
diff $LOG/a4-pre-reference-root.sha256 $LOG/a4-final-reference-root.sha256   # no output → IDENTICAL (final re-check at 12:45:26Z)
sha256sum $LOG/a4-pre-reference-root.sha256  $LOG/a4-post-reference-root.sha256  $LOG/a4-final-reference-root.sha256
#   099224b4b518bd9542fdb07cc8e95099addd19341a2f9c5c9bd514561a4e66e0  (all three, 30 lines each)
```
The read-only root was byte-unchanged at all three observation points: the pre-A2 set, the post-publish
set, and the final set taken after A6/A7/A8. Published products of this run (36 files under `$ART`; the
six audio files are the table above):

| file under `$ART` | bytes | sha256 |
|---|---|---|
| `transcripts/srt/BV1BdtazGEBE.p0.srt` | 120 220 | `8eaf8376b64a36583a2c503be09a6ae2bc799852141a0f24fb9988e4bae84fbb` |
| `transcripts/srt/BV1BdtazGEBE.p0.srt.bundle-ready` | 789 | `efee77c7a64eab6db4ce7932679023dd58f841c9a9efeef450a7f039871c622f` |
| `transcripts/srt/BV1Y7M4zNEfF.p0.srt` | 49 825 | `3fb754129949e3eff8dfd574f5b74d54b91026757cc98f2f101d755389b2c298` |
| `transcripts/srt/BV1Y7M4zNEfF.p0.srt.bundle-ready` | 669 | `066abf2ca142f8b57db04e01f61cfb99e68bcbde01738f6a156639b7981ac624` |
| `transcripts/srt/BV1vNTqzFEve.p0.srt` | 89 041 | `ea6017643f2661b8c6fc518fb72f494923bd47672e3dc5c2b234769c9d7d056c` |
| `transcripts/srt/BV1vNTqzFEve.p0.srt.bundle-ready` | 681 | `e3d9b16181eaf7d59fb7cc6978facb09926c131b85a1f2c7829172268c59d95d` |
| `transcripts/srt/BV1zz5zzFENq.p0.srt` | 42 411 | `28ef7551b7f8f3ee9c0bb7fe057177299696102a917cc224d0cf8767992fd5c1` |
| `transcripts/srt/BV1zz5zzFENq.p0.srt.bundle-ready` | 669 | `5d735daa60511e126449e49b0b15b5365e3999f9e00cc71f467388cbcef3dc92` |
| `transcripts/srt/BV11p5qzAE6s.p0.srt` | 48 572 | `665af479c48912e2a74c22acab208a05139b1c0c424aa8b36b665ff6ecca1ebb` |
| `transcripts/srt/BV11p5qzAE6s.p0.srt.bundle-ready` | 741 | `aa234fbcd9b5ee68b918d2c48fa0d9ca736dffa78e8f1cdc8f20570e677c3564` |
| `transcripts/srt/BV1iddQYQE7D.p0.srt` | 147 218 | `bd936434542a09f8d0072d9cfe784150dba4feafe16ba52c9146c98198f2831d` |
| `transcripts/srt/BV1iddQYQE7D.p0.srt.bundle-ready` | 765 | `1dcfd0b85b8e57cb2daf0906b4f82795da64f98cd9f024997c618f62f13e1162` |
| `transcripts/txt/BV1BdtazGEBE.p0.txt` | 76 400 | `b39239304b46748989f4df10ee6072c1ff8b45ed3969c427a933365d7d5a2d66` |
| `transcripts/txt/BV1Y7M4zNEfF.p0.txt` | 32 819 | `2722b7999e66f35654bacdf73df4ce2e27cd00bff6ef919bd5cca4e4f2493e3d` |
| `transcripts/txt/BV1vNTqzFEve.p0.txt` | 55 830 | `98a639fe970502d14106238f98481a72055a4cd57bcd97389c9d1cb9d51bacc7` |
| `transcripts/txt/BV1zz5zzFENq.p0.txt` | 27 645 | `dc15c20d9014271c708c96cef8864a193ae34f99c90050db328803e72852d9c3` |
| `transcripts/txt/BV11p5qzAE6s.p0.txt` | 31 076 | `f69c4e8c09be035175caac2b19c3402d3ecbe0709f0c984b3fbd5eb872aa93ca` |
| `transcripts/txt/BV1iddQYQE7D.p0.txt` | 94 722 | `9a3fca15bf1271b341b31bbe3fc052e571907145497669d31b930ee24f1faf61` |
| `transcripts/raw/BV1BdtazGEBE.p0.json` | 203 556 | `f71993f8c71a8198c9aaab76ec1c722640789ff5c9e720097722c4951314d826` |
| `transcripts/raw/BV1Y7M4zNEfF.p0.json` | 82 810 | `b4a941e9a43ec2e3ec9a1988c5e005b030fe162f4754123a716b3a6766a242e6` |
| `transcripts/raw/BV1vNTqzFEve.p0.json` | 152 893 | `c50b9f0877131c309eed4ec7b7c1db2ebd63d0be6305b191aa12f065f1cd7b39` |
| `transcripts/raw/BV1zz5zzFENq.p0.json` | 71 119 | `a814d5084ebf092f83a3d4c06fd880a234d7427bb17c354a6a20a68227b38f5d` |
| `transcripts/raw/BV11p5qzAE6s.p0.json` | 82 472 | `06de4e45b3522dddcab36d4609f81ca1b9d4cf30921e60db5871f35f8bf43b2f` |
| `transcripts/raw/BV1iddQYQE7D.p0.json` | 246 405 | `db012cdc42982bd4c35d51c984dc5ccb3dfb640606d7d7fc5c88960115f35e79` |
| `transcripts/md/2025-08-09_BV1BdtazGEBE.p0_【哲学与现实】….md` | 77 570 | `219890b510ae178337644c172288ae837bdd50303e1974b865a68ac2e65e65de` |
| `transcripts/md/2025-06-15_BV1Y7M4zNEfF.p0_【行动指南】从爱情走向革命.md` | 33 814 | `ebdd4e7ed253b5a999dbef805ea414bea0b3a0029a10ce0f7cbc22aa55728fd6` |
| `transcripts/md/2025-06-09_BV1vNTqzFEve.p0_【爱欲经济学】….md` | 57 004 | `8a59a6af6528770e6ad219da6f393b0bb517a4bb1864e4ea7b8559d1c19be5f0` |
| `transcripts/md/2025-04-17_BV1zz5zzFENq.p0_【历史唯物主义】革命与爱情.md` | 28 640 | `2f916296582cfeb20ec3a4f3504bbefd2348b9c022590904838e6f45710f5bc0` |
| `transcripts/md/2025-04-17_BV11p5qzAE6s.p0_【实事求是】….md` | 32 125 | `67f42121495e6f36fb54ba043cbdacb7e0a5e9e1462de6ef96e5e0cbfb09c7bf` |
| `transcripts/md/2025-04-11_BV1iddQYQE7D.p0_【随便聊聊】….md` | 96 172 | `84bf6dc890d1bf1c4f3e955ff13e880e8c3f56d0a6736fe1af7634aaedfd2fdc` |

Each `.bundle-ready` marker records the four artifact paths with their `sha256`; every recorded value
equals the recomputed on-disk value (24/24). Marker payloads are in `$LOG/a4-sha256-and-reference-proof.log`.

### A5 — reference integrity and the freshness control (`$LOG/a5-reference-integrity-freshness.log`, `$LOG/a5-freshness.py`, `$LOG/a5-live-BV1zz5zzFENq.json`)

Read-only reference documents (all under `$REF`, never written):

| item | `transcripts/txt/<bvid>.p0.txt` bytes / sha256 | `transcripts/raw/<bvid>.p0.json` bytes / sha256 | chars (txt, incl. newlines) |
|---|---|---|---|
| `BV1BdtazGEBE:p0` | 68 688 / `c8aede8d11b6406d99b012962fb22b69c5403efe48a9e97145c2c94b07948ad3` | 241 841 / `05ec43be74928670662769c0ee8a0a01caca685c0fec9720da6b6ab07fa36990` | 24 868 |
| `BV1Y7M4zNEfF:p0` | 30 222 / `9f78f20958679b80916863065e3ee347689962cf7d747c96a114f67c76040579` | 100 614 / `e650a2c0f8316dcf4717b192e2e4a81f1f21cc0d344b070f2da58536ad6906d8` | 10 818 |
| `BV1vNTqzFEve:p0` | 50 791 / `cd5f7109fc8bf334fc37e1c1fe959b30e3b722d4d0f65d94116e45a964f9118a` | 178 213 / `0ee4bd2bb25710b69638797ceea4ab8e2585faadf24b6b84c8c64146f5cfed7b` | 18 693 |
| `BV1zz5zzFENq:p0` | 25 256 / `c5af56404f45da20f2ca65eff6a87d1ee6289066a94a19448671b7b43dca758a` | 84 397 / `0c3e89896e7619663865910d0c3a3b13ce68c3d89a9b89e8d25eed7a852dbfda` | 8 976 |
| `BV11p5qzAE6s:p0` | 28 012 / `defbcc79a27a2286729e76c72be42015d9bcf6aaf062cf2a2e0bbd0700b8d4d7` | 96 251 / `c8a4cc8958ec041d5f6c89c4b1e92c04cfd78cccef83caec3c6d833d80668d14` | 10 018 |
| `BV1iddQYQE7D:p0` | 86 168 / `4ea186fe5d3b04bb6777b2af50de184a044c02903d96e6389dab46f1f2859ed4` | 304 334 / `8ae784458d708b0ad76644b944a1806ca89b8adfb99904457b5bbb270549ef62` | 31 154 |

Freshness control (read-only gateway re-fetch, script `$LOG/a5-freshness.py`, uses
`BiliClient(sessdata=$BILI_SESSDATA)` → `probe_subs` → `download_subtitle`, writes only the log dir):
live inventory `1 track`, `{"lan": "ai-zh", "lan_doc": "中文", "ai_status": 2, "type": 1, "id": 1734465805871377664}`;
live document **797 cues**, normalized **8173 chars**, `identical=True` against the stored reference
(`source='subtitle-ai'`, 797 segments, 8173 chars, `sha256 0c3e8989…`). The probe output also contained
a short-lived signed CDN URL (`auth_key`, expiry `1790077086`); it is transient, is not the session
cookie, and is deliberately not reproduced here. SESSDATA itself was never printed.

### A6 — the product's own comparison (`$LOG/a6-coverage-reference-six.log`, `$LOG/a6-<bvid>.json`, `$LOG/a6-<bvid>.err`)

```
bili-asr coverage --archive-root /root/e2e-asr/asr-vs-subtitle --artifact-root /mnt/123pan/bili-asr-e2e/asr-vs-subtitle \
  --scope <bvid>:p0 --trusted-local --quality --reference /mnt/123pan/bili-asr-e2e/subtitle-publish/transcripts/txt/<bvid>.p0.txt --format json
```
| item | exit | `reference.agreement` | `reference.floor` | `reference.compared_chars` (asr, reference) | `reference_disagreement` |
|---|---|---|---|---|---|
| `BV1BdtazGEBE:p0` | **1** | — (`coverage: reference too large to compare`, no JSON) | — | — | — |
| `BV1Y7M4zNEfF:p0` | 0 | 0.9556635286972366 | 0.95 | (9903, 9855) | no |
| `BV1vNTqzFEve:p0` | 0 | 0.9283032256157053 | 0.95 | (16972, 16851) | **yes** (`summary.reference_disagreement = 1`) |
| `BV1zz5zzFENq:p0` | 0 | 0.9506682867557715 | 0.95 | (8287, 8173) | no |
| `BV11p5qzAE6s:p0` | 0 | 0.9352376798953336 | 0.95 | (9253, 9091) | **yes** (`summary.reference_disagreement = 1`) |
| `BV1iddQYQE7D:p0` | **1** | — (`coverage: reference too large to compare`, no JSON) | — | — | — |

Walls: 1 / 0 / 2 / 1 / 1 / 0 s. `reference.reference` = the basename `BV1Y7M4zNEfF.p0.txt` etc.

### A7 — the independent comparison (`$LOG/a7-independent-comparison.log`, `$LOG/a7-compare.py`, `$LOG/a7-hotwords.json`)

```
/root/gpu-venv/bin/python $LOG/a7-compare.py BV1BdtazGEBE BV1Y7M4zNEfF BV1vNTqzFEve BV1zz5zzFENq BV11p5qzAE6s BV1iddQYQE7D   # [exit=0] wall 10 s
```
The script is **evidence tooling under the log dir, not product code**; it reads only published
artifacts (`transcripts/txt` and `transcripts/raw` of both roots) plus the manifest for durations, and
writes nothing outside the log dir. It prints, before any result, the normalization it applies to both
sides — drop `。，？！、；：,?!.;:…—·"'“”‘’（）()《》`, drop **all** whitespace (spaces and newlines), lowercase
(`'你好，世界！' -> '你好世界'`, `'A B\nC' -> 'abc'`), i.e. the same N1 the product's `flatten_reference`
computes, which is why the two readers' character counts coincide exactly. The hotword list is not
imported from the product: it is a pinned JSON dump (`$LOG/a7-hotwords.json`, 33 entries) written by
```
cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && /root/gpu-venv/bin/python -c 'from bili_asr.asr import DEFAULT_HOTWORDS; import json; print(json.dumps(list(DEFAULT_HOTWORDS), ensure_ascii=False))'
```
Metrics printed per item (and defined in the script header): N1 character counts on both sides, cue-joined
and file-level counts, `Levenshtein.distance(ASR_n1, AI_n1)/len(AI_n1)` as **CER with the AI caption as
reference**, the reverse direction, and the independently recomputed product metric
`difflib.SequenceMatcher(None, ASR_n1, AI_n1, autojunk=False).ratio()`; segment counts, mean/min/max cue
duration and cue span on both sides; per-hotword occurrence counts on both sides with the one-sided
terms named; and the aligned excerpts (opening 3 cues plus windows at 25/50/75/95 % of the item's
duration, paired by absolute wall-clock time so the two sides are comparable). Full per-item output is
the log file; the six-row summary is the table above. Independent-vs-product agreement: recomputed ratio
`0.9557 / 0.9283 / 0.9507 / 0.9352` vs product `0.9556635286972366 / 0.9283032256157053 /
0.9506682867557715 / 0.9352376798953336`, and N1 counts equal `compared_chars` exactly on all four
comparable items.

### A8 — reader agreement and root separability (`$LOG/a8-readers-and-separability.log`, `$LOG/a8-dig-verify-and-search.log`, `$LOG/a8-verify-<bvid>.json`, `$LOG/a8-export-archived.json`, `$LOG/final-integrity-and-source-identity.log`, `$LOG/final-prev-manifest-source.log`)

```
bili-asr verify --archive-root … --artifact-root … --scope <bvid>:p0 --trusted-local --format json
#   each item: {"authoritative": false, "checked": 1, "defect_count": 0, "defects": [], "diagnostics": ["missing_attempts_sidecar"]}   [exit=1]
bili-asr coverage --archive-root … --artifact-root … --scope <bvid>:p0 --trusted-local --quality --format json   # [exit=0] ×6
bili-asr search 革命者 --source asr --limit 3 --format json …          # search: no matching transcripts found  [exit=1]
bili-asr search 革命者 --limit 3 --format text …                       # BV1zz5zzFENq:p0 … (score: -1.6326, path: transcripts/txt/BV1zz5zzFENq.p0.txt)  [exit=0]
bili-asr export --format json --status archived --archive-root … --artifact-root …   # [exit=0] 6 rows, no `source` key
```
`coverage --quality` rows (all `status=archived`, `artifact_count=4`, `diagnostics=[]`): `cue_count`
2496 / 978 / 1904 / 850 / 1006 / 2978 with `reasons` `low_confidence,overlong_cue,repeated_ngram`
(±`duplicate_cue` for `BV1BdtazGEBE`). Search index internals (`search.db` under the **archive** root):
`transcripts_fts` has 6 rows and `SELECT DISTINCT source FROM transcripts_fts` → `[('')]`. Manifest
comparison: this run's six archived rows have **no `source` key**; the previous caption run's archived
rows have `"source": "subtitle-ai", "language": "ai-zh"`. Registered runs (`bili-asr runs`): the two
`fetch-meta` runs of A1 (`outcome=limited`, pages=3, videos=90; `outcome=risk_interrupted`, error=rate_limited).
The read-only root's content is unchanged at the final check (identical set-file sha256, above).

### Write footprint (constraint compliance)

Byte-for-byte, this run wrote only inside `/root/e2e-asr/asr-vs-subtitle` (archive store, manifest,
coordinator lock, `search.db`), `/mnt/123pan/bili-asr-e2e/asr-vs-subtitle` (audio + the four artifact
families + markers) and `/root/e2e-asr/logs/asr-vs-subtitle-20260922T1130Z/` (raw logs plus three
evidence scripts: `a1-fetch-meta-retry.sh`, `a4-publish.sh`, `a8-readers.sh`, and the comparison tool
`a7-compare.py`). Nothing was written under `/mnt/123pan/bili-asr-e2e/subtitle-publish` (measured: 0
files modified since the run began), under `/mnt/e`, or under `/root/workspace` — with one disclosure:
importing the package regenerated one bytecode cache file,
`bilibili-asr-archive/src/bili_asr/__pycache__/audio_reclaim.cpython-312.pyc` (gitignored,
`.gitignore:12`), inside the checkout. No product source, test, spec, knowledge doc, git object,
`.mstar/status.json` or `snapshot.json` was modified (`.mstar/**` is gitignored, `.gitignore:2`, so the
report itself creates no git object either); the checkout still reports HEAD
`37b0acce5dbd4e0d0992b69bdce5c8bd4d8e1030` and `git status --porcelain` = `?? .env.bak-20260917-181947`
only. No pytest and no project test suite was run.

### Reused vs new evidence

All evidence in this report is **new** (produced by this run between 11:29:18Z and 12:45:26Z). The only
reused inputs are the six AI-caption products under `$REF`, which were produced by the earlier
`e2e-23191782-subtitle-publish-webdav` run and are used here as a read-only reference; their identity is
pinned by the sha256 table in A5, and their liveness is separately re-earned by the A5 freshness control.

## Findings and handoff

Five items, ordered by impact. No product repair happened inside this workflow; each is routed to a
bounded follow-up. Findings are evidence, not verdicts on the whole product: A0–A5 and A7 all passed,
and the ASR branch itself is verified end to end on this host.

**F1 — `coverage --reference` refuses any item whose flattened pair exceeds 20 000 characters
(A6, failed on 2/6).** Impact: the product's own caption-vs-ASR telemetry — and therefore the
`reference_disagreement` signal — is unavailable for the long-form items where the comparison matters
most; on this corpus everything longer than roughly 75 minutes of speech is refused. Reproduction:
```
bili-asr coverage --archive-root /root/e2e-asr/asr-vs-subtitle --artifact-root /mnt/123pan/bili-asr-e2e/asr-vs-subtitle \
  --scope BV1iddQYQE7D:p0 --trusted-local --quality --reference /mnt/123pan/bili-asr-e2e/subtitle-publish/transcripts/txt/BV1iddQYQE7D.p0.txt --format json
# → stderr: coverage: reference too large to compare   [exit=1]
```
Measured N1 lengths at the refusal: `BV1BdtazGEBE` (ref 22 460 / asr 22 995), `BV1iddQYQE7D`
(ref 28 140 / asr 28 320) — both over `_MAX_COMPARE_CHARS = 20_000`
(`bilibili-asr-archive/src/bili_asr/quality.py:104`, checked per side in `_compare_reference`). Evidence:
`$LOG/a6-coverage-reference-six.log`, `$LOG/a6-BV1BdtazGEBE.err`, `$LOG/a6-BV1iddQYQE7D.err`.
Suggested bounded follow-up owner: **`@architect`** — decide whether the cap becomes a windowed/sampled
comparison with a stated window, or an explicit "too large, not compared" coverage state that callers
can distinguish from "compared and agreed"; the independent A7 numbers already cover the six items
today, so no repair is urgent for this run.

**F2 — ASR archived rows carry no `source`/`language` in the manifest, so ASR rows are not
distinguishable downstream (A8, failed clause).** Measured: this run's six archived manifest rows have
**no `source` key at all**, while the previous caption run's archived rows carry
`"source": "subtitle-ai", "language": "ai-zh"`. Three visible consequences: the search index's `source`
column is empty for all six rows (`SELECT DISTINCT source FROM transcripts_fts` → `[('')]`) and
`search … --source asr` / `--source asr-local` / `--source subtitle-ai` all exit 1 with
`no matching transcripts found`; `export --format json --status archived` has no `source` field; and
`verify` reports `authoritative: false` + `diagnostic: missing_attempts_sidecar` and exits 1 even with
`defect_count: 0`. The ASR rows are separable in fact (different artifact root, `raw` sidecar
`source: "asr"`, md frontmatter `source: "asr"`, and no audio under the caption root) but not by the
manifest/export/search field the scenario names. Reproduction:
```
bili-asr export --format json --status archived --archive-root /root/e2e-asr/asr-vs-subtitle --artifact-root /mnt/123pan/bili-asr-e2e/asr-vs-subtitle | python3 -m json.tool | head -30
bili-asr search 革命者 --source asr --limit 3 --format json --archive-root /root/e2e-asr/asr-vs-subtitle --artifact-root /mnt/123pan/bili-asr-e2e/asr-vs-subtitle
```
Evidence: `$LOG/a8-dig-verify-and-search.log`, `$LOG/a8-export-archived.json`,
`$LOG/final-prev-manifest-source.log`. Suggested bounded follow-up owner: **`@fullstack-dev`** — give the
ASR archive path the same `source`/`language` projection on its manifest row that the caption path
writes, then re-check `search --source` and `export`; the `missing_attempts_sidecar` diagnostic is a
separate, smaller question for the same owner (this root records no `acquisition_runs`/`attempts.jsonl`,
so `verify` can never be authoritative here).

**F3 — `publish-transcripts` is a no-op in an audio-only root (unexpected behaviour, not a defect for
A4).** Six invocations each printed `candidates=0 published=0 already_published=0 failed=0` and exited 0:
the command's range is "every stored part that holds a transcript", the store's `transcripts` table is
caption-only (`bilibili-asr-archive/src/bili_asr/storage/models.py:471-476`,
`ALLOWED_CAPTION_SOURCE_KINDS = ALLOWED_SOURCE_KINDS - {"asr-local"}`) and holds 0 rows, so it never has
candidates; the `asr` stage had already written all four families plus the marker. A4's artifact
expectation is met by that output, and the marker's recorded hashes match the bytes on disk (24/24).
Impact: operators reading `publish-transcripts` as the ASR publishing step will see a silent no-op that
still exits 0. Evidence: `$LOG/a4-publish-and-reference-proof.log`. Suggested bounded follow-up owner:
**`@product-manager` / `@architect`** for wording or an explicit "no publishable transcripts" outcome;
no code change is required by this verification.

**F4 — the store holds no ASR transcript row (expected per the code, but it contradicts A3's wording).**
`COUNT(transcripts) = 0`, `COUNT(transcript_segments) = 0`, `COUNT(asr_models) = 0`,
`COUNT(audio_objects) = 0`, `COUNT(part_audio_objects) = 0` after six successful ASR runs, and
`v_pending_subtitles` still lists all 90 parts. So a second `derive-manifest` would re-derive the same
90 rows as `needs_audio` — the queue does not drain from ASR work, only from caption harvesting (which
this root deliberately never runs). Impact: for the documented "Route B" shape this is benign and is the
reason the run worked at all; it matters for any consumer that expects ASR provenance in the DB, and it
is why A3's identity fields had to be read from the raw sidecar/frontmatter (see the executor's Scope
correction 2). Evidence: `$LOG/a3-transcript-identity.log`,
`$LOG/final-integrity-and-source-identity.log`. Suggested bounded follow-up owner:
**`@architect`** — decide whether ASR provenance belongs in the store or only in the artifact bundle,
and make the A3-style contract (and `publish-transcripts`' range) follow that decision.

**F5 — host gate residual R1 unchanged, and `fetch-meta` needs a bounded retry (surprises, no repair
expected).** (a) The bare `check-asr-env` still exits 1 because `HSA_ENABLE_DXG_DETECTION=1` is not
persisted on this host; every ASR invocation in this run exported it explicitly, and both invocations
are recorded in A0. Residual `e2e-23191782-subtitle-publish-webdav · R1` therefore stays open and
unchanged by this run. (b) The first `fetch-meta` invocation exited **2** with
`metadata gateway failure (rate_limited)` and stored nothing; the identical command succeeded
immediately on retry (`collected 3 page(s)`, `outcome=limited`). Impact: a single-shot enumeration
script fails intermittently against the gateway; exit 2 is not terminal and a bounded retry is enough.
Evidence: `$LOG/a0-build-identity.log`, `$LOG/a1-fresh-root-enumeration.log` and
`$LOG/a1-fetch-meta-retry.log` (the retry script is `$LOG/a1-fetch-meta-retry.sh`). Suggested bounded
follow-up owner: **`@ops-engineer`** (host configuration, next scheduled run) for (a);
**`@architect`** for (b) if the enumerated-retry behaviour should become the documented run recipe.

**Informational, no owner — the hotword bias is visible in this comparison.** In every one of the six
items the ASR side uses more default hotwords than the caption side (2 / 5 / 7 / 11 / 12 / 17 of 33 vs
0 / 1 / 3), and the caption side never uses a hotword the ASR lacks. The sharpest instance: at t≈525 s of
`BV1zz5zzFENq:p0` the ASR writes `他未明子停下脚步` (the recurring name, a hotword) while the AI caption
writes `他为你留停下脚步`. Evidence: `$LOG/a7-independent-comparison.log`, per-hotword counts printed
there. This observes an association, not a causal measurement — no A/B or control item was run here.

## Not verified

Pre-declared by the PM and still true: the comparison measures **agreement between two machine
transcripts**, not accuracy against ground truth — no human-verified reference exists for these six
items; the ASR model's behaviour outside this host/version is not established; no wheel install was
attempted; the project's full local test suite was not authorized and was not run.

Added by the executor, from what this run actually did:

- **Corpus coverage.** `fetch-meta` covered pages 4–6 only (`--start-page 4 --limit-pages 3`, 90 videos);
  pages 1–3 were not retried in this run, so whether they still rate-limit is unknown. All six items
  came from pages 4–6.
- **Single-run observations.** One ASR pass per item, one caption revision, one device, one model build.
  No repeatability run, no second model, no CPU-vs-GPU comparison, no decoding-parameter sweep; the
  per-item rtf and CER figures are single measurements.
- **`reference_disagreement` for the two refused items is unknown, not absent.** Because the product
  refused those pairs (F1), nothing can be said about whether those rows would have been flagged.
- **Language detection was not exercised.** Every ASR product records `language: ""`; nothing here shows
  what the field holds when the model reports a language.
- **A5's freshness control covered one item.** The other five references were verified by `sha256`
  identity against the read-only root, not re-fetched live; those five captions could have changed
  server-side without this run noticing.
- **The excerpts are for human spot-check, not adjudicated.** The opening three cues plus 25/50/75/95 %
  windows are printed with wall-clock pairing; judging which side is better in any window is explicitly
  outside this run's evidence.
- **The retained audio was not independently inspected.** 145 596 128 bytes of m4a are evidenced by
  byte size and `sha256`, and by ASR having consumed them — not by an independent decode or duration check.
- **The mount, not the object store, was measured.** Byte reads and `sha256` come from the WebDAV mount
  on the target host; the remote store's own consistency was not verified independently.
- **`verify`'s authority gap is reported, not diagnosed.** `missing_attempts_sidecar` / `authoritative:
  false` is recorded as measured; the mechanism that would make an audio-only root authoritative was not
  investigated beyond reading this run's own state.
- **No product file was changed**, by design — so none of F1–F4's proposed changes is validated here,
  and "the run passed" must not be read as those gaps being closed.

## Completion recommendation

Assigned **9** / determinate **9** — **passed 7, failed 2, not-run 0, blocked 0**. Every scenario carries
exactly one outcome, no scenario was left indeterminate, and the bounded-time guard did not fire (the
measured first-item rtf 0.180 is far below the ~0.5 threshold, so all six items were transcribed within
69 minutes of GPU wall time for 7.30 h of audio).

Product result, stated separately from the workflow lifecycle: the **local GPU ASR branch is verified end
to end on this host** for all six items — enumeration → queue admission (`needs_audio`) → audio under the
artifact root → GPU transcription → published bundles whose recorded and recomputed hashes agree → a
read-only reference root proven byte-unchanged at three observation points. **The requested comparison is
delivered per item and as the six-row table above**, with both the product's `agreement` and an
independent edit-distance CER, and with the two readers agreeing to the last printed digit. What failed
is the product's **read** side: its own comparison refuses two of six items (F1) and its ASR rows are not
labeled with `source`/`language` downstream (F2).

Recommendation to PM (lifecycle only): **`workflow completed`** — all nine scenarios have determinate
results, the run itself has no unresolved execution block, and the two failures are routed as bounded
findings rather than presented as execution blockers. Pending actions for the PM: register F1 and F2 as
residuals (both medium — product comparison-reader gap on long items; ASR rows indistinguishable by
`source` in manifest/export/search), leave residual `e2e-23191782-subtitle-publish-webdav · R1` open and
unchanged (F5a), and treat F5b (a bounded `fetch-meta` retry is required; exit 2 is not terminal) as a run
recipe note. No repair is dispatched from this workflow; if a retest is authorized later it needs only A6
and A8 — the ASR artifacts already exist under this run's roots, so the 70-minute GPU phase need not be
repeated.

`ops-engineer` reports results; the PM alone marks the plan Done and closes the workflow.
