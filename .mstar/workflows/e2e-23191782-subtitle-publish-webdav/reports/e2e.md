# E2E Verification Report — 未明子 six-part subtitle → publication chain (fresh root, WebDAV artifact root)

> **Workflow:** `e2e-23191782-subtitle-publish-webdav` (`type: plan`, `delivery_kind: verification/report-only`)
> **Status:** scope locked by PM 2026-09-22; execution owned by `ops-engineer`
> **Executor:** `ops-engineer` (PM orchestrates; ops executes and records actual results)
> **This file is the plan AND the report.** PM writes `## Scope` … `## Acceptance criteria`;
> ops fills `## Results`, `## Evidence`, `## Findings and handoff`, `## Not verified`,
> `## Completion recommendation` with what actually happened.

## Scope

- **Workflow / plan:** `e2e-23191782-subtitle-publish-webdav` — an independent E2E verification
  workflow (`mstar-e2e`), not an iteration phase, not a development plan, not a QA gate.
  Scenarios A0–A8 below are the workflow's plan rows.

- **User authorization and permitted side effects.** Direct operator request 2026-09-22:
  “开一次新的e2e，目标为以下的几个视频” with six Bilibili URLs. The PM put the **branch
  question** to the operator before locking the scope, because the six items turned out to carry
  live AI captions (see the premise below) and therefore cannot exercise the audio→ASR branch.
  Operator answer the same day: **option A — run these six through the subtitle → publication
  chain**, plus the assertion that they are correctly excluded from the audio queue.
  Permitted: metadata enumeration for UID 23191782 on the target host (bounded window, see A2),
  subtitle acquisition for the six named parts, publication of their bundles to the WebDAV
  artifact root, writes to the fresh archive root (state, local disk) and to the WebDAV artifact
  root (products), reading the existing SESSDATA from its existing location (referred to by path
  only — **never recorded**). **Not permitted and not to be done:** any product-code change for
  the run, production/deployment changes, destructive cleanup outside the named roots, media
  redistribution, the project's full local test suite (not authorized), and — out of scope by the
  operator's choice — any audio download or GPU transcription for these six items.

- **Target build / ref.** Target checkout `/root/workspace/bilibili-asr-archive` at
  `37b0acc` (2026-09-21), = `origin/main`. The PM fast-forwarded it the same day (21 commits,
  `ef5e1e8..37b0acc`) and repaired both virtualenv entry points, which were broken at the time
  (`bili-asr --version` → `ModuleNotFoundError: No module named 'bili_asr'` in both
  `<product>/.venv` and `/root/gpu-venv`; neither site-packages held a `bili_asr-*.dist-info` or an
  editable `.pth`). The repair was `uv pip install -e .` (repo venv: plain; GPU venv: `--no-deps`
  to leave the torch/ROCm stack untouched) and the build residue `src/bili_asr.egg-info/` was
  removed. **A0 must record which entry point the run actually used and from which tree it
  resolved.** The delivered feature under test is `publish-transcripts` + the transcript
  projection (`iter-2026-09-transcript-projections`, plan `20260920-transcript-projections`), which
  has not yet run on live rows.

- **Actual environment / device / session.** Target WSL2 `DESKTOP-HHFROLO` on the Windows compute
  box (192.168.3.21), AMD Radeon RX 7800 XT (gfx1101), interpreter `/root/gpu-venv/bin/python`
  (Python 3.12.3) — the pair `check-asr-env` verifies — with the product editable-installed into
  it; product invoked as `bili-asr <cmd> …` (or `PYTHONPATH=<product>/src /root/gpu-venv/bin/python
  -m bili_asr.cli <cmd> …`). Archive root (state, local disk, **fresh**): `/root/e2e-asr/subtitle-publish`.
  Artifact root (products, network mount, **must already exist**): `/mnt/123pan/bili-asr-e2e/subtitle-publish`.
  Logs: `/root/e2e-asr/logs/subtitle-publish-<UTC-stamp>/`.

- **Assigned scenario IDs:** A0–A8.

### The six items (identified live at scope-lock, 2026-09-22)

All six belong to UID **23191782** (未明子), all are **single-part** (`page_index 0`), and all six
were live-probed with the production gateway (`BilibiliApiGateway.get_video_parts` /
`get_subtitle_tracks`) **before** the scope was locked. Probe log:
`/root/e2e-asr/scope-lock/probe-subs-20260922T110740Z.jsonl`.

| # | `bvid` | `cid` | duration | live tracks | title as served |
|---|---|---|---|---|---|
| 1 | `BV1BdtazGEBE` | 31594841414 | 6395 s (106.6 min) | **6** — `ai-zh` + `ai-en`/`ai-ja`/`ai-es`/`ai-ar`/`ai-pt` | 【哲学与现实】爱情升级指南——当你说“我爱你”时，你到底在怎说什么 |
| 2 | `BV1Y7M4zNEfF` | 30506419561 | 2598 s (43.3 min) | 1 — `ai-zh` | 【行动指南】从爱情走向革命 |
| 3 | `BV1vNTqzFEve` | 30412768784 | 5112 s (85.2 min) | 1 — `ai-zh` | 【爱欲经济学】爱情的阶次和解放 |
| 4 | `BV1zz5zzFENq` | 29471998505 | 2087 s (34.8 min) | 1 — `ai-zh` | 【历史唯物主义】革命与爱情 |
| 5 | `BV11p5qzAE6s` | 29471278516 | 2408 s (40.1 min) | 1 — `ai-zh` | 【实事求是】被迫配种的本已是囚，革命者应该如何恋爱 |
| 6 | `BV1iddQYQE7D` | 29363077962 | 7682 s (128.0 min) | 1 — `ai-zh` | 【随便聊聊】普通人如何扬弃性的压抑，革命者如何扬弃爱的压抑 |

Total audio length **26 282 s ≈ 7.30 h**. Every track above is `is_ai = true`.

### Locked premise, and what it forces (live-probed, NOT inherited)

**All six items already serve live AI captions.** The chain's published design is
“subtitles first, local ASR as fallback”, so all six take the subtitle branch, and
`derive-manifest`'s queue predicate (`no transcript`) therefore **excludes all six from the audio
queue**. This is the fact the previous E2E's round-2 failure flowed from (residual
`e2e-23191782-longform-pair-webdav · R2`), so it is re-measured here rather than inherited:
A4 does not assume the exclusion, it **asserts** it — had any of the six entered the derived
queue, A4 would be a `failed` scenario, not a surprise.

The PM chose the enumeration window from a live page walk, not from a stored manifest: the six sit
on channel **pages 5 and 6** of `mid 23191782` (30/page, `observed_total = 1691`), while pages
**1–3 answered `GatewayRateLimited` / `GatewayShapeError`** at scope-lock time and pages **4–6
answered normally**. Page-walk log: `/root/e2e-asr/scope-lock/locate-pages-20260922T111225Z.json`.
A2 therefore enumerates the bounded window that is reachable, and records the blocked pages as a
known upstream condition (residual `e2e-23191782-longform-pair-webdav · R3`) instead of failing on
them.

### Assigned scenarios

| ID | Scenario | Expected |
|---|---|---|
| **A0** | Target build and entry-point identity | `git -C /root/workspace/bilibili-asr-archive rev-parse HEAD` = `37b0acc…`; `git status --porcelain` = only the pre-existing `?? .env.bak-20260917-181947`; `bili-asr --version` prints `bili-asr 0.1.0` from **both** `<product>/.venv/bin/bili-asr` and `/root/gpu-venv/bin/bili-asr`; `bili-asr publish-transcripts --help` prints the command help (the command under test exists); record the entry point used for the run and the resolved `bili_asr.__file__` of the interpreter that ran it |
| **A1** | Host self-check | `bili-asr check-asr-env` exits **0** from the product root and its device line names the RX 7800 XT / `gfx1101`; record the cwd used, the exact failing check if it fails, and any environment variable the passing invocation needed. Two candidate causes existed and **the run decides between them, not this scope text**: the known cwd-fragility of the helper anchor (residuals `e2e-23191782-longform-pair-webdav · R1` and `· R5`) or an unset host-side variable the command depends on. *PM correction 2026-09-22, after reading the run's evidence: the executor measured the second — the anchor was fine and the cwd was correct; `HSA_ENABLE_DXG_DETECTION` was unset (F-1).* |
| **A2** | Fresh-root bootstrap over the bounded window | `bili-asr fetch-meta --mid 23191782 --start-page 4 --limit-pages 3 --archive-root /root/e2e-asr/subtitle-publish` exits **0**; `archive.db` exists and holds **all six target parts** (assert each `bvid` present with a `cid`); record pages fetched, `observed_total`, and the stored cursor (`ingestion_cursors.next_page/state`). A page that stays rate-limited is recorded with its error and the workaround used; a window that cannot be enumerated leaves the scenario `blocked`, never a claimed pass |
| **A3** | Subtitle acquisition for all six | `bili-asr harvest-subs --bvid <bvid>:p0 --archive-root …` per item, each exit **0** and each recording a determinate outcome. Per row assert: `transcripts.source_kind = 'subtitle-ai'`, a recorded `language`, `transcript_segments` count > 0, `content_sha256` recorded, and `acquisition_attempts.outcome = 'stored'`. Record the per-item segment counts, the six-way total, and **which track the default language selection picked** for item 1 (it exposes six) and why |
| **A4** | The six are excluded from the derived queue | `bili-asr derive-manifest --archive-root …` exits **0**; the derived `work_id` set **equals** the store's pending set for that root (both set differences empty); **all six target `work_id`s are ABSENT** from the derived queue; a second invocation is idempotent (`already_derived` = the whole set, effective rows unchanged). Record `queue=`, `derived=`, `already_derived=`, `chain_owned=`, `identity_mismatch=` and both set differences |
| **A5** | Publish the six as archive bundles to the WebDAV artifact root | `bili-asr publish-transcripts --bvid <bvid>:p0 --archive-root … --artifact-root /mnt/123pan/bili-asr-e2e/subtitle-publish` per item, each exit **0**; per published row the four families (`srt`, `txt`, `md`, `raw`) **plus** the `.bundle-ready` marker exist **under the artifact root**; state (`archive.db`, `manifest/`, `coordinator/`, any audio) stays in the local archive root; one `archived` manifest row per publication. Record every product path with its byte size and the bundle `sha256`. Then run the whole set in one unbounded invocation and record its summary counters |
| **A6** | The archive's own readers agree on the published rows | `bili-asr verify --archive-root … --artifact-root … --trusted-local` reports **zero defects on the six** (the run is `trusted-local` by operator ownership); `bili-asr coverage --archive-root … --artifact-root … --trusted-local --quality` prints and includes the six; the four artifact families are mutually consistent per row; each recorded bundle `sha256` **recomputes** from the on-disk bytes; `bili-asr search` returns text from at least one published row; `bili-asr export --format json --status archived` lists the six |
| **A7** | Artifact-root boundary on the **publication** path | (i) the documented “must already exist” contract holds: a publication against a **non-existent** artifact root refuses with exit **1** and a named refusal, and writes nothing (confirm by re-listing); (ii) after A5 **nothing** was written outside the artifact root — the archive root holds only state (`archive.db`, `manifest/`, `coordinator/`); (iii) record the elapsed wall time of the publication path on the WebDAV mount, and a local-artifact-root comparison for the same work (one row is an acceptable sample if the full set is not re-run — state exactly what was measured). The prior run's A7 answered the *ASR-chain* peak-measurement questions; this scenario covers the publication path only and must not re-claim those answers |
| **A8** | Re-publication is inert (no clobber) | Run A5's full-set publication a second time: the summary reports the rows as already published, **no** new manifest row appears, and every bundle `sha256` is **byte-identical** to A5's recorded value with unchanged product mtimes. If a newer transcript version exists for one row, record whether the published product was left as-is (the documented contract); if no newer version exists, report that clause `not-run` rather than inventing a case |

Outcome vocabulary is exactly `passed` / `failed` / `not-run` / `blocked`. A scenario with no
determinate evidence is `not-run` or `blocked` — never a claimed pass.

### Acceptance criteria

1. All nine scenarios have exactly one determinate outcome, each carried by commands with their
   exit codes and the observed output (not a summary of intent).
2. Every product claim is backed by a path listing with byte sizes, and every bundle claim by a
   `sha256` recomputed from the on-disk bytes.
3. Nothing was written outside the two named roots; `git status` of the target checkout is
   unchanged from A0's baseline; no product file was modified.
4. The report's `## Not verified` section states in the run's own words that the audio→ASR branch
   was not exercised by these six items and that residual `e2e-23191782-longform-pair-webdav · R2`
   therefore stays open.
5. `## Findings and handoff` routes every failure to a bounded follow-up with the evidence that
   reproduces it. No product repair happens inside this workflow.

### Executor corrections and realizations of Scope (added by `ops-engineer`, 2026-09-22)

Marked as the executor's own corrections, per the Assignment's permission to correct Scope where
reality differs. Nothing in the PM's `## Scope` was deleted; these are additions.

1. **A1's stated expectation (`check-asr-env` exits 0) does not hold in the default login
   environment of the target host.** The determining invariant is `HSA_ENABLE_DXG_DETECTION=1`,
   which `docs/wsl-rocm-gpu.md` step 8 documents as required *and* which the check's own FAIL line
   names as its fix, but which is **not persisted** on `DESKTOP-HHFROLO` (no such line in
   `/root/.bashrc`). The PM's Scope attributed A1's fragility to cwd; **the cwd was correct in this
   run and is not the mechanism** — the env var is. A1 is therefore recorded `failed` against the
   expectation as written, with the capability itself proven under the documented invariant.
2. **A7(iii) requires a third writable root that the run's hard constraint does not name.** The
   scenario asks for a "local-artifact-root comparison", and a local artifact root can only be
   written under an authorized root. The executor created
   `/root/e2e-asr/subtitle-publish/artifact-local` (inside the archive root — the only other
   authorized local root) and ran that measurement **after** the A7(ii) state listing, so the A7(ii)
   assertion still describes the publication path's own output. Disclosed consequence: that
   publication appended a **7th `archived` manifest row** (recorded here, and in F-2 below).
3. **The derived-queue manifest field is `status`, not `state`** — a derived row is
   `{"status":"needs_audio", …}`. The PM's wording "`ingestion_cursors.next_page/state`" is correct
   for the cursor; for manifest rows read `status`.
4. **"the store's pending set" was realized as the work_id set of the `v_pending_subtitles` view**
   (same predicate: not `gone` and no transcript). It held **84** rows and equalled the derived set
   exactly, so both differences were empty.
5. **A2's rate-limit contingency did not trigger.** The bounded window (pages 4–6) answered on the
   **first** attempt; no retry, no backoff, no `GatewayRateLimited`. The stored cursor state is
   `limited` — capped by `--limit-pages 3`, **not** rate-limited — and `last_error_code` is `NULL`.
   Pages 1–3 were not re-probed (out of scope).
6. **`verify`/`coverage` exit non-zero on this store for a reason unrelated to the six** (the 84
   still-unprocessed rows). The A6 clauses are stated against the six and are all met; the exit codes
   are recorded verbatim rather than normalized. See F-4.
7. Scope realisation note: "one `archived` manifest row per publication" in A5 and "no new manifest
   row" in A8 were asserted against `manifest.jsonl` line counts and a whole-file `sha256`, not
   against a database table — the manifest is an append-only JSONL under `<archive_root>/manifest/`.

## Results

Filled by `ops-engineer`, 2026-09-22, run stamp `20260922T111639Z`. Every outcome below is the
result of a command actually executed in this run; nothing is inherited from the scope-lock probes.

| Scenario | Expected | Actual | Outcome | Evidence |
|---|---|---|---|---|
| **A0** | HEAD `37b0acc…`, clean baseline, `bili-asr 0.1.0` from both entry points, command help present | HEAD = `37b0acce5dbd4e0d0992b69bdce5c8bd4d8e1030`, branch `main`, = `origin/main`; `git status --porcelain` = `?? .env.bak-20260917-181947` only; `bili-asr 0.1.0` (exit 0) from **both** `/root/gpu-venv/bin/bili-asr` and `<product>/.venv/bin/bili-asr`; both resolve `bili_asr.__file__=<product>/src/bili_asr/__init__.py` (editable, same tree); `publish-transcripts --help` exit 0. **Entry point used for the whole run: `/root/gpu-venv/bin/bili-asr`, cwd = product root** | `passed` | `01-setup-a0.log` |
| **A1** | bare `check-asr-env` exits 0 from the product root; device line names RX 7800 XT / `gfx1101` | bare invocation: **exit 1**, `dxg-detection FAIL … HSA_ENABLE_DXG_DETECTION=unset`, `device-probe FAIL torch.cuda.is_available() == False`, `asr-env: not verified (2 failed)`. Same command with the recipe's documented `HSA_ENABLE_DXG_DETECTION=1`: **exit 0**, `device ok name=AMD Radeon RX 7800 XT arch=gfx1101 vram_gb=15.8`. cwd = product root in both runs; `/dev/dxg` exists, `/dev/dri` does not | `failed` | `02-a1.log`, `02b-a1-retry.log` |
| **A2** | `fetch-meta --start-page 4 --limit-pages 3` exits 0; all six target parts in `archive.db`; record pages/cursor | exit 0 on the **first** attempt: `collected 3 page(s) for mid=23191782 (outcome=limited)`, `cursor: next_page=7 state=limited`. `archive.db` 180224 B; 90 `video_parts` / 90 `videos`; **all six present with the expected `cid`** (`video_part_id` 38, 60, 61, 72, 73, 74); `observed_total=1691`, `last_error_code=NULL`; no rate limit, no retry | `passed` | `03-a2.log`, `03b-a2-assert.log` |
| **A3** | six `harvest-subs` runs exit 0; per row `subtitle-ai` + language + segments + sha256 + `stored` | all six exit **0**, each `stored subtitle-ai ai-zh v1`; segments 2318+947+1709+797+918+2918 = **9607**; `content_sha256` recorded for all six; `acquisition_attempts.outcome='stored'` (kind `subtitle`), error_code NULL; `transcripts` total = 6. **Item 1's default selection picked `ai-zh`** — of its six tracks only `ai-zh` is in the default zh family ("the zh family, then en, CC before AI" does not reach the en/ja/es/ar/pt AI tracks) | `passed` | `04-a3.log`, `04b-a3-assert.log` |
| **A4** | queue ≠ empty set semantics; derived set = pending set; six ABSENT; second run idempotent | run 1: exit 0, `queue=84 derived=84 already_derived=0 chain_owned=0 identity_mismatch=0`; run 2: exit 0, `queue=84 derived=0 already_derived=84 chain_owned=0 identity_mismatch=0`. Derived set (84) == `v_pending_subtitles` set (84), **both differences `[]`**; **all six ABSENT** from both. `manifest.jsonl` byte-identical across run 2 (`sha256 7237ec1c…`, mtime unchanged) | `passed` | `05-a4.log`, `05b-a4-assert.log` |
| **A5** | six per-item publishes exit 0; 4 families + marker under the artifact root; state stays local; one `archived` row each | six per-item publishes exit **0** (`candidates=1 published=1 already_published=0 failed=0`), then the **full-set unbounded invocation #1** exit 0: `candidates=6 published=0 already_published=6 failed=0`. Under the artifact root: **24 product files + 6 `.bundle-ready` markers = 30 files**, families `transcripts/{srt,txt,md,raw}`; archive root holds only state; `archived` manifest rows = **6** (90 rows total = 84 `needs_audio` + 6 `archived`) | `passed` | `06-a5-item1.log`, `07-a5-rest.log` |
| **A6** | readers agree on the six; families consistent; sha256 recomputes; search + export work | `verify … --trusted-local`: `checked=90 defect_count=84`, every defect `retryable_incomplete` on one of the **84 unrelated** `needs_audio` rows — **zero defects on the six** (parsed and asserted); overall **exit 1** (see F-4). `coverage … --quality`: prints all 90 rows incl. the six (`artifact_count=4`, `status=archived`, `language=ai-zh`), **exit 1**. Four families + marker mutually consistent per row; all 24 recorded vs recomputed `sha256` **equal**. `search` exit 0 returning a snippet from item 1 (plus a hit on item 2). `export --format json --status archived` exit 0, **exactly the six** | `passed` | `08-a6a.log`, `09-a6b.log`, `a6-export-archived.json`, `a6-search-item1.json` |
| **A7** | (i) missing artifact root refuses, writes nothing; (ii) nothing outside the artifact root; (iii) WebDAV vs local wall time | (i) `publish-transcripts: artifact root does not exist (<path>)`, **exit 1**, probe path still absent, manifest unchanged (90 lines), artifact file count unchanged (30). (ii) archive root = `archive.db`, `coordinator/archive-writer.lock` (0 B), `manifest/manifest.jsonl` + `.lock`, `search.db` (A6's FTS index) — **no product-family file**; nothing else under `/root/e2e-asr` changed but `logs/` and the archive root; `/mnt/123pan/bili-asr-e2e` gained only the artifact root. (iii) WebDAV per-row **1.364 / 0.377 / 0.383 / 0.324 / 0.369 / 0.376 s**; same sample row to a local artifact root **0.081 s** (~4× penalty on a 188 KB bundle, byte-identical output) | `passed` | `10-a7ab.log`, `12-a7iii.log`, `14-localhash.log` |
| **A8** | 2nd full-set publication inert: already published, no new row, identical sha256 + mtimes | 2nd full-set invocation exit **0**: `candidates=6 published=0 already_published=6 failed=0` in 0.107 s; manifest 90 lines / 6 `archived` **before and after**, whole-file `sha256 cce94931…` identical; all **30 file `sha256` and all mtimes identical** (diff empty). No row has a newer transcript version (each work_id has exactly one transcript, `version=1`) → the newer-version clause is **`not-run`**; no case invented | `passed` (one clause `not-run`) | `11-a8.log`, `a8-before.sha256` / `a8-after.sha256`, `a8-before.mtimes` / `a8-after.mtimes` |

## Evidence

**All evidence below is new, produced by this run on 2026-09-22 between 11:16:39Z and 11:20:26Z.**
Nothing is reused: the PM's scope-lock probes
(`/root/e2e-asr/scope-lock/probe-subs-20260922T110740Z.jsonl`,
`…/locate-pages-20260922T111225Z.json`) are *not* cited as results — every number in `## Results`
came from a command executed during the run. The only inherited facts used were the six
`bvid`/`cid` pairs, used as assertion oracles and independently re-measured in A2/A3.

**Channel.** The remote login shell is `cmd.exe`; every script was written locally and piped in as
`ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes -o ConnectTimeout=20 chosenecho@192.168.3.21 'wsl -e bash -s' < <script>.sh`.
Exit codes quoted are those of the *remote* command; `ssh_exit=0` on every attempt (the host was
reachable on the first probe — no blocked-by-unreachable scenario).

**Raw logs (target host, `192.168.3.21`): `/root/e2e-asr/logs/subtitle-publish-20260922T111639Z/`**

```
01-setup-a0.log        7549 B    03b-a2-assert.log     2912 B    09-a6b.log            3820 B
02-a1.log              2240 B    04-a3.log             3934 B    10-a7ab.log           3134 B
02b-a1-retry.log       5849 B    04b-a3-assert.log     3342 B    11-a8.log            10105 B
03-a2.log             11282 B    05-a4.log             5951 B    12-a7iii.log          3752 B
                                 05b-a4-assert.log     1606 B    13-final-evidence.log 3187 B
                                 06-a5-item1.log       3118 B    14-localhash.log      2412 B
                                 07-a5-rest.log       15859 B
                                 08-a6a.log           26660 B
a6-export-archived.json 3927 B   a6-search-item1.json 1168 B   a8-before/after.sha256 4848 B
a8-before/after.mtimes  3703 B   a6-export-archived.err   0 B
```

**Environment identity.** WSL2 `DESKTOP-HHFROLO` `Linux 6.18.33.2-microsoft-standard-WSL2` x86_64,
user `root`; interpreter `/root/gpu-venv/bin/python` = Python 3.12.3; `torch 2.9.1+rocm7.2.0.git7e1940d4`,
`hip 7.2.26015-fc0010cf6a`; artifact root on `fuse.rclone` mount `123pan:` at `/mnt/123pan`.
**Session cookie: never read into a variable that was printed, never logged, never reported.**
Only `/root/workspace/bilibili-asr-archive/.env` was sourced (via `set -a; . …/.env; set +a`) and the
commands themselves print only `sessdata: present`.

### A0 — build and entry-point identity

```bash
git -C /root/workspace/bilibili-asr-archive rev-parse HEAD
# 37b0acce5dbd4e0d0992b69bdce5c8bd4d8e1030                                  exit=0
git -C /root/workspace/bilibili-asr-archive rev-parse --abbrev-ref HEAD     # main            exit=0
git -C /root/workspace/bilibili-asr-archive log -1 --format='%H %ad %s' --date=iso
# 37b0acce5dbd4e0d0992b69bdce5c8bd4d8e1030 2026-09-21 09:54:35 +0800 Merge remote-tracking branch 'origin/main'
git -C /root/workspace/bilibili-asr-archive status --porcelain   # ?? .env.bak-20260917-181947   exit=0
git -C /root/workspace/bilibili-asr-archive rev-parse origin/main # 37b0acce5dbd4e0d0992b69bdce5c8bd4d8e1030
/root/gpu-venv/bin/bili-asr --version                             # bili-asr 0.1.0   exit=0
/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/bili-asr --version
# bili-asr 0.1.0                                                             exit=0
/root/gpu-venv/bin/python -c 'import bili_asr,sys; print(bili_asr.__file__, sys.executable)'
# /root/workspace/bilibili-asr-archive/bilibili-asr-archive/src/bili_asr/__init__.py
# /root/gpu-venv/bin/python
cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && /root/gpu-venv/bin/bili-asr publish-transcripts --help
# prints usage + options --bvid/--limit-parts/--archive-root/--artifact-root            exit=0
```

Both site-packages carry `bili_asr-0.1.0.dist-info` **and** `__editable__.bili_asr-0.1.0.pth`, and
both resolve `bili_asr` to the same `<product>/src/bili_asr/` tree — the PM's 2026-09-22 entry-point
repair holds. **The run used `/root/gpu-venv/bin/bili-asr` with cwd = product root throughout**;
A0.10 cross-checked the product-venv script and it printed identical help.

### A1 — host self-check (the one failure)

```bash
cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && /root/gpu-venv/bin/bili-asr check-asr-env
# check: dxg-detection FAIL dxg_device=path-exists (not opened) HSA_ENABLE_DXG_DETECTION=unset
# check: rocm-loader-path ok
# check: torch-present ok
# check: hsa-runtime ok
# check: device-probe FAIL torch.cuda.is_available() == False hip=7.2.26015-fc0010cf6a
# asr-env: not verified (2 failed)
# exit=1
cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && HSA_ENABLE_DXG_DETECTION=1 /root/gpu-venv/bin/bili-asr check-asr-env
# check: dxg-detection ok
# check: rocm-loader-path ok
# check: torch-present ok
# check: hsa-runtime ok
# check: device ok name=AMD Radeon RX 7800 XT arch=gfx1101 vram_gb=15.8 hip=7.2.26015-fc0010cf6a
# asr-env: verified
# exit=0
ls -l /dev/dxg    # crw-rw-rw- 1 root root 10, 258 Sep 20 20:05 /dev/dxg          exit=0
ls -l /dev/dri    # No such file or directory                                     exit=2
grep -n -E 'HSA|ROCM|torch' /root/.bashrc   # (no match)                           exit=0
```

`docs/wsl-rocm-gpu.md` line 32 lists `HSA_ENABLE_DXG_DETECTION=1` as part of the verified
combination and line 291 says to persist it in `~/.bashrc`; that line is **absent** from
`/root/.bashrc`, so a bare shell fails the same check the recipe's step 8 is meant to satisfy.
`/root/gpu-venv/lib/python3.12/site-packages/torch/lib/libhsa-runtime64.so` is present (4248144 B,
Sep 12 18:50), i.e. recipe step 7 was applied earlier. `check-asr-env` itself needs no network.

### A2 — fresh-root bootstrap over the bounded window

```bash
mkdir -p /root/e2e-asr/subtitle-publish          # archive root: created empty (was absent)
mkdir -p /mnt/123pan/bili-asr-e2e/subtitle-publish   # artifact root: created empty (was absent)
set -a; . /root/workspace/bilibili-asr-archive/.env; set +a
cd <product> && /root/gpu-venv/bin/bili-asr fetch-meta --mid 23191782 --start-page 4 \
    --limit-pages 3 --archive-root /root/e2e-asr/subtitle-publish
# sessdata: present
# fetch-meta: collected 3 page(s) for mid=23191782 (outcome=limited)
# cursor: next_page=7 state=limited
# FETCH_META_EXIT=0                                     (11:17:19Z → 11:17:21Z, ~2 s)
```

No `GatewayRateLimited` / `GatewayShapeError` occurred: the bounded window answered on attempt 1, so
the PM's 3-attempt/30–60 s backoff contingency was **not** exercised and no retry is recorded. Post
state: `archive.db` 180224 B + `coordinator/`; 90 `video_parts`, 90 `videos`, 1 `bilibili_users` row.

Database assertions (read-only `sqlite3` via `/root/gpu-venv/bin/python`, URI `mode=ro`):

```sql
select * from ingestion_cursors;
-- {mid: 23191782, next_page: 7, observed_total: 1691, state: 'limited',
--  last_error_code: None, updated_at: 1790075841}
select count(*) from video_parts;   -- 90
select bvid,page_index,cid,duration_ms,processing_status from video_parts
 where bvid in ('BV1BdtazGEBE','BV1Y7M4zNEfF','BV1vNTqzFEve','BV1zz5zzFENq','BV11p5qzAE6s','BV1iddQYQE7D');
-- BV11p5qzAE6s p0 cid=29471278516 2408000 discovered
-- BV1BdtazGEBE p0 cid=31594841414 6395000 discovered
-- BV1Y7M4zNEfF p0 cid=30506419561 2598000 discovered
-- BV1iddQYQE7D p0 cid=29363077962 7682000 discovered
-- BV1vNTqzFEve p0 cid=30412768784 5112000 discovered
-- BV1zz5zzFENq p0 cid=29471998505 2087000 discovered
-- ALL_SIX_PRESENT_WITH_CID: True     (video_part_id 38, 60, 61, 72, 73, 74)
```

Every `cid` equals the scope-locked value, and every `duration_ms` equals the scope-locked duration
× 1000. `sqlite3` is not installed on the host (`which sqlite3` → exit 1); all DB work used Python's
`sqlite3` module, which is equivalent and read-only.

### A3 — subtitle acquisition (six items)

```bash
cd <product> && /root/gpu-venv/bin/bili-asr probe-subs --bvid BV1BdtazGEBE:p0 --archive-root /root/e2e-asr/subtitle-publish
# probe BV1BdtazGEBE:p0 tracks=6
#   track ai-zh ai 中文 / track ai-en ai English / track ai-ja ai 日本語
#   track ai-es ai Español / track ai-ar ai العربية / track ai-pt ai Português
# probe-subs: probed=1 with_tracks=1 without_tracks=0 failed=0        exit=0
# (BV1Y7M4zNEfF:p0 → tracks=1: ai-zh ai 中文                            exit=0)
for B in BV1BdtazGEBE BV1Y7M4zNEfF BV1vNTqzFEve BV1zz5zzFENq BV11p5qzAE6s BV1iddQYQE7D; do
  cd <product> && /root/gpu-venv/bin/bili-asr harvest-subs --bvid ${B}:p0 --archive-root /root/e2e-asr/subtitle-publish
done
# harvest BV1BdtazGEBE:p0 stored subtitle-ai ai-zh v1 → run_id=e786dec6… attempted=1 stored=1 failed=0  exit=0
# harvest BV1Y7M4zNEfF:p0 stored subtitle-ai ai-zh v1 → run_id=c69ee64d… attempted=1 stored=1 failed=0  exit=0
# harvest BV1vNTqzFEve:p0 stored subtitle-ai ai-zh v1 → run_id=433d71d1… attempted=1 stored=1 failed=0  exit=0
# harvest BV1zz5zzFENq:p0 stored subtitle-ai ai-zh v1 → run_id=359dce85… attempted=1 stored=1 failed=0  exit=0
# harvest BV11p5qzAE6s:p0 stored subtitle-ai ai-zh v1 → run_id=7b9f403d… attempted=1 stored=1 failed=0  exit=0
# harvest BV1iddQYQE7D:p0 stored subtitle-ai ai-zh v1 → run_id=143c1896… attempted=1 stored=1 failed=0  exit=0
```

Per-row assertion query (join `video_parts`→`transcripts`, sub-selects for `transcript_segments` and
the latest `acquisition_attempts`), result — **`ALL_ROW_ASSERTIONS_PASS: True`**:

```
work_id            transcript_id source_kind language version content_sha256(first 16) segs outcome   run_kind
BV1BdtazGEBE:p0         1  subtitle-ai  ai-zh   1  800e2de54ec7fda8  2318  stored   subtitle
BV1Y7M4zNEfF:p0         2  subtitle-ai  ai-zh   1  0bb5a5da823c1c1f   947  stored   subtitle
BV1vNTqzFEve:p0         3  subtitle-ai  ai-zh   1  e80f72b455be055c  1709  stored   subtitle
BV1zz5zzFENq:p0         4  subtitle-ai  ai-zh   1  12eb035d2a10bb9d   797  stored   subtitle
BV11p5qzAE6s:p0         5  subtitle-ai  ai-zh   1  d49cdc687f8e82de   918  stored   subtitle
BV1iddQYQE7D:p0         6  subtitle-ai  ai-zh   1  f8495cdaa306ac96  2918  stored   subtitle
SIX_WAY_SEGMENT_TOTAL: 9607        transcripts_total: 6
```

Full `content_sha256` values: `800e2de54ec7fda8cff3b2f46c9836cb0015383cf211bd8fd0deccda982709bd`,
`0bb5a5da823c1c1ffee9947c4842f9017ed90332ba12074430e799bdce4639f6`,
`e80f72b455be055c8ada26d49e2e71ba2aa68b19ef470f1937c6aedbc944d294`,
`12eb035d2a10bb9dd500321716c811edfc49c9f86235517f9056d5ed6255aa96`,
`d49cdc687f8e82de4a28d1112ae656f04a293e2b5cc2a4e56a35ff28d30e41e5`,
`f8495cdaa306ac963ea78dcbda63f7b27143dbddf3d460f8992d72dde597371c`.

**Which track the default language selection picked for item 1, and why.** The default `--language`
is, verbatim from `harvest-subs --help`, "the zh family, then en, CC before AI". Item 1 offers six
tracks — `ai-zh`, `ai-en`, `ai-ja`, `ai-es`, `ai-ar`, `ai-pt` — of which only **`ai-zh`** is in the
zh family, so first-match-wins selects it before the preference ever reaches the en family; there
are no CC tracks to outrank it. The command recorded `language: 'ai-zh'` (the upstream code, not
`zh`). All six items therefore stored `ai-zh`, 9607 segments in total.

### A4 — the six are excluded from the derived queue

```bash
cd <product> && /root/gpu-venv/bin/bili-asr derive-manifest --archive-root /root/e2e-asr/subtitle-publish
# (84 × "<work_id>: needs_audio (duration_s=…)")
# derive-manifest: queue=84 derived=84 already_derived=0 chain_owned=0 identity_mismatch=0
# DERIVE_EXIT_1=0
cd <product> && /root/gpu-venv/bin/bili-asr derive-manifest --archive-root /root/e2e-asr/subtitle-publish
# derive-manifest: queue=84 derived=0 already_derived=84 chain_owned=0 identity_mismatch=0
# DERIVE_EXIT_2=0
```

`queue=84 / derived=84 / already_derived=0 / chain_owned=0 / identity_mismatch=0` then
`queue=84 / derived=0 / already_derived=84 / chain_owned=0 / identity_mismatch=0`.

```text
derived_count= 84            store_pending_count= 84        (v_pending_subtitles)
derived_minus_store= []      store_minus_derived= []
SETS_EQUAL= True
six_absent_from_derived= True            six_present_in_derived= []
six_absent_from_store_pending= True      six_present_in_manifest_any_state= (none)
manifest_row_keys= [bvid, cid, duration_s, page_index, pubdate, pubdate_str, status, title, work_id]
total_rows= 84  (all status=needs_audio)
store_pending_sql_predicate_count (status<>'gone' and no transcript) = 84
```

Idempotence: `manifest.jsonl` = 22405 B, `sha256 7237ec1c42c338c58d5a15fb07f06c6b5c3e8d316c807df89bfa3a3c2cb3f875`
and mtime `19:18:01.669825800` — **identical after invocation 1 and invocation 2**, so the second run
added nothing. Derived rows carry `"status":"needs_audio"` (there is no `state` key in a manifest row).

### A5 — publication to the WebDAV artifact root

```bash
for B in BV1BdtazGEBE BV1Y7M4zNEfF BV1vNTqzFEve BV1zz5zzFENq BV11p5qzAE6s BV1iddQYQE7D; do
  cd <product> && /root/gpu-venv/bin/bili-asr publish-transcripts --bvid ${B}:p0 \
    --archive-root /root/e2e-asr/subtitle-publish \
    --artifact-root /mnt/123pan/bili-asr-e2e/subtitle-publish
done
# BV1BdtazGEBE:p0: published (source=subtitle-ai lang=ai-zh version=1 cues=2318) transcripts/md/2025-08-09_…
# publish-transcripts: candidates=1 published=1 already_published=0 failed=0        exit=0   (1.364 s)
# BV1Y7M4zNEfF:p0: … cues=947   candidates=1 published=1 … failed=0   exit=0   (0.377 s)
# BV1vNTqzFEve:p0: … cues=1709  candidates=1 published=1 … failed=0   exit=0   (0.383 s)
# BV1zz5zzFENq:p0: … cues=797   candidates=1 published=1 … failed=0   exit=0   (0.324 s)
# BV11p5qzAE6s:p0: … cues=918   candidates=1 published=1 … failed=0   exit=0   (0.369 s)
# BV1iddQYQE7D:p0: … cues=2918  candidates=1 published=1 … failed=0   exit=0   (0.376 s)
cd <product> && /root/gpu-venv/bin/bili-asr publish-transcripts \
    --archive-root /root/e2e-asr/subtitle-publish --artifact-root /mnt/123pan/bili-asr-e2e/subtitle-publish
# (each of the six) already_published
# publish-transcripts: candidates=6 published=0 already_published=6 failed=0          exit=0   (0.090 s)
```

`cues=` in that line matches the stored segment count per row, so the projection is faithful.

**Products under `/mnt/123pan/bili-asr-e2e/subtitle-publish` (artifact root) — byte size and
`sha256` recomputed from the on-disk bytes** (24 files + 6 markers = 30):

```
md/2025-08-09_BV1BdtazGEBE.p0_【哲学与现实】爱情升级指南——当你说“我爱你”时，你到底在怎说什么.md
     68994  4088ed319cbae04c4326fe19a9455299fa380e620214b76ecc4ec97fb8dc1d7e
md/2025-06-15_BV1Y7M4zNEfF.p0_【行动指南】从爱情走向革命.md
     30468  af350f2f3d0786f2790b37edaa816db3d38a7513a8e05f8432efbfaa04703fd0
md/2025-06-09_BV1vNTqzFEve.p0_【爱欲经济学】爱情的阶次和解放.md
     51043  9c7c6ab40930d3e57a17b019ab2d278828255baec8c1775d9bf21a16aabea657
md/2025-04-17_BV1zz5zzFENq.p0_【历史唯物主义】革命与爱情.md
     25502  9911e083ddc46f7317cc61f2a7772424822984b96bebe314734ea00271d646d3
md/2025-04-17_BV11p5qzAE6s.p0_【实事求是】被迫配种的本已是囚，革命者应该如何恋爱.md
     28294  26a0adaa77e653363ce46f96a22880b156c894cb8647a19d823c8f46d4f88380
md/2025-04-11_BV1iddQYQE7D.p0_【随便聊聊】普通人如何扬弃性的压抑，革命者如何扬弃爱的压抑.md
     86462  fdc59280814fbebd1af91c992cbc7c1bd26940bd414fa3f003f1928e282f82d3
srt/BV1BdtazGEBE.p0.srt   151028  7a3044ed5dff3ca0fc14332671b827bcd7f8893afb759899b57ec9992acb7de6
srt/BV1Y7M4zNEfF.p0.srt    63258  19e5872771f59c7a5f44e727c06b059fd74e7f6720c9fde91063e1a94131e6dc
srt/BV1vNTqzFEve.p0.srt   111207  a902ca92c80cfcc76180949e8969a009c9d73273a24d8dc0209dd1c09488a3a8
srt/BV1zz5zzFENq.p0.srt    53042  b038d4f2787f9e2531296e53c5ef7ebd5a0651b5b5fdbcd70a5d339d7749b4d3
srt/BV11p5qzAE6s.p0.srt    60033  fff2a3f2e43acb5f9481addc38924ed8212329e9f20e179aba7098337bafc1af
srt/BV1iddQYQE7D.p0.srt   190108  8a1ad1ab6c9c25c7f0b4df9c9b63c0ad0d0d1065adbf0a882df8ccb0807da972
txt/BV1BdtazGEBE.p0.txt    68688  c8aede8d11b6406d99b012962fb22b69c5403efe48a9e97145c2c94b07948ad3
txt/BV1Y7M4zNEfF.p0.txt    30222  9f78f20958679b80916863065e3ee347689962cf7d747c96a114f67c76040579
txt/BV1vNTqzFEve.p0.txt    50791  cd5f7109fc8bf334fc37e1c1fe959b30e3b722d4d0f65d94116e45a964f9118a
txt/BV1zz5zzFENq.p0.txt    25256  c5af56404f45da20f2ca65eff6a87d1ee6289066a94a19448671b7b43dca758a
txt/BV11p5qzAE6s.p0.txt    28012  defbcc79a27a2286729e76c72be42015d9bcf6aaf062cf2a2e0bbd0700b8d4d7
txt/BV1iddQYQE7D.p0.txt    86168  4ea186fe5d3b04bb6777b2af50de184a044c02903d96e6389dab46f1f2859ed4
raw/BV1BdtazGEBE.p0.json  241841  05ec43be74928670662769c0ee8a0a01caca685c0fec9720da6b6ab07fa36990
raw/BV1Y7M4zNEfF.p0.json  100614  e650a2c0f8316dcf4717b192e2e4a81f1f21cc0d344b070f2da58536ad6906d8
raw/BV1vNTqzFEve.p0.json  178213  0ee4bd2bb25710b69638797ceea4ab8e2585faadf24b6b84c8c64146f5cfed7b
raw/BV1zz5zzFENq.p0.json   84397  0c3e89896e7619663865910d0c3a3b13ce68c3d89a9b89e8d25eed7a852dbfda
raw/BV11p5qzAE6s.p0.json   96251  c8a4cc8958ec041d5f6c89c4b1e92c04cfd78cccef83caec3c6d833d80668d14
raw/BV1iddQYQE7D.p0.json  304334  8ae784458d708b0ad76644b944a1806ca89b8adfb99904457b5bbb270549ef62
srt/BV1BdtazGEBE.p0.srt.bundle-ready    789  65d4238d896120d8e6d55ce9486f2b17fcca31456b746652cb8be52c8f0747fd
srt/BV1Y7M4zNEfF.p0.srt.bundle-ready    669  3cdf5099f564750f9fded2badba53dc8083e9f6c3f2ae910902040f09c49f5b2
srt/BV1vNTqzFEve.p0.srt.bundle-ready    681  10285d7eaead6515d1d1120aecdb1d7add332041d883439d0453cb78fa2c0cb2
srt/BV1zz5zzFENq.p0.srt.bundle-ready    669  9b84de3d40d0a022130e434fc98034ad11c9707779a0fb129a549246bf3cfd31
srt/BV11p5qzAE6s.p0.srt.bundle-ready    741  1d96ee918b800f398ec62041daf0c1f14b7176cabe00eafaa564aec20ede1fd2
srt/BV1iddQYQE7D.p0.srt.bundle-ready    765  d1180ab7d14410571ba8948fd9633757fb1e0aa123ed081a172c3930a6a60fc0
```

**Bundle sha256** — the `.bundle-ready` marker *is* the bundle record: `schema: archive-bundle-v1`,
`artifacts.{srt_path,txt_path,md_path,raw_path}.{path,sha256}`. For all six rows the four recorded
hashes equal the four recomputed on-disk hashes (verified programmatically, per row, on the WebDAV
copies and again on the local A7(iii) copies), so **24/24 recorded == recomputed**.

Archive root after A5 — **state only**, no product family anywhere beneath it:

```
/root/e2e-asr/subtitle-publish/archive.db                     782336
/root/e2e-asr/subtitle-publish/coordinator/archive-writer.lock      0
/root/e2e-asr/subtitle-publish/manifest/manifest.jsonl            25753   (90 rows = 84 needs_audio + 6 archived)
/root/e2e-asr/subtitle-publish/manifest/manifest.jsonl.lock          0
(find … -name '*.srt' -o -name '*.txt' -o -name '*.md' -o -name '*.json' -o audio -o '*.bundle-ready' → no output)
```

A sample `archived` row (item 1) records all four relative product paths, status `archived`, source
`subtitle-ai`, `language: ai-zh` — one such row per publication, six in total.

### A6 — the archive's own readers

```bash
cd <product> && /root/gpu-venv/bin/bili-asr verify --archive-root /root/e2e-asr/subtitle-publish \
    --artifact-root /mnt/123pan/bili-asr-e2e/subtitle-publish --trusted-local
# {"authoritative": false, "checked": 90, "defect_count": 84,
#  "defects": [{"code": "retryable_incomplete", "work_id": "BV11EYEzZEvA:p0"}, … 84 entries …],
#  "diagnostics": ["missing_attempts_sidecar"]}                                 VERIFY_EXIT=1
cd <product> && /root/gpu-venv/bin/bili-asr coverage --archive-root /root/e2e-asr/subtitle-publish \
    --artifact-root /mnt/123pan/bili-asr-e2e/subtitle-publish --trusted-local --quality
# {"denominator":{"count":90,…}, "rows":[…90 rows…],
#  "summary":{"artifact_missing":84,"duplicate_cue":5,"empty":0,"fragment_cue":6,"identity_mismatch":0,
#             "leading_mark":0,"low_confidence":0,"malformed":0,"non_monotonic":0,"out_of_range":0,
#             "overlap":0,"overlong_cue":0,"reference_disagreement":0,"repeated_ngram":5,
#             "total_cues":19214,"total_work_items":90,"valid_work_items":6}}      COVERAGE_EXIT=1
cd <product> && /root/gpu-venv/bin/bili-asr search "爱情" \
    --archive-root /root/e2e-asr/subtitle-publish --artifact-root /mnt/123pan/bili-asr-e2e/subtitle-publish --limit 3
# BV1Y7M4zNEfF:p0: 【行动指南】从爱情走向革命 [archived] (score: -0.9133, path: transcripts/txt/BV1Y7M4zNEfF.p0.txt)
# BV1BdtazGEBE:p0: 【哲学与现实】爱情升级指南——当你说“我爱你”时，你到底在怎说什么 [archived] (score: -0.4978, …)
# SEARCH_EXIT=0
cd <product> && /root/gpu-venv/bin/bili-asr export --format json --status archived \
    --archive-root /root/e2e-asr/subtitle-publish    > …/a6-export-archived.json     EXPORT_EXIT=0  (3927 B)
```

Defect isolation (parsed from the `verify` JSON, not eyeballed):
`checked=90, defect_count=84, authoritative=false, defect_codes=['retryable_incomplete'],
defects_on_the_six=[], ZERO_DEFECTS_ON_THE_SIX=True` — the 84 defects are exactly the 84
`needs_audio` rows that hold no transcript yet. The six archived rows carry **no defect**.

`coverage` rows for the six (`artifact_count=4`, `language=ai-zh`, `source=subtitle-ai`,
`status=archived`), cue counts `1836 / 4636 / 1894 / 5836 / 3418 / 1594` — note each is exactly
**2 ×** that row's stored segment count (see F-3):

```
BV11p5qzAE6s:p0 artifact_count=4 cue_count=1836 lang=ai-zh reasons=[fragment_cue,duplicate_cue,repeated_ngram]
BV1BdtazGEBE:p0 artifact_count=4 cue_count=4636 lang=ai-zh reasons=[fragment_cue,duplicate_cue,repeated_ngram]
BV1Y7M4zNEfF:p0 artifact_count=4 cue_count=1894 lang=ai-zh reasons=[fragment_cue,duplicate_cue,repeated_ngram]
BV1iddQYQE7D:p0 artifact_count=4 cue_count=5836 lang=ai-zh reasons=[fragment_cue,duplicate_cue,repeated_ngram]
BV1vNTqzFEve:p0 artifact_count=4 cue_count=3418 lang=ai-zh reasons=[fragment_cue,duplicate_cue,repeated_ngram]
BV1zz5zzFENq:p0 artifact_count=4 cue_count=1594 lang=ai-zh reasons=[fragment_cue]
```

`search --work-id BV1BdtazGEBE:p0 --format json` (exit 0) returned a real `transcript_snippet` from
the published row (`…交叉上升的我们开始来讨论这个 要就是这这都是你的爱情的发生点位…`), i.e. the
published text is searchable, not just its metadata. `export --format json --status archived` —
`export_rows: 6`, `export_work_ids: ['BV11p5qzAE6s:p0','BV1BdtazGEBE:p0','BV1Y7M4zNEfF:p0',
'BV1iddQYQE7D:p0','BV1vNTqzFEve:p0','BV1zz5zzFENq:p0']`, `export_lists_exactly_the_six: True`,
`all_status_archived: True`.

Per-row family/marker consistency and recomputation (assertion script over the manifest rows):
`archived_manifest_rows: 6`, `ALL_SIX_BUNDLES_CONSISTENT: True`,
`artifact_root_file_count: 30 (24 non-marker)`, for every row
`paths_under_artifact_root: True`, `marker: True`, `recorded==recomputed sha256: {srt,txt,md,raw}=True`.

### A7 — artifact-root boundary on the publication path

**(i) missing artifact root refuses and writes nothing**

```bash
cd <product> && /root/gpu-venv/bin/bili-asr publish-transcripts --bvid BV1zz5zzFENq:p0 \
    --archive-root /root/e2e-asr/subtitle-publish \
    --artifact-root /root/e2e-asr/subtitle-publish/nonexistent-artifact-root
# publish-transcripts: artifact root does not exist (/root/e2e-asr/subtitle-publish/nonexistent-artifact-root)
# NONEXISTENT_ROOT_EXIT=1
ls -la …/subtitle-publish/nonexistent-artifact-root   # No such file or directory        exit=2
manifest_lines_before=90   manifest_lines_after=90   artifact_root_file_count_after=30
```

The probe path was deliberately chosen **inside an authorized root** so that even a misbehaving
product could not write outside the run's named roots; the contract held and nothing was created.

**(ii) nothing outside the artifact root after A5**

The archive root holds only state (listing in A5 above). Entries modified under `/root/e2e-asr`
since the run start were only `logs/` and `subtitle-publish/`; the only additions under
`/mnt/123pan/bili-asr-e2e` were the artifact root's own contents (`longform-pair`, a prior run's
root, has mtime 2026-09-20 and was untouched). `git status --porcelain` of the target checkout was
re-checked here and still reads exactly `?? .env-bak…` → `?? .env.bak-20260917-181947`.

**(iii) wall time — WebDAV vs a local artifact root**

| Measurement | Root | Row | Files | Bytes | Wall time |
|---|---|---|---|---|---|
| Publication, item 1 (first write; creates the 4 family directories) | WebDAV `/mnt/123pan/…` | `BV1BdtazGEBE:p0` | 5 | 530809 | 1.364 s |
| Publication, items 2–6 | WebDAV | one row each | 5 each | 188–412 KB | 0.377 / 0.383 / 0.324 / 0.369 / 0.376 s |
| Publication, full set (already published) | WebDAV | 6 rows | — | — | 0.090 s |
| **Local-artifact-root sample** | `/root/e2e-asr/subtitle-publish/artifact-local` | `BV1zz5zzFENq:p0` | 5 | 188033 | **0.081 s** |
| Repeat of that sample (already published) | local | `BV1zz5zzFENq:p0` | — | — | 0.059 s |
| `dd` 1 MiB write to the mount | WebDAV | — | — | 1048576 | 0.00199 s (526 MB/s) |

What was measured, exactly: per-row wall time of the `publish-transcripts` process (`date +%s.%N`
around the command), same row, same store, WebDAV vs local root — a **~4× penalty on a 188 KB bundle**
(`0.324 s` vs `0.081 s`), while bulk `dd` throughput on the mount is unremarkable. The five local
copies are **byte-identical** to the WebDAV copies (sizes and all five `sha256` equal, e.g. srt
`b038d4f2…`, raw `0c3e8989…`, marker `9b84de3d…`), so the timing difference is mount latency, not a
different amount of work. `LOCAL_PUBLISH_EXIT=0`, and the local re-run printed `already_published`.
Creating that local root is disclosed in the Scope corrections (item 2) and in F-2.

### A8 — re-publication is inert

```bash
sha256sum …/manifest/manifest.jsonl   # before: cce9493197c001a92450d9b42fab9578bf79b9b569cff9c719d3b240ccb69f04
find … -printf '%T@ %s %p\n' | sort -k3 > a8-before.mtimes ; find … | xargs sha256sum > a8-before.sha256
cd <product> && /root/gpu-venv/bin/bili-asr publish-transcripts \
    --archive-root /root/e2e-asr/subtitle-publish --artifact-root /mnt/123pan/bili-asr-e2e/subtitle-publish
# BV11p5qzAE6s:p0: already_published / BV1BdtazGEBE:p0: already_published / BV1Y7M4zNEfF:p0: already_published
# BV1iddQYQE7D:p0: already_published / BV1vNTqzFEve:p0: already_published / BV1zz5zzFENq:p0: already_published
# publish-transcripts: candidates=6 published=0 already_published=6 failed=0       PUBLISH_FULLSET_2ND_EXIT=0 (0.107 s)
sha256sum …/manifest/manifest.jsonl   # after:  cce9493197c001a92450d9b42fab9578bf79b9b569cff9c719d3b240ccb69f04
head -0 ; diff a8-before.sha256 a8-after.sha256 && echo SHA256_SET_IDENTICAL: yes
diff a8-before.mtimes a8-after.mtimes && echo MTIME_SET_IDENTICAL: yes
```

`manifest_lines 90 → 90`, `archived_rows 6 → 6`, whole-file hash identical, **all 30 file sha256 and
all 30 mtimes identical**. Newer-version clause: each of the six work_ids has exactly **one**
transcript, `version = 1` (`any_work_id_with_more_than_one_transcript_version: False`), so no newer
version exists and that clause is `not-run` — no case was invented.

### Positive boundary checks

* `git -C /root/workspace/bilibili-asr-archive rev-parse HEAD` → `37b0acce…` (unchanged), and
  `git status --porcelain` → `?? .env.bak-20260917-181947` at A0, after A5, and at the end of the
  run: **identical to the A0 baseline**, so no tracked product file was modified.
* Honest side effect: executing the CLI regenerated Python byte-code caches — the only paths under
  the checkout with a post-start mtime were
  `bilibili-asr-archive/src/bili_asr/__pycache__/{archive,export,search_index}.cpython-312.pyc`,
  `.pyc` files that are untracked/ignored and are not source. No file under `src/`, `tests/`,
  `docs/` was edited; no `.mstar/` state, `status.json` or `snapshot.json` was written by ops.
* Writes stayed inside the two named roots plus `/root/e2e-asr/logs/`; nothing was written to
  `/mnt/e` or to `/root/workspace`, and nothing under them was deleted. (The one file ops removed was
  its own 1 MiB `dd` throughput probe inside the artifact root, created and deleted in the same
  step purely to characterise the mount.)
* No `download-audio`, `asr`, `run`, `schedule`, `campaign` or `pilot` was invoked; no audio was
  downloaded and no GPU transcription was run. No `pytest` was run and the local test suite was not
  executed.

## Findings and handoff

Four findings: one scenario failure (F-1) and three surprises (F-2…F-4). Each is routed to a bounded
follow-up. **No product repair was performed inside this workflow** — no source file, test, spec,
knowledge doc, git object or harness state was modified; the only repo write is this report.
Retesting, if it happens, belongs to this same workflow on its authorized scenarios only.

### F-1 — `check-asr-env` fails in the default shell: `HSA_ENABLE_DXG_DETECTION=1` is not persisted *(severity: medium; the A1 failure)*

* **Impact.** The host capability exists and is proven, but the check that is supposed to certify it
  returns non-zero from an ordinary shell. Anything launched from a plain shell (including any future
  `asr` / `run` / `schedule` work on this box) reaches the HIP runtime without the DXG transport and
  will fail `device-probe`; the audio→ASR branch is exactly where that bites. It also means
  `check-asr-env` cannot serve as a bare pass/fail gate today, and it is a *different* mechanism from
  the cwd fragility the Scope attributed to A1 — cwd was correct throughout this run.
* **Reproduction.**
  `cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && /root/gpu-venv/bin/bili-asr check-asr-env` → exit 1;
  the same line prefixed with `HSA_ENABLE_DXG_DETECTION=1` → exit 0 with
  `device ok name=AMD Radeon RX 7800 XT arch=gfx1101 vram_gb=15.8`. `grep -n HSA /root/.bashrc` → no
  match, while `docs/wsl-rocm-gpu.md` line 291 instructs persisting that exact line.
* **Evidence.** `/root/e2e-asr/logs/subtitle-publish-20260922T111639Z/02-a1.log`,
  `…/02b-a1-retry.log`; failed checks reproducible in one command.
* **Suggested bounded follow-up owner.** **Operator / ops on the host** (host configuration, not
  product code): persist `export HSA_ENABLE_DXG_DETECTION=1` per recipe step 8 and re-run
  `check-asr-env` once. A product-side question worth only a note, not a repair: whether the check
  should detect and report the unset variable as *environment-not-configured* rather than as a
  capability failure — for the PM to route as a documentation/UX item if it matters.
* **Does not block anything else.** None of A2–A8 needs the GPU, and all eight ran to completion.

### F-2 — an `archived` manifest row does not identify its artifact root; publishing to a second root appends a byte-identical duplicate *(severity: low-medium)*

* **Impact.** The manifest is the archive's index of record, but a row carries only *relative*
  product paths (`transcripts/srt/…`) and no artifact root. Consequently, one publication to the
  WebDAV root and one to a local root produced **two byte-identical JSONL rows** for the same
  `work_id` — a reader cannot tell which root a row describes, and row counts no longer equal
  published works. Idempotence is effectively per `(work_id, artifact_root)` while the row schema can
  only express `work_id`. This surfaced only because A7(iii) required a second root; it is not an
  artifact of the six items.
* **Reproduction.**
  `publish-transcripts --bvid BV1zz5zzFENq:p0 --archive-root /root/e2e-asr/subtitle-publish --artifact-root /mnt/123pan/bili-asr-e2e/subtitle-publish`
  then the same command with `--artifact-root /root/e2e-asr/subtitle-publish/artifact-local`.
  Both exit 0 with `published=1`; `grep '"work_id":"BV1zz5zzFENq:p0"' manifest.jsonl` returns two
  rows, `byte_identical_rows: True`, `row_carries_artifact_root: False`. (Second run against the same
  root is correctly inert — `already_published=1`.)
* **Evidence.** `…/12-a7iii.log` (the 7th row appended, `manifest_lines 90 → 91`),
  `…/13-final-evidence.log` §F2 (`rows_for_this_work_id: 2`, identical).
* **Suggested bounded follow-up owner.** **PM → dev**, as a scoped plan on the transcript-projection /
  manifest surface: decide and encode whether the artifact root belongs in the row, or whether
  duplicate rows for one `work_id` are simply disallowed. Bounded ask: one design decision + the
  smallest test that pins it. Not a repair inside this workflow.

### F-3 — `coverage --quality` `cue_count` is exactly 2× the stored segment count *(severity: low; telemetry surprise)*

* **Impact.** All six rows report double their segment count (1836/4636/1894/5836/3418/1594 vs
  918/2318/947/2918/1709/797), and `summary.total_cues = 19214 = 2 × 9607`. Any consumer that reads
  `cue_count` as "cues in this transcript" will double-count. Either two cue-bearing families (`srt`
  + `md`) are summed without saying so, or one family is counted twice; the current output does not
  distinguish them. Harmless to this run's acceptance clauses.
* **Reproduction.** `coverage --archive-root … --artifact-root … --trusted-local --quality` and
  compare each row's `cue_count` with `select count(*) from transcript_segments` for that row.
* **Evidence.** `…/08-a6a.log` (coverage JSON), `…/04b-a3-assert.log` (segment counts).
* **Suggested bounded follow-up owner.** **PM → dev**: confirm whether summing cues across families
  is intended; if yes, document it in the output (e.g. per-family counts) — if no, one focused fix.

### F-4 — `verify` / `coverage` exit 1 on a store that legitimately holds unprocessed rows, and `verify` reports `missing_attempts_sidecar` *(severity: low; interpretation risk)*

* **Impact.** Both readers exited **1** here, purely because of the 84 `needs_audio` rows that hold no
  transcript yet (all defects are `retryable_incomplete` against those rows; valid items = 6). For
  an operator or CI gate that keys on the exit code, a partially-processed — but entirely healthy —
  store reads as a failure. `verify` additionally emits the diagnostic `missing_attempts_sidecar`,
  whose subject row was not determined in this run. The six published rows are defect-free, so A6's
  clauses hold; this finding is about the exit-code/summary signal, not about the six.
* **Reproduction.** `verify --archive-root … --artifact-root … --trusted-local` → `defect_count: 84`,
  `authoritative: false`, exit 1; `coverage … --quality` → `artifact_missing: 84`, exit 1.
* **Evidence.** `…/08-a6a.log`, `…/13-final-evidence.log` §F1
  (`defects_on_the_six: []`, `ZERO_DEFECTS_ON_THE_SIX: True`).
* **Suggested bounded follow-up owner.** **PM** (decision, not repair): whether a partially-processed
  store should be exit 0 with the defect detail in the payload; if yes, that is a bounded dev item.

Nothing else surprised the run. In particular the PM's locked premise held exactly — all six took
the subtitle branch, all six stayed out of the derived queue, and no item reached the audio chain.

## Not verified

Stated in this run's own words, and additional to the PM's pre-declared exclusions.

* **The audio→ASR branch was not exercised at all.** No item among the six entered the derived queue
  (A4 asserts all six absent from both the derived set and the store's pending set), no audio was
  downloaded, no transcription ran, and nothing reached the artifact root by way of ASR. The
  subtitle→publication chain is therefore verified end to end **only** on its subtitle path. Because
  the ASR path was not exercised, **residual `e2e-23191782-longform-pair-webdav · R2` stays open** —
  this run does not close it, does not weaken it, and provides no new evidence either way about it.
  A1 additionally shows that the ASR path on this host would fail from a plain shell (F-1), which is
  a reason to keep that residual open, not a reason to close it.
* PM pre-declared exclusions, all confirmed as not exercised: GPU transcription, `download-audio`,
  channel **pages 1–3** (never re-probed in this run — out of scope), the project's **full local test
  suite** (not authorized; **no `pytest` was run at all**), and any behaviour specific to a **wheel /
  non-editable install** (only the editable install was used).
* **A8's newer-version clause is `not-run`.** No work_id holds more than one transcript version, so
  the documented "a store that later gains a newer transcript version leaves the published product
  as it is" contract could not be observed; nothing was invented to force it.
* Enumerated window is bounded: **3 pages / 90 parts**, not the channel's `observed_total = 1691`.
  Conclusions about the queue (84 derived) are statements about this window, not the whole channel.
* `rate-limit behaviour` was not observed: pages 4–6 answered first try, so neither the retry path nor
  the `GatewayRateLimited` / `GatewayShapeError` handling was tested. The scope-lock note that pages
  1–3 were rate-limited is inherited context, not re-measured here.
* **Reader checks were not re-run after the A7(iii) local publication.** `verify`, `coverage`,
  `search` and `export` ran (A6) against the state produced by A5/A8's WebDAV publication; the 7th
  `archived` row created by the local comparison (F-2) appeared afterwards and was not put in front
  of those readers. Its 5 local products were checked for byte-identity only.
* A7(iii)'s local comparison is a **one-row sample** (`BV1zz5zzFENq:p0`) and its timings are single
  measurements — no repetition, no statistics, no cold/warm separation; the WebDAV figures are
  likewise single-shot per row. Treat the ~4× figure as indicative.
* `coverage`'s quality reasons (`fragment_cue`, `duplicate_cue`, `repeated_ngram` on five rows) were
  reported, not investigated — they may be intrinsic to Bilibili AI captions and are outside this
  run's scenarios.
* Not probed: `scan`/audio sidecars, concurrency (`evaluate-concurrency`), `recover`, `runs`,
  `status`, any multi-part item (all six are single-part, `page_index 0`), and any write to
  `/mnt/e`.
* Evidence limitations: the run used one host, one artifact mount, one SESSDATA source (referred to
  by path only — never read out, logged or reported), and the harness-reported clock of the target
  host; no external time source was cross-checked beyond UTC stamps from `date -u`.

## Completion recommendation

**Assigned 9 / determinate 9 / passed 8 / failed 1 / not-run 0 / blocked 0.**

Every assigned scenario has exactly one determinate outcome carried by commands with their exit codes
and observed output; every product claim is backed by a path with a byte size and a `sha256`
recomputed from the on-disk bytes (24 products + 6 markers, plus the 5-file local sample); nothing
was written outside the two named roots plus the log directory; the target checkout's
`git status --porcelain` is identical to A0's baseline; and the audio→ASR branch was not exercised,
so `e2e-23191782-longform-pair-webdav · R2` stays open.

**Product verdict (separate from lifecycle):** the delivered feature under test —
`publish-transcripts` + the transcript projection — **behaves as specified** on this store: all six
items were enumerated, acquired as `subtitle-ai`/`ai-zh`, correctly excluded from the derived audio
queue, published as complete four-family bundles with markers to the WebDAV artifact root, reported
consistently by the archive's own readers, refused cleanly on a missing artifact root, and inertly
re-published on a second run. The single scenario failure is **a host environment precondition outside
the product's publication path** (F-1) and it blocked nothing in this run.

**Lifecycle recommendation to the PM:** treat this verification run as **execution-complete** (all
nine scenarios determinate, evidence complete) and take the report to `InReview` acceptance; the PM
alone marks the plan `Done` and closes the workflow. Open handoffs, none of which is a repair inside
this workflow:

1. F-1 → operator/ops, host configuration (`HSA_ENABLE_DXG_DETECTION=1` persisted), one re-check.
2. F-2 → PM-routed bounded dev plan on manifest/artifact-root attribution (design decision first).
3. F-3, F-4 → PM decisions on coverage telemetry and on the exit-code signal; dev only if the PM
   decides a change is wanted.
4. Keep residual `e2e-23191782-longform-pair-webdav · R2` open; this run adds no closure.
5. If a retest is ever wanted, it belongs to this workflow's authorized scenarios only — and any
   attempt to exercise the audio→ASR branch needs a fresh scope lock, new authorization, and items
   that actually lack live captions.
