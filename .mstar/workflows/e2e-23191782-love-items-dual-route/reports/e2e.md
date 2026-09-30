# E2E Verification Report — 未明子「爱情」4 条稿件，双路线（字幕优先 / 强制音频→ASR）

> **Workflow:** `e2e-23191782-love-items-dual-route` (`type: plan`, verification-only)
> **Status:** scope locked by PM 2026-09-30; execution owned by `ops-engineer`
> **Executor:** `ops-engineer` (PM orchestrates; ops executes and records actual results)
> **This file is the plan AND the report.** PM writes `## Scope` … `## Acceptance criteria`;
> ops fills `## Results`, `## Evidence`, `## Findings and handoff`, `## Not verified`,
> `## Completion recommendation` with what actually happened.

## Scope

- **Workflow / plan:** `e2e-23191782-love-items-dual-route` — an independent E2E verification
  workflow (`mstar-e2e`), not an iteration phase, not a development plan, not a QA gate.
  Scenarios A0–D4 below are the workflow's plan rows. It changes no product code.

- **User authorization and permitted side effects.** Direct operator request 2026-09-30:
  *"计划对'BV1Y7M4zNEfF,BV1vNTqzFEve,BV1zz5zzFENq,BV1BdtazGEBE'这4个视频在
  chosenecho@192.168.3.21的wsl中进行e2e测试"*. Three scope questions were put to the operator
  and answered the same day: (1) route = **both** — subtitle-first route and the forced
  audio→ASR route, in two independent roots; (2) build = **do not introduce the pad's 4
  unpushed commits** — run on the fetched `origin/main`; (3) roots = **state on the local disk,
  products on `/mnt/e`**.
  **Permitted:** read and run the product from a detached checkout of `ed291be` on the target
  host; create fresh archive roots and artifact roots under the two named bases; bounded
  metadata enumeration for UID 23191782 (pages 5–6 only); subtitle acquisition for the four
  named parts both with and without the session credential; audio download for the four parts;
  GPU transcription on the target's AMD GPU; read the working session cookie from its existing
  location *by path only*; write logs under the run's log dir.
  **Not permitted and not to be done:** any product-code change on the target for the run itself;
  production/deployment change; destructive cleanup outside the named roots; moving
  `refs/heads/main` on the target; media redistribution; the project's full local test suite (not
  authorized — this run supplies its own evidence); any write to a previously published
  artifact root.

- **Target build / ref.** `ed291be` (= `origin/main` = `ed291be76b88fb72f940b3284b3a179f50ca56b3`).
  **No bundle is needed:** `ed291be` already exists intact on the target as a fetched ref
  (verified: `git cat-file -t ed291be` = `commit`; `3b561ea` is its ancestor; the local commit
  `d41c257` sits on `main`, which will **not** be moved).
  **Mechanism deviation from the answered option, and why it is strictly safer:** the operator
  chose "advance to `origin/main`, do not introduce the pad's unpushed commits". A
  `merge --ff-only` is *impossible* here — `main` holds the local-only commit `d41c257`, so
  `d41c257` is not an ancestor of `ed291be` and a fast-forward is refused by construction. The
  run therefore realizes the same intent with **`git worktree add --detach <path> ed291be`**,
  which leaves `refs/heads/main`, `d41c257`, the tracked working tree and its uncommitted delta
  **byte-identical and untouched**. This is a change of mechanism, not of the authorized
  outcome: no commit is discarded, nothing is reset, nothing is reflog-only.
  **The uncommitted delta and `d41c257` are not inputs to this run.** They are recorded (B0) as
  pre-existing target state so the report is honest about what the checkout contained.

- **Actual environment / device / session.** Target WSL2 `DESKTOP-HHFROLO` on the Windows compute
  box (192.168.3.21), Ubuntu 24.04.1, 12 cores, 24 GB RAM, AMD Radeon RX 7800 XT `gfx1101`
  (15.8 GB), torch `2.9.1+rocm7.2.0.git7e1940d4` (hip `7.2.26015-fc0010cf6a`), ffmpeg 6.1.1.
  **The GPU gate needs `HSA_ENABLE_DXG_DETECTION=1` exported** — measured again this round: bare
  `check-asr-env` → exit 1 (`dxg-detection FAIL … HSA_ENABLE_DXG_DETECTION=unset`,
  `device-probe FAIL`); same command with the variable → exit 0 naming the RX 7800 XT / `gfx1101`
  (residual `e2e-23191782-subtitle-publish-webdav · R1`, still open).
  **Interpreter / entry point: the product's own `.venv`, not `/root/gpu-venv`.** Measured this
  round: `/root/gpu-venv` is **missing `accelerate`**, which `ed291be`'s Qwen3 engine requires for
  its `device_map=` load path (`asr.py:886-893`) — the recorded entry point of the two previous
  E2E runs cannot load this engine. `<product>/.venv/bin/python` has `accelerate 1.15.0`, the
  same ROCm torch, and `torch.cuda.is_available() == True` naming the RX 7800 XT. A0 records both
  and asserts which one the run used.
  **Import path is pinned, never inherited.** The editable install in both venvs resolves
  `bili_asr` to the **primary checkout** (`/root/workspace/bilibili-asr-archive/bilibili-asr-archive/src`),
  so an unpinned run would grade the wrong tree while appearing to grade the worktree
  (`{KNOWLEDGE_DIR}/testing-patterns/worktree-test-invocation.md`). Every product invocation in
  this run therefore sets `PYTHONPATH` to the detached worktree's `src` and A0 prints the
  resolved `bili_asr.__file__`.

- **Roots (all on the target host):**
  | Role | Path | Access |
  |---|---|---|
  | build (detached `ed291be` worktree) | `/root/e2e-asr/love-dual-route/build` | create; read |
  | route-1 archive root (state, local disk, **fresh**) | `/root/e2e-asr/love-dual-route/route1` | read/write, created empty |
  | route-1 artifact root (products) | `/mnt/e/bili-e2e/love-dual-route/route1` | read/write, create first |
  | route-2 archive root (state, local disk, **fresh**) | `/root/e2e-asr/love-dual-route/route2` | read/write, created empty |
  | route-2 artifact root (products) | `/mnt/e/bili-e2e/love-dual-route/route2` | read/write, create first |
  | pre-run rescue ledger | `/root/e2e-asr/love-dual-route/pre-run/` | create |
  | logs | `/root/e2e-asr/love-dual-route/logs/<UTC-stamp>/` | create |
  | **`/mnt/123pan`** | — | **unusable — do not touch.** Retired 2026-09-28; re-measured this round: mounted `fuse.rclone` but `ls` → `Input/output error`, `rclone lsd 123pan:` → `401 Unauthorized` |

- **The four items** (UID 23191782, all single-part `:p0`, **16 192 s ≈ 4.50 h** of audio):

  | `work_id` | duration | cid | published | title |
  |---|---|---|---|---|
  | `BV1BdtazGEBE:p0` | 6395 s (106:35) | 31594841414 | 2025-08-10 | 【哲学与现实】爱情升级指南——当你说"我爱你"时，你到底在怎说什么 |
  | `BV1vNTqzFEve:p0` | 5112 s (85:12) | 30412768784 | 2025-06-10 | 【爱欲经济学】爱情的阶次和解放 |
  | `BV1Y7M4zNEfF:p0` | 2598 s (43:18) | 30506419561 | 2025-06-15 | 【行动指南】从爱情走向革命 |
  | `BV1zz5zzFENq:p0` | 2087 s (34:47) | 29471998505 | 2025-04-18 | 【历史唯物主义】革命与爱情 |

  Selection provenance: these are the four most recent entries of the 12 title-matched
  `爱情` videos collected this session (`.tmp/up-videos-all.json`, 1730 rows; API keyword
  intersection 12 / symmetrical difference empty). **Page positions are index-derived and
  therefore a premise, not a fact:** the snapshot's newest-first ordering puts `BV1BdtazGEBE` at
  page 5 and the other three at page 6, so A2/B1 enumerate **pages 5–6** and assert the four
  `work_id`s are present. A live re-confirmation attempt this round was refused by upstream
  (`-352 风控校验失败` on the user-video page call), which is itself recorded evidence; the
  enumeration in A2/B1 is where the position claim is earned or falsified.

### Locked premise: which route each root can reach, and exactly why (code-derived)

The queue is the store's own relation, not a flag. `v_missing_audio` requires **all** of:
`processing_status <> 'gone'` **and** no `transcripts` row **and** the newest caption attempt's
outcome ∈ `('no-subtitle', 'failed')` **and** no `part_audio_objects` row
(`schema-transcripts.sql:185-223`). `v_missing_transcript` requires audio evidence and no
transcript (`:228-243`).

Therefore, with a working credential, a part that acquires its AI caption becomes
**permanently ineligible** for the audio queue — the "subtitles first" branch is not a
preference, it is the only reachable route. Verified live this round against the four parts:

    BV1Y7M4zNEfF cid=30506419561 tracks=[('ai-zh', True)]
    BV1vNTqzFEve cid=30412768784 tracks=[('ai-zh', True)]
    BV1zz5zzFENq cid=29471998505 tracks=[('ai-zh', True)]
    BV1BdtazGEBE cid=31594841414 tracks=[('ai-zh', True), ('ai-en', True), ('ai-ja', True),
                                          ('ai-es', True), ('ai-ar', True), ('ai-pt', True)]
    (control, same credential) BV1vVDKBvEqL / BV1iMGL6KE9J → [('ai-zh', True)]

  and with **no** credential in effect the same call returns an empty inventory for the same
  parts — the switch is the credential, not the item.

So the two roots diverge on exactly one input:

- **Route 1 (subtitle-first, credential present).** `harvest-subs` stores the `ai-zh` transcript
  → `publish-transcripts` emits the four artifact families + marker. The audio branch is
  **correctly unreachable** here, and A6 asserts that as an invariant — with a negative control.
- **Route 2 (forced audio→ASR, caption route exhausted *without* changing any product code).**
  `harvest-subs --sessdata ""` runs the documented anonymous path
  (`config.py:128-141`: an explicitly blank flag forces anonymous and never falls through to the
  environment), the gateway returns an empty inventory, and the ingestor records the **valid,
  in-contract** `no-subtitle` outcome (`subtitle_ingest.py:_record_captionless_part`;
  `acquisition_attempts` CHECK admits `no-subtitle` with a NULL `error_code`). That is what
  admits the part to `v_missing_audio`. Then `download-audio` → `asr` run on the GPU.
  **This is the shipped design, not an override:** no flag is forced, no row is hand-written, no
  file is rewritten, and the run takes its own determinism from the anonymous attempt it made.

### Assigned scenarios

| ID | Scenario | Expected |
|---|---|---|
| **A0** | Build identity, host gate, and import pinning | Worktree created detached at `ed291be`; `git log --oneline -1` names it; `git status --porcelain` inside the worktree is empty; **both** venvs recorded with `accelerate` presence (`gpu-venv` **MISSING**, product `.venv` present); `torch.cuda.is_available()` + device name recorded per venv; bare `check-asr-env` → exit 1 and with `HSA_ENABLE_DXG_DETECTION=1` → exit 0 naming gfx1101; **the pinned `PYTHONPATH` resolves `bili_asr.__file__` to the worktree's `src`**, printed, not assumed; `--version`, the parsed subcommand count, and the checkpoint paths + a weight-file listing recorded |
| **A1** | Non-destructive preservation of the pre-existing target state | `refs/heads/main` still equals `d41c257` (recorded before **and** after); the uncommitted `asr.py` delta saved as a patch file with `sha256` **before** the worktree is created; `git -C <primary> status --porcelain` unchanged across the whole run; **no `reset`, no `checkout --force`, no `stash`, no branch move** — the `reflog` tail is recorded and shows no new `reset`/`merge` entry |
| **A2** | Route-1 fresh root bootstrap | `fetch-meta --mid 23191782 --start-page 5 --limit-pages 2 --archive-root <route1>` exits 0 (a bounded retry ladder is permitted and every attempt is recorded verbatim, including failures — the prior run measured the first invocation exiting 2 on `rate_limited`); `archive.db` exists; **all four `work_id`s present with a positive `duration_s`**; a second `--resume` invocation is resumable; `status` counters recorded |
| **A3** | Route-1 caption admission probe (read-only) | `probe-subs --bvid <bvid>:p0` per item with the credential → each lists `ai-zh` (AI); `candidates=`/`failed=` counters recorded; the command writes nothing (no new file below the archive root, asserted by a before/after file-set comparison) |
| **A4** | Route-1 subtitle acquisition | `harvest-subs --bvid <bvid>:p0` per item, each exit 0 with a **determinate** outcome (`stored` expected); four stored transcripts, each with `source_kind=subtitle-ai`, `language=ai-zh`, `version`, `content_sha256`, and **segment count > 0**; `v_missing_subtitle` decreases by 4; per-item and total timings |
| **A5** | Route-1 publication to the product base | `publish-transcripts --archive-root <route1> --artifact-root </mnt/e/…/route1>` exits 0 with `published=4` (or the actual counters, recorded); the **four artifact families (`raw`/`txt`/`md`/`srt`) plus the `.bundle-ready` marker** land under the `/mnt/e` artifact root with byte sizes and `sha256`; one archived manifest row per publication; **state stays local** — `archive.db`, `manifest/`, `coordinator/` present under the local archive root and absent under the artifact root |
| **A6** | Route-1 branch invariant, with a negative control | After A4/A5 the four parts are **absent** from both `v_missing_audio` and `v_missing_transcript` (they hold a transcript), asserted as a **whole-view equality**, not a filtered absence. **Negative control, same run:** a hand-written `no-subtitle` attempt row on **one additional enumerated part that holds no transcript** must move that part **into** `v_missing_audio` — proving the view's producer is reachable from this fixture and that the absence above is a live decision rather than a tautology (`{KNOWLEDGE_DIR}/testing-patterns/absence-assertion-negative-control.md`). The control's row is written to the **route-1 store only** and is disclosed as a deliberate fixture |
| **A7** | Route-1 archive evidence | `verify --trusted-local --scope <bvid>:p0` per item + `coverage --quality --scope <bvid>:p0` per item: actual `defect_count`, actual exit codes, actual reason codes recorded; the four families are mutually consistent per row and each bundle's recorded `sha256` recomputes from the on-disk bytes; `search` returns text from at least one route-1 row |
| **B0** | Pre-existing target state, recorded (no writes) | `d41c257` present on `main`; its subject/scope recorded verbatim; the uncommitted delta's stat (**only** `bilibili-asr-archive/src/bili_asr/asr.py`, +60/−1) and its key lines recorded; the delta's *content* judged against `ed291be` and stated as superseded-by-upstream **only if the evidence shows it**; `?? .env.bak-20260917-181947` recorded. **This is a read of target state, not a repair** |
| **B1** | Route-2 fresh root bootstrap + live page-position confirmation | `fetch-meta … --start-page 5 --limit-pages 2 --archive-root <route2>` exits 0 under the same bounded-retry discipline; the four `work_id`s present with positive `duration_s` (this **earns or falsifies** the index-derived page claim); `derive-manifest` **is not run** (it is inert on this build and is the subject of a separately registered plan); the store is recorded as `transcripts = 0` |
| **B2** | The credential switch, isolated and controlled | On route 2: (i) `probe-subs --bvid <bvid>:p0` **with** the credential lists `ai-zh`; (ii) the same command with **`--sessdata ""`** lists nothing (empty inventory) — same host, same store, same item, only the credential differs; (iii) `harvest-subs --bvid <bvid>:p0 --sessdata ""` per item exits **0** and records `no-subtitle` for each (the outcome is **determinate**, not a failure); (iv) `transcripts` count is still **0**. The pair (i)/(ii) is the control that makes the switch attributable to the credential rather than to the item or the network |
| **B3** | Route-2 queue admission — the locked premise, asserted before any audio work | All four parts present in **`v_missing_audio`** with `status: needs_audio` and a **positive integer `duration_s`**; the full admitted set and its count recorded; `v_missing_transcript` empty for the four (no audio evidence yet). **If any of the four is not admitted, the premise is wrong: stop, and B4–B7 are `blocked` — never worked around** |
| **B4** | Route-2 audio acquisition to the product base | `download-audio --missing-subs --bvid <bvid>:p0 --archive-root <route2> --artifact-root </mnt/e/…/route2>` per item, each exit 0; every row reaches `audio_ok`; each audio object present **under the `/mnt/e` artifact root** with a byte size and `sha256`; per-item and total bytes and wall timings; state stays local |
| **B5** | Route-2 transcription on the GPU | `asr --bvid <bvid>:p0 --archive-root <route2> --artifact-root </mnt/e/…/route2>` per item with `HSA_ENABLE_DXG_DETECTION=1`, each exit 0; every row `archived`; the store's `part_audio_objects` still present and no `transcripts` row created (**expected** on this build — see B7); four families + `.bundle-ready` under the artifact root; per-row segment/cue counts > 0; the **producer identity as actually recorded** (`asr_model_name`, `asr_device`, aligner, VAD fields) read from the md frontmatter / raw sidecar; per-item and total GPU wall time with the run's own `rtf`; `BILI_ASR_DEVICE=cuda` confirmed |
| **B6** | Route-2 archive evidence | `verify --trusted-local --scope <bvid>:p0` and `coverage --quality --scope <bvid>:p0` per item: actual `defect_count`, actual diagnostics, actual exit codes, actual reason codes; four-family mutual consistency and `sha256` recomputation per row |
| **B7** | **Convergence probe: does the transcript queue drain?** | After B5, query `v_missing_transcript` for the four parts and `v_part_pipeline` for their rendered state. Recorded either way as a **finding, not a run failure**: the documented expectation, derived from the code, is that the part **remains** in `v_missing_transcript`, because the ASR path writes disk artifacts and a manifest row and **no `transcripts` row** (`ALLOWED_CAPTION_SOURCE_KINDS` excludes `asr-local`; the `asr-local` reservation has no writer). B5's rows and this probe together are the evidence the separately registered plan `20260929-asr-local-transcript-storage` cites. **No product change is made to make this pass** |
| **C0** | Cross-route comparison for the same four items | For each item, compare the route-1 AI caption against the route-2 ASR transcript: N1 character counts, `coverage --reference` result where the size floor permits (the prior run measured a refusal on the two longest items — record the actual), cue counts and mean cue duration, and the ASR/AI segmentation ratio. **The reference side is named.** `HSA_ENABLE_DXG_DETECTION` is irrelevant here (no GPU path) |
| **C1** | Artifact-root boundary behaviour on `/mnt/e` (drvfs, not FUSE) | Recorded with commands and timings: (i) whether an **absent** audio directory is distinguished from a **measured-empty** one, or fails open; (ii) whether the boundary validation probes a write and a directory `fsync`, or only opens the root; (iii) that a **relative** recorded path resolves under the configured base and the products are not shadowed by a legacy copy. Each answer is a finding regardless of direction; a raw error is a legitimate observed result. The prior run answered the same three questions for the retired WebDAV mount — this run answers them for drvfs and states whether the answer differs |
| **C2** | Reader agreement and source identity | `export --format json --status archived` and `search`/`search-index` on both roots: record whether the ASR rows carry `source`/`language` (the prior run measured that they **do not**, while caption rows do — re-test, do not inherit), and whether `search --source …` filters on what the index actually holds. Reader agreement is a pair property; record both readers' candidate sets |
| **D0** | Credential hygiene | Every log, report and store row is scanned for the session cookie value; the credential is referenced **by path only**; `credential_present` column values recorded as booleans. Assert **zero** occurrences of the cookie in the run's logs and in this report |
| **D1** | Stale-credential trap, recorded | `/root/.bili-sessdata` measured `nav → code -101, isLogin False`, while `/root/.config/bili-asr/session.env` and the checkout `.env` both measure `code 0, isLogin True` (`uname` recorded). Both states recorded as a **target-environment finding**; no credential file is modified |
| **D2** | Upstream risk-control reality, recorded | Every refusal met during the run is recorded verbatim with its code (`-412`, `-352`, `-799`, `rate_limited`), the attempt count, and the backoff used — including the `-352` measured during scoping. A scenario that needed a retry ladder states the ladder's outcome |
| **D3** | Scope-fidelity audit | For every scenario, state whether the operator's three answers were honoured: no pad-unpushed commit introduced (assert `ed291be` == the tip actually run); no product-code change (assert the worktree's `porcelain` is empty at the **end** of the run, not only at the start); no branch moved; `/mnt/123pan` untouched; nothing written outside the named roots. Any deviation is reported as a deviation |
| **D4** | Re-run safety — the tool's core promise, bounded | Four **cheap** re-invocations, each recorded with its exit code and printed counters, **none of which re-spends the GPU**: (i) route 1, `harvest-subs --bvid <bvid>:p0` again → expect the documented `unchanged` outcome (content-hash idempotency / version-append), recording which outcome actually appears; (ii) route 1, `publish-transcripts` again → expect `already_published` for the four, because "a complete published bundle is never replaced" is a documented guarantee and a silent overwrite would be a finding; (iii) route 2, `download-audio --missing-subs --bvid <shortest item>:p0` again → record whether it reports the queue empty or re-downloads, and the audio tree's byte total before/after; (iv) route 2, read the store's own view of what a re-run would select (this is the **cost** question: the ASR stage on this build leaves the part in `v_missing_transcript`, so a naive re-run would re-spend the GPU). **The ASR stage is deliberately NOT re-run** — that cost is not authorized by this scope, and (iv) answers the question from the store instead. Each of the four is a finding either way; a re-run that silently re-does expensive work is the most valuable thing this scenario can surface |

Outcome vocabulary is exactly `passed` / `failed` / `not-run` / `blocked`. A scenario with no
determinate evidence is `not-run` or `blocked` — never a claimed pass. A **failed product
scenario is still a completed verification run.**

## Acceptance criteria

1. Every scenario A0–D4 carries exactly one of the four outcomes, each with a command, an exit
   code, and an artifact/byte-level pointer. `passed` requires the expected value to have been
   **observed**, not inferred.
2. No scenario claims a pass from a stale, reused or inferred fact. Where this run re-tests
   something a previous run measured, both the previous measurement and this run's are shown and
   the report says which is which.
3. `D3`'s four no-go assertions are demonstrated by before/after evidence, not by intent.
4. Findings are separated from failures: a real product defect is registered as a finding with a
   reproduction and a bounded owner; a failed scenario caused by an upstream refusal, an absent
   prerequisite, or a wrong premise in this plan is reported as such and **not** folded into a
   product verdict.
5. The run's own scope errors are disclosed in the report, in the executor's own voice — as the
   two previous E2E reports did.

## Estimated cost (agent-oriented)

| Stage | Basis | Estimate |
|---|---|---|
| A0–A1 (build, gates, rescue) | ssh round-trips | ~8 min |
| A2–A7 (route 1) | 2 metadata pages + 4 caption acquisitions + 4 publications; upstream risk ladder dominates | ~15–25 min |
| B1–B3 (route 2 bootstrap, control, admission) | 2 metadata pages + 8 subtitle calls | ~10–15 min |
| B4 (audio) | 16 192 s of audio; prior run measured ~90 MB for a comparable span on a healthy link | ~5 min |
| B5 (ASR) | **measured** `rtf 0.17–0.18` on this host (`results-gpu.jsonl`, 2026-09-26) → 16 192 s × 0.18 ≈ 2 915 s, + model/aligner load | ~50–70 min |
| B6–D4 (evidence, comparison, audits) | reads + a few local compares | ~20 min |
| **Total** | | **~1.8–2.4 h wall**, dominated by B5 |

The ASR estimate is extrapolated from a measured `rtf` on *different* audio of similar shape
(single-speaker lecture) and is stated as an extrapolation, not a measurement. One model
construction is reused across the four rows if they run in a single invocation; running four
separate invocations pays the load four times and is budgeted as such. If the observed `rtf`
exceeds `0.5`, the engine's own time guard applies and the run reports it rather than
compensating.

## Risks and mitigations (stated before execution)

| Risk | Mitigation, decided now |
|---|---|
| Upstream risk control refuses the enumeration or the caption calls (`-412` / `-352` / `-799`) | Bounded retry ladder with recorded backoff; a ladder that never succeeds makes its dependent scenarios `blocked` with the code named — never a silent pass |
| The page positions (5–6) are wrong, so the bootstrap never sees the four items | A2/B1 assert the four `work_id`s. If absent, the pages are widened as a **recorded deviation** before any dependent scenario runs |
| `--sessdata ""` does not in fact produce an empty inventory | B2 (ii) measures it. If it lists tracks, the audio route is **unreachable without a product change**, and B3–B7 become `blocked` with that finding — the run stops rather than forcing a queue row |
| The 4 separate ASR invocations pay 4 model loads and blow the budget | Run them in one invocation with `--bvid` selectors if the CLI admits it, else accept the load cost and record both; the fallback is decided by the CLI's actual surface, measured in A0 |
| A model checkpoint is incomplete or unreachable | A0 records the checkpoint paths and a weight listing; `BILI_ASR_MODEL`/`BILI_ASR_ALIGNER_MODEL` point at the existing local checkpoints so the run never needs the network. A load failure makes B5 `failed` with the engine's message, not a retry storm |
| The negative control in A6 is itself the thing that breaks | The control uses a **separate** enumerated part with no transcript, its own attempt row, and is disclosed as a deliberate fixture; it cannot make a real difference invisible, and its outcome is reported either way |
| drvfs is slow or flaky for the products base | C1 measures the boundary behaviour; `/mnt/e` was re-verified writable this round (`WRITE_OK`, 1.3 TB free, measured ~94 MB/s write / ~332 MB/s read in a prior round). If it degrades mid-run, the affected scenarios report the raw error as an observed result |

## Entry gate

Execution starts only on the operator's GO. It begins with A0+A1+B0+A2 and **stops for a
checkpoint report** before B5, so the ~1-hour GPU stage is not spent on a route that A2/B3 have
not already admitted.

---

# EXECUTION LOG — checkpoint round 1 (2026-09-30)

Executed by `ops-engineer` on 2026-09-30, target host `DESKTOP-HHFROLO` (192.168.3.21, WSL2).
Every command ran as
`ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes -o ConnectTimeout=10 chosenecho@192.168.3.21 "wsl -e bash -s"`
with the script on stdin; the credential was loaded with
`set -a; . /root/.config/bili-asr/session.env; set +a` and never printed or recorded.

**Run directories (target host):** build `/root/e2e-asr/love-dual-route/build`;
logs `/root/e2e-asr/love-dual-route/logs/20260930T064056Z/`;
pre-run ledger `/root/e2e-asr/love-dual-route/pre-run/`.

## Results — checkpoint round 1

| Scenario | Expected | Actual | Outcome | Evidence |
|---|---|---|---|---|
| **A0** | Worktree detached at `ed291be`; both venvs recorded; bare `check-asr-env` exit 1, with `HSA_ENABLE_DXG_DETECTION=1` exit 0; `PYTHONPATH` pin proven | **passed.** `git worktree add --detach` → `HEAD is now at ed291be`; `rev-parse HEAD` = `ed291be76b88fb72f940b3284b3a179f50ca56b3`; `symbolic-ref` → `DETACHED`; `PORCELAIN_LINES=0`. Entry points: `/root/gpu-venv` → `accelerate MISSING`, torch `2.9.1+rocm7.2.0.git7e1940d4`, `cuda_avail False` **bare** / `True AMD Radeon RX 7800 XT` **with DXG**; product `.venv` → `accelerate 1.15.0`, same torch, same two DXG states. `check-asr-env` bare **exit 1** (`dxg-detection FAIL`, `device-probe FAIL`), with the variable **exit 0** (`device ok … arch=gfx1101 vram_gb=15.8`, `asr-env: verified`). Pinning: unpinned resolves `/root/workspace/bilibili-asr-archive/bilibili-asr-archive/src/bili_asr/__init__.py`; `PYTHONPATH=<worktree>/src` resolves `<worktree>/bilibili-asr-archive/src/bili_asr/__init__.py`. `--version` = `bili-asr 0.1.0`; subcommand count **24** | **passed** | `a0-build-identity.txt`, `a0-check-env-bare.log`, `a0-check-env-dxg.log`, `a0-entry-points-with-dxg.log`, `a0-import-pinning.log`, `a0-cli-surface.log`, `a0-host-facts.log` |
| **A1** | `refs/heads/main` unchanged; delta saved with `sha256`; `porcelain` unchanged; no `reset`/`checkout --force`/`stash` | **passed.** `main` = `d41c2572e27c116fb422f4be93927f0e71b422e3` both before **and** after. Delta saved twice: `uncommitted-asr-py.delta.patch` (4 596 B, `sha256 7fcb056a…`) and a byte copy `asr.py.working-copy` (`sha256 cf535810…`), which equals the still-present working file's `sha256` **exactly**. `porcelain` before = after = ` M …/asr.py` + `?? .env.bak-20260917-181947`. Reflog top entry still `d41c257 HEAD@{0}: commit:` — **no new `reset`/`merge`/`checkout --force`/`stash` entry**. Rescue ref created, nothing deleted: `rescue/d41c257-librosa-m4a d41c257` | **passed** | `a1-pre-state.txt`, `a1-delta.sha256`, `a1-rescue-ref.txt`, `a1-post-state.txt`, `uncommitted-asr-py.delta.patch`, `asr.py.working-copy` |
| **B0** | Pre-existing state recorded; delta judged against `ed291be`, claim only what evidence shows | **passed (read-only).** `d41c257` = `d41c2572e27c116fb422f4be93927f0e71b422e3`, 2026-09-26 10:38:33 +0800, author `measurement`, subject `fix(asr): read the .m4a/AAC the archive's own downloader writes`. Only commit on `main` not in `ed291be`. Untracked `?? .env.bak-20260917-181947`. `ed291be` **is already `origin/main`** and was already present on the target as a fetched ref — **no bundle transfer was needed**, and none was performed | **passed** | `b0-pre-state.txt`, `a1-pre-state.txt` |
| **A2** | `fetch-meta --start-page 5 --limit-pages 2` exits 0; all four `work_id`s present with positive `duration_s`; resumable; counters recorded | **failed — 2 of 4 present, and the cause is a product defect, not risk control.** First invocation: page 5 `ok` (30 videos / 30 parts), page 6 `risk_interrupted`/`rate_limited`, exit 2. A 5-attempt ladder then a 12-attempt widened ladder (one page per invocation, 20–80 s pacing) **never landed page 6**: 12/12 invocations exit 2. **Store after all attempts: `videos=30`, `transcripts=0`, `v_missing_subtitle=30`.** Present: `BV1BdtazGEBE:p0` (cid 31594841414, 6 395 000 ms), `BV1Y7M4zNEfF:p0` (cid 30506419561, 2 598 000 ms). **Absent: `BV1vNTqzFEve:p0`, `BV1zz5zzFENq:p0`.** Ingestion outcomes show page 6 failing **13× `failed`/`shape_error`** alongside 19× `risk_interrupted`/`rate_limited` — two distinct classes, and the `shape_error` class is the real blocker. Cursor `next_page=6, state=ready` (resume-safe), `observed_total` **1 691** (was 1 739 at the 2026-09-25 enumeration) | **failed** | `a2-fetch-meta.log`, `a2b-widen.log`, `a2c-widen.log`, `a2-store.log`, `a2-diag.log` |
| **A3–A7** | Route-1 caption/publish/verify chain | **not-run.** Dependent on A2 enumerating the four items; only 2 of 4 are in the store, so the chain would have covered half the ordered set. Per the plan's own risk clause, this is recorded rather than narrowed silently | **not-run** | — |
| **B1–B7, C0–C2, D0–D4** | route 2 and the cross-cutting audits | **not-run** (checkpoint round 1; B5's ~1 h GPU stage is deliberately not spent while the admission premise is unproven) | **not-run** | — |

**Checkpoint counts: assigned 24 · passed 3 (A0, A1, B0) · failed 1 (A2) · not-run 20 · blocked 0.**

**The GPU stage was NOT started** — deliberately, per the entry gate: route 2's admission premise
(audio queue entry) is downstream of the same enumeration that A2 just failed, so spending the
ASR hour would have graded an unproven premise.

## Evidence — the A2 root cause, isolated

The `shape_error` class is not risk control. It is deterministic and reproducible, and it is a
**product defect**. Diagnostic chain, all on the target host under the pinned `PYTHONPATH`:

**E-1 — page position ground truth (the plan's premise, earned).** The `recArchivesByKeywords`
endpoint (a different endpoint from the one `fetch-meta` uses) enumerated pages 4–7 with a live
credential:

    recArchives pn=4 total=1739 n=30 hits=[]
    recArchives pn=5 total=1739 n=29 hits=['BV1BdtazGEBE']
    recArchives pn=6 total=1739 n=29 hits=['BV1Y7M4zNEfF','BV1vNTqzFEve','BV1zz5zzFENq']
    recArchives pn=7 total=1739 n=27 hits=[]

So the plan's page estimate (page 5 = `BV1BdtazGEBE`, page 6 = the other three) was **correct**.
The scenario failed on the shipped endpoint, not on the premise. Evidence: `a2-position-probe.log`.

**E-2 — the two failure classes are distinct, and page 1 is healthy.** Same live credential, same
host, shipped gateway:

    gateway pn=1 OK n=30 total=None
    gateway pn=6 GatewayShapeError: GatewayShapeError(shape_error): video item is not normalizable

Page 1 succeeds while page 6 fails, so this is neither an endpoint-wide block nor a credential
problem. Evidence: `a2-endpoint.log`.

**E-3 — the offending item and the offending field.** Fetching page 6 raw and normalizing each
item individually:

    30 items on page 6
    ITEM 27 FAILS: GatewayShapeError(shape_error): video item is not normalizable
       bvid  = 'BV18b9DYeE3s'
       title = '【随便聊聊】何为抑郁，怎样不抑郁'
       mid   = 23191782 (matches)
       author= '未明子'
       pubdate = None    created = 1741387364
    normalizable bvids: 29 of 30

and the field-level probe:

    pic   : OK
    desc  : REJECTED ValueError: desc contains invalid control characters
            value='理解抑郁以及拒绝抑郁的方法，不代表就【能】不抑郁。\n抑郁本身是器质性的，该吃药吃药，该入院入院。'
    tid   : OK
    aid   : OK
    title : OK
    author: OK
    === the real reader path ===
    REJECTED: ValueError: desc contains invalid control characters

**The field is `description`, and the character is `\n` (0x0a).** Evidence:
`a2-item-diagnosis.log`, `a2-item-field-level.log`.

**E-4 — the blast radius is not one item.** Scanning pages 2–6 for items whose text fields carry
a control character, and counting DTO failures per page:

    pn=2: items=30 DTO_ok=30 DTO_fail=0 control_char_items=0
    pn=3: items=30 DTO_ok=27 DTO_fail=3 control_char_items=3
         BV1DJB5BJEAY created=1766569646 fields={'description': ['0xa']}
         BV1RDSTBNEMo created=1764320400 fields={'description': ['0xa']}
         BV1KBCMBrEaL created=1763110800 fields={'description': ['0xa']}
    pn=4: items=30 DTO_ok=30 DTO_fail=0 control_char_items=0
    pn=5: items=30 DTO_ok=30 DTO_fail=0 control_char_items=0

At least **4 affected items across 2 of the sampled pages**, all via multi-line `description`.
Evidence: `a2-blast-radius.log`.

**E-5 — no shipped path can work around it.** No command ingests a single video's metadata by
`bvid`: the `--bvid` selectors that exist belong to `asr` / `download-audio` / `harvest-subs` /
`probe-subs` / `publish-transcripts`, all of which require the part to be **already in the store**
(`list_selected_parts` / the gap views). The single-video gateway method
`get_completed_video_summary` only *completes* an already-normalized `VideoSummary` and is not
reachable from any CLI. So a part on an affected page cannot enter the store at all. Evidence:
`a2-minimal-tail.log`.

**E-6 — the defect is on the current shipping build, not an artifact of this run.**
`bilibili-asr-archive/src/bili_asr/sources/models.py:109-113` on `ed291be` (= `origin/main`):

```python
        if self.pic is not None:
            _text(self.pic, "pic")
        if self.desc is not None:
            _text(self.desc, "desc")
```

and `_text` (`models.py:41-42`) rejects `\x00`, `\r` and `\n`. The same code is present on pad
`main` (`68770b1`). `git blame` places the `desc` line at `cefed49` (2026-09-28). The page-level
fan-out is at `bilibili_api_gateway.py:282`, where `_normalize_user_video_page` normalizes all
items in one comprehension — **one bad item raises out of the whole page**.

## Findings and handoff

### F1 (P1, product defect — pre-registered as `R6`) — a multi-line `description` makes an entire page un-enumerable

- **Impact:** `fetch-meta` can never enumerate past any page containing a video whose
  `description` carries `\n` / `\r` / `\x00`. Because the cursor refuses to advance past a failed
  page, **the enumeration is permanently wedged at the first affected page** — not a transient
  failure, and not recoverable by retry. Measured here: page 6 blocked 13/13 attempts across two
  ladders; page 3 carries 3 further affected items. The archive cannot reach full coverage while
  this holds, and the previously recorded `observed_total` delta (1 739 → 1 691) is a separate
  observation that also needs explaining.
- **Reproduction (bounded, on the target):** with a live credential, fetch page 6 through the
  shipped gateway and normalize item `BV18b9DYeE3s`; or directly:
  `VideoSummary(bvid="BV18b9DYeE3s", aid=..., title="…", pubdate=..., mid=23191782, desc="…\n…")`
  → `ValueError: desc contains invalid control characters`.
- **The design question the code has to answer (not mine to decide):** `description` is *not* an
  operator-facing one-line field the way `title`/`author` are — the `_text` docstring's own
  justification is that these values are "printed verbatim, one line per record". A multi-line
  video description is normal upstream data, and the `transcripts` side already has the
  answer for exactly this: `_caption_text` deliberately **keeps** control characters because
  "rejecting `\\n` here would turn a real caption into a document-level shape error". The same
  argument applies verbatim to `desc`. Two candidate shapes: (a) normalize `desc` at the boundary
  (collapse/keep the newline and relax the validator for this field), or (b) treat `desc` as
  absent when it carries control characters — the ingestor already counts an observation by
  whether the field holds anything, so dropping is representable and loses no typed field.
  **A third, orthogonal question:** whether one un-normalizable item should be able to fail a
  whole page at all, or whether the page should degrade to partial with a recorded per-item
  error. Both are product decisions with different claim-scope consequences.
- **Owner / bounded follow-up:** a `development` plan (owner: `fullstack-dev` + a
  `code-reviewer` seat; `bilibili-asr-archive/src/bili_asr/sources/models.py` and the page
  normalizer in `bilibili_api_gateway.py` are the touched files). The repair must carry a fixture
  whose producer can actually reach the failure — i.e. a page fixture containing a multi-line
  `description` — and the page-level fan-out needs its own decision either way
  (`{KNOWLEDGE_DIR}/testing-patterns/absence-assertion-negative-control.md`: a test whose fixture
  cannot reach the falsifier is documentation, not verification).
- **This workflow does not repair it.** A product-code change on the target is explicitly outside
  this run's authorization.
- **F1 is NOT a new finding — it was already registered, and this report was wrong to imply
  otherwise.** On re-reading the register, the same defect is **`20260926-video-metadata-enrichment
  · R6`** (severity `medium`, `decision: defer`, owner `@project-manager`, `registered_at`
  2026-09-28), whose own text reads: *"A multi-line upstream `description` would raise
  `GatewayShapeError` from `_text` (it rejects `\n`/`\r`) and therefore fail the WHOLE page … but
  unruled: either the boundary should normalise newlines the way caption text does, or the
  terminal-on-malformed choice is accepted and pinned. **Needs a decision, not a guess.**"* The
  sibling class **`M-R2`** (the tag endpoint failing the whole page+run) is registered in the same
  bucket and still `open`.
  **What this E2E adds is the measurement R6 lacked**, not the defect: a live 4-item run blocking
  **13/13** attempts, the cause located at a specific line and field, the blast radius measured at
  **4 items across 2 of 5 sampled pages**, and `desc` proven to have **zero readers** in the whole
  `src` tree — which is what makes the ruling decidable rather than a coin toss.
  **A correction to this report's own earlier claim:** the `## Findings` heading originally implied
  a fresh discovery. It is not. An earlier revision of this very section also stated that
  `residuals.json` "holds 0 entries" — that is **false**: the register is `{"entries": {<plan-id>:
  [...]}}` and carries entries for ~25 plan/iteration ids, R6 among them. The reason nothing was
  written is narrower and unchanged: the register is the **migration-history** surface while the
  issue store now owns capture, and `store.db` does not exist (`store.not-initialized`), so the
  finding stays in this report rather than being written to a surface that would misrepresent where
  it lives. **PM's call** whether to initialise the store.
- **The ruling this decision needs is now planned.** `/root/workspace/bilibili-asr-archive/.mstar/plans/20260930-metadata-shape-resilience.md`
  (`20260930-metadata-shape-resilience`) closes R6 with the evidence above and carries the RED
  baseline reproduced on the unfixed build. It is **draft, unregistered, and not dispatched** — the
  PM owns that.

### F2 (P3, environment) — the engine's default model resolution requires a network this host cannot reach

- **Measured:** `default_config()` resolves `model_name = Qwen/Qwen3-ASR-1.7B-hf` and
  `aligner_name = Qwen/Qwen3-ForcedAligner-0.6B-hf` (hub ids, `model_id = None`), while
  `https://huggingface.co/` answers **`curl rc=35` (connection reset)** and the HF cache holds
  **only `refs/` — 12 K per model, no weights**. The real weights (3.9 G + 1.8 G) exist only as
  local directories `bilibili-asr-archive/models/…` and are gitignored, so the **detached worktree
  has no `models/`**.
- **Nothing was mis-run:** this is why B5 was not started. The prior successful Qwen3 run solved
  it by exporting `BILI_ASR_MODEL=<absolute local checkpoint path>`
  (`logs/ab-hotwords-qwen3-20260926T103940.log`, environment record). Route 2's ASR stage will
  need the same explicit local paths **and** an absolute path outside the worktree, since
  `models/` does not exist inside it.
- **Not a defect**, but a run-book trap worth recording: the documented default is hub-shaped and
  this host is offline for that hub.

### F3 (P3, observation) — `observed_total` moved 1 739 → 1 691

Recorded 2026-09-25 as `total=1739` (and the earlier pad enumeration also read 1739); the
`recArchivesByKeywords` probe in E-1 still reads **1 739**, while the cursor's
`observed_total` from the shipped `arc/search` endpoint reads **1 691**. Two different endpoints,
two different totals. Recorded as an observation with its evidence; **not** diagnosed, and not
claimed to be a cause of F1.

## Not verified

- **A3–A7 (route 1) — `not-run`.** Requires all four items in the store; only 2 of 4 are, and the
  store cannot be completed while F1 holds.
- **B1–B7 (route 2) — `not-run`.** Same dependency, plus the deliberate decision not to spend the
  ~1 h GPU stage on an unproven admission premise.
- **C0–C2, D0–D4 — `not-run`.**
- **The four-item ordering the operator asked for is not what was exercised.** What A2 actually
  covered is 2 of the 4 named items (`BV1BdtazGEBE`, `BV1Y7M4zNEfF`); the other two are on the
  blocked page. Stated plainly rather than left to be inferred from the counters.
- **No product code was changed, no branch was moved, nothing was reset, and `/mnt/123pan` was not
  touched.** `refs/heads/main` is `d41c257…` before and after; the only new Git objects are the
  `rescue/` ref and the detached worktree.
- **Ambient note:** the pad itself hit `-352 风控校验失败` on the space endpoint while diagnosing,
  so part of the localisation had to run on the target. Both hosts' refusals are recorded under
  the run's logs; this is normal upstream risk control, not F1.

## Completion recommendation

**Counts: assigned 24 · passed 3 · failed 1 · not-run 20 · blocked 0.**

**Product verdict: route 1 is blocked by a P1 product defect (F1), and route 2 was never reached.**
This is a **completed verification round** — the scenario with a determinate result (A2) produced a
reproducible defect with a located cause, a measured blast radius, and a bounded repair owner. The
run did **not** pass, and the report does not claim it did.

**Recommended next step, in order:**

1. **Repair F1** as a `development` plan (page-level `description` normalization, plus a decision on
   whether one bad item may fail a whole page). This is upstream of every remaining scenario.
2. **Then resume this workflow** — A2 re-run, then A3–A7, then B1–B7 and the rest. The workflow
   stays open for exactly that; the build, the roots, the preserve ledger and the two artifact roots
   are all standing, and A1's rescue ref plus the patch file make the target's pre-state fully
   recoverable.
3. **The ~1 h GPU stage remains unspent** — deliberately. Do not authorise it until A2/B3 admit the
   four items.

**Nothing was left in a half-state that a resume cannot pick up:** cursor is `next_page=6, ready`;
`main` is untouched; the delta is saved twice with `sha256`; the worktree is at `ed291be`.

---

## Addendum — where the evidence lives, and the state this round leaves behind

**Evidence tree (durable, on the pad, inside the workflow):**
`.mstar/workflows/e2e-23191782-love-items-dual-route/evidence/` — 37 verbatim files copied from
the target, indexed by `evidence/README.md`. The report's `a2-*.log` / `a0-*.log` / `a1-*`
references above resolve inside it. Nothing in it was edited after collection.

**State left on the target host (all recoverable, nothing half-written):**

| Item | State |
|---|---|
| `refs/heads/main` | `d41c2572e27c116fb422f4be93927f0e71b422e3` — **unchanged** (before and after) |
| tracked working tree | the pre-existing ` M …/asr.py` delta, **byte-identical** (`sha256 cf535810…`) |
| `rescue/d41c257-librosa-m4a` | created → `d41c257` (a ref, not a copy; nothing deleted) |
| pre-run ledger | `/root/e2e-asr/love-dual-route/pre-run/` (9 files, incl. the patch and both hashes) |
| build worktree | `/root/e2e-asr/love-dual-route/build` at `ed291be`, detached, `porcelain` empty |
| route-1 archive root | `/root/e2e-asr/love-dual-route/route1` — 30 videos / 30 parts, 0 transcripts, cursor `next_page=6, ready` |
| route-1/2 artifact roots | `/mnt/e/bili-e2e/love-dual-route/{route1,route2}` — created, **empty** |
| route-2 archive root | **not created** (B1 never ran) |
| the uncommitted delta | still present in the primary checkout, untouched, as it was found |
| `/mnt/123pan` | not touched (still `EIO` + `401`) |
| GPU time spent | **none** |

**What a resume needs:** F1 repaired, then re-run A2. Everything else the plan calls for is
already staged, and A1's rescue ref plus the patch file mean the target's pre-state can be
restored or re-derived without relying on the reflog.
