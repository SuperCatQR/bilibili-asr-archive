# E2E Verification Report — 未明子 long-form pair through the ASR chain (fresh root, WebDAV artifact root)

> **Workflow:** `e2e-23191782-longform-pair-webdav` (`type: plan`, verification-only)
> **Status:** scope locked by PM 2026-09-20; execution owned by `ops-engineer`
> **Executor:** `ops-engineer` (PM orchestrates; ops executes and records actual results)
> **This file is the plan AND the report.** PM writes `## Scope` … `## Acceptance criteria`;
> ops fills `## Results`, `## Evidence`, `## Findings and handoff`, `## Not verified`,
> `## Completion recommendation` with what actually happened.

## Scope

- **Workflow / plan:** `e2e-23191782-longform-pair-webdav` — an independent E2E verification
  workflow (`mstar-e2e`), not an iteration phase, not a development plan, not a QA gate.
  Scenarios A0–A8 below are the workflow's plan rows.
- **User authorization and permitted side effects.** Direct operator request 2026-09-20:
  “确认一下项目的状态，计划一次对未明子 2个长视频的e2e测试”. Four choices were put to the
  operator and answered the same day: (1) container = **standalone E2E workflow** (option A);
  (2) items = **one long + one medium** (option B): `BV1vVDKBvEqL:p0` (129.4 min) and
  `BV1iMGL6KE9J:p0` (89.4 min) ≈ 3.65 h of audio; (3) products to the **WebDAV artifact root**
  `/mnt/123pan` (option B — this is also the trigger recorded on residual `iter-2026-09-artifact-root · R2`);
  (4) a **fresh archive root following the full documented operator sequence** (option A).
  Permitted: enumerate metadata for UID 23191782 on the target host, acquire subtitles for the
  two named parts, download their audio, transcribe on the target GPU, write the archive root
  (state) and the artifact root (products) on the target host, read the working session cookie
  from its existing location. **Not permitted and not to be done:** any product-code change on
  the target for the run itself, production/deployment changes, destructive cleanup outside the
  named roots, media redistribution, running the project's full local test suite (not
  authorized — this run supplies its own evidence).
- **Target build / ref.** Target checkout `/root/workspace/bilibili-asr-archive` is at
  `ef5e1e8` (2026-09-17) and does **not** contain `derive-manifest` or `--artifact-root`.
  It must be fast-forwarded to the pad's current `main` (`f22bafd`) — see A0. The delivered
  features under test are the two most recent iterations: the configurable artifact root
  (`iter-2026-09-artifact-root`) and the store→manifest queue bridge
  (`iter-2026-09-queue-bridge`, `bili-asr derive-manifest`).
- **Actual environment / device / session.** Target WSL2 `DESKTOP-HHFROLO` on the Windows
  compute box (192.168.3.21), AMD Radeon RX 7800 XT (gfx1101), interpreter `/root/gpu-venv`
  (the pair `check-asr-env` verifies), product invoked as
  `PYTHONPATH=<product>/src /root/gpu-venv/bin/python -m bili_asr …`.
  Archive root (state, local disk): `/root/e2e-asr/longform-pair`.
  Artifact root (products, network mount): `/mnt/123pan/bili-asr-e2e/longform-pair`.
  Logs: `/root/e2e-asr/logs/longform-pair-<UTC-stamp>/`.
- **Assigned scenario IDs:** A0–A8.

### Item identification (provenance of the two `work_id`s)

Both items belong to UID 23191782's season 7686105 (合集·哲学进阶). They were identified on
2026-09-20 from the **previous** run's manifest at `/root/e2e-asr/e2e50` on the target host
(effective row per `work_id`, 39 rows: 14 `archived`, 24 `needs_audio`, 1 `audio_ok`):

| `work_id` | Duration | Title (as recorded in that manifest) | Status there |
|---|---|---|---|
| `BV1vVDKBvEqL:p0` | 129.4 min (7766 s) | 【哲学进阶】现代哲学《第一哲学沉思录》第六讲 第三个沉思（3） | `needs_audio` |
| `BV1iMGL6KE9J:p0` | 89.4 min (5364 s) | 【哲学进阶】黑格尔《逻辑学》第十一讲 存有论（11）作为对整体谎言进行揭穿的实情 | `needs_audio` |

That manifest is the *old* root's state and is not an input to this run: the fresh root
re-derives everything through the shipping commands (A2/A3), which is also where the identity of
both `work_id`s is confirmed against live metadata. If a live title or duration differs from the
line above, the live value wins and the difference is recorded as evidence — it would mean the
stored identification was stale.

### Assigned scenarios

| ID | Scenario | Expected |
|---|---|---|
| **A0** | Target build identity | Checkout fast-forwarded from `ef5e1e8` to the pad's current `main` via a thin `git bundle` (prerequisite `ef5e1e8`, ≈510 KB) pushed over the ssh channel; afterwards `git log --oneline -1` names that tip and `grep -c derive-manifest src/bili_asr/cli.py` > 0; `git bundle verify` exit 0 on the transferred file |
| **A1** | Host self-check | `bili-asr check-asr-env` exits `0`; the device line names the RX 7800 XT / gfx1101 |
| **A2** | Fresh root bootstrap | `fetch-meta --mid 23191782 --archive-root /root/e2e-asr/longform-pair` completes; `archive.db` exists and holds the enumerated video/part rows; a second invocation is resumable |
| **A3** | Subtitle acquisition for the two parts | `harvest-subs --bvid BV1vVDKBvEqL:p0` and `--bvid BV1iMGL6KE9J:p0` each exit `0` and record a determinate outcome in the store (a stored transcript, or an attempted-with-no-caption row) — either outcome is a determinate result, not a failure |
| **A4** | The bridge produces the queue | `derive-manifest --archive-root …` exits `0`; the derived `work_id` set equals the store's `v_pending_subtitles` set for that root; both target `work_id`s are present with a **positive integer `duration_s`** and `status: needs_audio`; a second invocation leaves the effective row per `work_id` unchanged |
| **A5** | Item 1 through the chain, products on WebDAV | `download-audio --missing-subs --bvid BV1vVDKBvEqL:p0 --artifact-root /mnt/123pan/bili-asr-e2e/longform-pair` then the ASR stage for the same work_id reach `archived`; four artifacts (`raw`/`txt`/`md`/`srt`) plus `.bundle-ready` land **under the artifact root**; state (`archive.db`, `manifest/`, `coordinator/`) stays in the local archive root |
| **A6** | Item 2 through the chain | Same acceptance as A5 for `BV1iMGL6KE9J:p0` (89.4 min) |
| **A7** | Artifact-root behaviour on the WebDAV mount (residual R2's trigger) | Recorded, with command lines and timings: (i) the per-row audio-usage/peak measurement over the WebDAV tree and its elapsed cost; (ii) whether an unreadable/absent mount is distinguished from a measured-empty one, or **fails open**; (iii) whether the boundary validation probes a write and a directory `fsync`, or a mount that opens but rejects directory fsync passes validation and fails later with a raw error. Each of the three is a finding regardless of direction; a raw error is a legitimate observed result |
| **A8** | Archive evidence on the produced rows | `verify --trusted-local` reports **zero defects** on the archived rows; the four artifact families are mutually consistent for each row; bundle `sha256` recomputable; `coverage --quality` runs and prints the doubt surface for the run |

Outcome vocabulary is exactly `passed` / `failed` / `not-run` / `blocked`. A scenario with no
determinate evidence is `not-run` or `blocked` — never a claimed pass.

## Results

| Scenario | Expected | Actual | Outcome | Evidence |
|---|---|---|---|---|
| A0 | build fast-forwarded; `derive-manifest` present | **final.** `git bundle verify` exit 0 on the transferred file; `git merge --ff-only` → `Updating ef5e1e8..f85fe91 / Fast-forward`, exit 0; reflog `merge refs/remotes/pad/main: Fast-forward`; independent confirmation: HEAD = `f85fe91a1b9aa5ab3d07d01bef64720cc982ce5c` = `refs/remotes/pad/main` = pad `main`, `ef5e1e8` an ancestor, `grep -c derive-manifest` = **7**, `grep -c -- --artifact-root` = **13** | **passed** | Evidence §R2-A0 |
| A1 | `check-asr-env` exit 0, gfx1101 named | **final.** From the product root (the documented cwd): `check: device ok name=AMD Radeon RX 7800 XT arch=gfx1101 vram_gb=15.8 hip=7.2.26015-fc0010cf6a`, `asr-env: verified`, **exit 0**. From the login cwd and from the repo root: `no check script found`, exit 1 — a real cwd-fragility defect (finding F4) | **passed** | Evidence §R2-A1 |
| A2 | `fetch-meta` completes; store populated | **final — did NOT complete.** 6 invocations, every one exit **2**: invocation 1 `outcome=failed` (`shape_error` at page 3), invocation 2 `outcome=risk_interrupted` (`rate_limited`), a 4-attempt resume ladder all `shape_error`. Store **was** populated from pages 1–2: `archive.db` 479 232 B, 60 videos / 63 parts, **including both target parts**; a direct read-only gateway probe shows page 3 raises `GatewayRateLimited` while page 4 returns 30 videos. Cursor `next_page=3, state=ready` — resume-safe exactly as documented | **failed** | Evidence §R2-A2 |
| A3 | two `harvest-subs` runs determinate | **final.** `harvest BV1vVDKBvEqL:p0 stored subtitle-ai ai-zh v1` EXIT=0; `harvest BV1iMGL6KE9J:p0 stored subtitle-ai ai-zh v1` EXIT=0. Store: transcript 1 (part 53) **2756 segments**, transcript 2 (part 24) **1996 segments**, both `source_kind=subtitle-ai`, `language=ai-zh`, `sha256` recorded, `acquisition_attempts.outcome=stored`. Pending fell 63 → 61. This is the sanctioned determinate subtitle branch | **passed** | Evidence §R2-A3 |
| A4 | derived set == `v_pending_subtitles`; 2 rows usable; idempotent | **final — 3 of 4 clauses passed, clause 3 unmet.** Run 1 `queue=61 derived=61 already_derived=0 chain_owned=0 identity_mismatch=0`, EXIT=0; **SETS EQUAL: True** (both set differences empty); run 2 `derived=0 already_derived=61`, EXIT=0, **EFFECTIVE ROWS UNCHANGED: True**. **Clause 3 unmet:** both target `work_id`s are **ABSENT** from the queue — because A3 stored their AI captions, and the bridge's predicate is "no transcript". The bridge is correct; the clause's subject does not exist | **failed** | Evidence §R2-A4 |
| A5 | item 1 `archived`, products on WebDAV, state local | **final — did not reach `archived`.** The plan's own command, verbatim: `download-audio --missing-subs --bvid BV1vVDKBvEqL:p0 --artifact-root /mnt/123pan/bili-asr-e2e/longform-pair` → `BV1vVDKBvEqL:p0: unresolved; not assigned to a page`, **DOWNLOAD_EXIT=1**; then `asr --pending --bvid BV1vVDKBvEqL:p0 …` → same, **ASR_EXIT=1**. Artifact root holds **0 files**; state stayed local as designed. No shipped command can put a caption-bearing part back on the audio queue (checked: `derive-manifest` skips it, `_todo_for_bvid` returns `[]`, `write_archive` has no transcript-reading call site) | **failed** | Evidence §R2-A5 |
| A6 | item 2 `archived` | **final — identical to A5.** `download-audio --missing-subs --bvid BV1iMGL6KE9J:p0 …` → `BV1iMGL6KE9J:p0: unresolved; not assigned to a page`, **DOWNLOAD_EXIT=1**; `asr --pending --bvid BV1iMGL6KE9J:p0 …` → **ASR_EXIT=1**. Artifact root still 0 files | **failed** | Evidence §R2-A6 |
| A7 | three artifact-root behaviours recorded | **final — all three answered with commands.** (i) **YES, measured**: the coordinator measures `audio_dir_usage_bytes(write_base)` — the WebDAV artifact root (`coordinator.py:538`, in `_note_audio_peak`, called per row at `:546`/`:673`; twice in the schedule path at `cli.py:2979`/`:2995`). Cost: 0.39 ms empty → 0.97 ms at 200 files on WebDAV vs 0.00–0.28 ms local (3.5×–86× slower, sub-ms absolute). (ii) **YES, it fails open**: an absent/dangling/non-directory `audio/` all return **0 bytes**, identical to a genuinely empty tree — "measured empty" and "cannot measure" are indistinguishable; the *boundary* is separately fail-closed (absent/symlinked configured root → exit 1 named refusal). (iii) **NO write probe, NO fsync probe**: validation performs exactly 1 `open(O_DIRECTORY)`, **0 fsync, 0 write-mode opens** — so R2's point is confirmed; but this specific mount **accepts** directory fsync, so the predicted later raw failure does not manifest here | **passed** | Evidence §R2-A7 |
| A8 | zero defects; artifacts consistent; quality surface prints | **final — no artifacts exist to verify.** `verify --trusted-local`: `{"authoritative": false, "checked": 61, "defect_count": 61, …, "diagnostics": ["missing_attempts_sidecar"]}`, **EXIT=1**, every defect `retryable_incomplete` (= the unprocessed `needs_audio` remainder, the documented classification for unfinished work — **not** corruption). `coverage --quality`: printed, `total_work_items 61, valid_work_items 0, artifact_missing 61, total_cues 0`, EXIT=1. Four-way artifact consistency and `sha256` recomputation: **N/A — zero archived rows** | **failed** | Evidence §R2-A8 |

**Round-2 counts: assigned 9 · passed 4 (A0, A1, A3, A7) · failed 5 (A2, A4, A5, A6, A8) ·
not-run 0 · blocked 0.**

**Read this with finding F5.** The five failures are **not five product defects**. A2 is upstream
risk control on one page; A4/A5/A6/A8 all flow from a single factual change since the scope was
written — **Bilibili now serves AI captions for both named items**, so the chain correctly took its
documented "subtitles first" branch and the audio→ASR→artifact-root branch had no work to do. The
two delivered features under test were exercised and behaved as specified wherever work existed:
the `derive-manifest` bridge matched the store's queue **exactly** and was idempotent (A4), and the
artifact-root boundary/treatment was measured directly (A7).

Round 1 (`blocked` × 9, unreachable host) is preserved below as history; its rows are superseded by
the ones above.

## Evidence

Record actual commands (verbatim, including every flag), exit codes, artifact listings with byte
sizes, frontmatter excerpts, log paths and timings, and the exact text of any error. Distinguish
new evidence from reused evidence. **Never record the session cookie** — refer to
`~/.config/bili-asr/session.env` by path only.

### §E1 — Host reachability gate (NEW evidence; the one and only observed result of this run)

Constraint 1 of the assignment made this the first action and a hard gate. Verbatim probe command
(repeated unchanged every ~60 s):

    $ ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes -o ConnectTimeout=15 \
          chosenecho@192.168.3.21 "echo PROBE_OK"
    ssh: connect to host 192.168.3.21 port 22: No route to host
    EXIT=255

**30 probes, 0 successes.** Window `2026-09-20T03:38:16Z` → `2026-09-20T04:08:11Z` (29 min 55 s;
the loop's own bound is 1740 s). Every probe returned exit **255** with the identical stderr line
`ssh: connect to host 192.168.3.21 port 22: No route to host`. No probe ever reached `cmd.exe`,
`wsl`, or the target's bash — so no scenario command was sent, and **nothing was written to the
target by this run**.

Loop machine-readable log (pad, new):
`/root/workspace/bilibili-asr-archive/.tmp/e2e-longform-pair/probe-log.txt`
Loop script (pad, new): `/root/workspace/bilibili-asr-archive/.tmp/e2e-longform-pair/probe-loop.sh`

Probe timestamps, copied from the log (all `rc=255`, all `No route to host`):

    03:38:16Z  attempt=0   (pre-loop probe)      03:53:25Z  attempt=15
    03:38:41Z  attempt=1  (loop start)           03:54:28Z  attempt=16
    03:39:44Z  attempt=2                         03:55:31Z  attempt=17
    03:40:47Z  attempt=3                         03:56:34Z  attempt=18
    03:41:51Z  attempt=4                         03:57:37Z  attempt=19
    03:42:54Z  attempt=5                         03:58:40Z  attempt=20
    03:43:57Z  attempt=6                         03:59:43Z  attempt=21
    03:45:00Z  attempt=7                         04:00:46Z  attempt=22
    03:46:03Z  attempt=8                         04:01:49Z  attempt=23
    03:47:06Z  attempt=9                         04:02:52Z  attempt=24
    03:48:09Z  attempt=10                        04:03:55Z  attempt=25
    03:49:12Z  attempt=11                        04:04:59Z  attempt=26
    03:50:15Z  attempt=12                        04:06:02Z  attempt=27
    03:51:18Z  attempt=13                        04:07:05Z  attempt=28
    03:52:21Z  attempt=14                        04:08:08Z  attempt=29

Final loop line: `GAVE_UP at 2026-09-20T04:08:11Z after 29 attempts / 1770s` (plus the pre-loop
probe = 30 probes). This is the same failure the scope recorded at scope-lock time
(`No route to host`, 100 % packet loss): **the condition had not changed 20 h later.**

No scenario command line, exit code, artifact listing, frontmatter excerpt, timing or rtf exists
for A0–A8, because none was ever executed. `verify --trusted-local` produced no output — the
command was never sent. There is no per-item wall clock and no reported `rtf`.

### §E2 — Work prepared for the run (preparation, **not** scenario evidence)

Recorded so the next round can execute immediately; none of it is a result, and none of it may be
read as evidence about the target.

- **A0 transfer helper** — *reused evidence, prepared before this dispatch, scope: A0 transfer only.*
  `/root/workspace/bilibili-asr-archive/.tmp/e2e-longform-pair/push-bundle.sh` and its already-built
  bundle `/root/workspace/bilibili-asr-archive/.tmp/e2e-longform-pair/main-delta.bundle`
  (**512 198 bytes**, `git bundle create ef5e1e8..main`, local `git bundle verify` clean, exit 0).
  Verified by reading the helper: remote side is `git bundle verify` → `git fetch … main:refs/remotes/pad/main`
  → `git merge --ff-only` → prints HEAD and the `derive-manifest` grep count. Not run: the target was
  unreachable.
- **Pad `main` (the commit A0 would have delivered)** — NEW, local read-only. At 03:39Z, the start of
  this run, `git rev-parse main` → `f22bafd0665d897d98949792fb2712db4b1286ab`, matching the scope's
  declared tip. **`main` then moved during the run** (a harness commit landed on the pad while the
  gate was running): at 04:10Z `git rev-parse HEAD main` → `f85fe91a1b9aa5ab3d07d01bef64720cc982ce5c`
  (`f85fe91 chore(harness): register the long-form E2E workflow and carry the artifact-root register
  rows`), whose parent is `f22bafd`. Consequence for the next dispatch: the **already-built**
  `main-delta.bundle` (512 198 bytes) delivers `f22bafd` and is now one commit stale; rebuilt against
  current `main` the same refspec yields 516 034 bytes. `f22bafd` remains an ancestor of `f85fe91`,
  and `f85fe91` is harness bookkeeping only — the product code under test is unchanged, the last
  product commit being `3ec23df merge(iter-2026-09-artifact-root): deliver the configurable product
  root to main`. `push-bundle.sh` re-derives the bundle on every invocation
  (`git bundle create "$WORK/main-delta.bundle" "$PREREQ..main"`), so re-running it is sufficient —
  no fix is needed, but the stale file must not be shipped as "the pad's current main".
- **Scenario runner** — NEW: `/root/workspace/bilibili-asr-archive/.tmp/e2e-longform-pair/remote/scenario.sh`,
  covering A0-confirm/A1/A2/A3/A4/A5/A6/A7/A8 with `--help` capture, cookie loading by
  `source ~/.config/bili-asr/session.env` (ASCII-checked, never passed on a command line),
  detached `nohup` launches with per-scenario log paths under
  `/root/e2e-asr/logs/longform-pair-<UTC-stamp>/`, per-row SQLite/manifest comparisons for A4, the
  three A7 probes, and the A8 four-way artifact/sha256 recomputation. Validated locally only:
  `bash -n` clean, all 7 embedded Python blocks compile.
- **Flag confirmation** — the assignment requires each flag to be confirmed against the command's
  own `--help` **on the target**. That was impossible. What *was* done is weaker and is labelled as
  such: `--help` was read from the **pad's** checkout at `f22bafd`, the commit A0 would have
  delivered. Subcommands and flags confirmed present there: `check-asr-env`;
  `fetch-meta --mid --archive-root --resume --start-page --limit-pages`;
  `harvest-subs --bvid --archive-root --limit-parts`;
  `derive-manifest --archive-root`;
  `download-audio --missing-subs --bvid --archive-root --artifact-root --limit`;
  `asr --pending --bvid --archive-root --artifact-root --keep-audio/--no-keep-audio`;
  `verify --trusted-local --archive-root --artifact-root --scope --format`;
  `coverage --quality --trusted-local --reference --scope --format`. **This is not target evidence:**
  the target still holds `ef5e1e8`, which by the scope's own statement lacks `derive-manifest` and
  `--artifact-root` entirely. The flags actually used on the target: **none — no command was sent.**
- **Harness self-test of the A7 probes** — NEW, local, on the pad's `/tmp`, deliberately isolated
  from the target: the instrumentation was exercised to prove it can observe anything
  (`audio_dir_usage_bytes` returned `0` for an absent `audio/`, a dangling symlink and a plain
  file, `2` for a 2-byte file; the `roots_for` spy reported exactly `open(<root>) flags~=O_DIRECTORY`,
  `fsync: 0`, `write-mode open: 0`). One real defect in *my own instrumentation* was found and fixed
  this way (`configured` is False unless two distinct roots are passed, so the first version spied
  nothing). **These numbers are pad-local and are NOT A7 evidence** — A7 requires the observation on
  the target's WebDAV mount, which never happened.

### §E3 — Artifacts produced by this run

**None.** No `work_id` reached any terminal state; no artifact family exists to list with sizes;
neither root (`/root/e2e-asr/longform-pair`, `/mnt/123pan/bili-asr-e2e/longform-pair`) was created
or written by this run. Acceptance criterion 2 (both items determinate + families with sizes) and
criterion 3 (verbatim `verify --trusted-local`) are **not satisfiable**, not satisfied-by-absence.

*(Round 1 ends here. Everything below is round 2 — the re-dispatch after the PM confirmed the host
answering. Round-1 text above is left as written and is not rewritten.)*

---

## Evidence — round 2 (2026-09-20, 12:08Z–12:22Z)

**Host gate (2nd dispatch, PM precondition F2 honoured):** one probe, answered.
`2026-09-20T12:08:33Z attempt=1 rc=0 out=PROBE_OK`. No 30-minute gate was spent.

**Runner (reused, extended this round):** `/root/workspace/bilibili-asr-archive/.tmp/e2e-longform-pair/remote/scenario.sh`,
invoked as `ssh … "wsl -e bash -s -- <SCENARIO> <STAMP> <PAGES>" < scenario.sh` with
`STAMP=20260920T120858Z`, `PAGES=10`. Parameters travel as positional args because the remote login
shell is `cmd.exe` (which cannot take `VAR=x cmd`).

**Environment (A1):** WSL2 `DESKTOP-HHFROLO`, Linux 6.18.33.2-microsoft-standard-WSL2,
`/root/gpu-venv/bin/python` = Python 3.12.3, login cwd `/mnt/c/Users/chosenecho`.
Cookie sourced from `~/.config/bili-asr/session.env` (len 222, ASCII-checked, never on a command
line, never recorded). `/mnt/123pan` present: `123pan: on /mnt/123pan type fuse.rclone (rw,…)`.

### §R2-A0 — target build identity (verbatim)

    $ bash .tmp/e2e-longform-pair/push-bundle.sh
    pad tip: f85fe91a1b9aa5ab3d07d01bef64720cc982ce5c  bundle: 518335 bytes
    --- bundle verify ---
    The bundle contains this ref:
    f85fe91a1b9aa5ab3d07d01bef64720cc982ce5c refs/heads/main
    The bundle requires this ref:
    ef5e1e887e3aeb717e9a1c34b6b531d0e5f938ee
    The bundle uses this hash algorithm: sha1
    --- fetch ---
    --- fast-forward ---
    Updating ef5e1e8..f85fe91
    Fast-forward
     … 80 files changed, 14918 insertions(+), 677 deletions(-)
    --- HEAD ---
    f85fe91 chore(harness): register the long-form E2E workflow and carry the artifact-root register rows
    --- derive-manifest present? ---
    7
    PUSH_EXIT=0

Independent confirmation (separate ssh session, §A0_confirm — not the script's own summary):

    + git -C /root/workspace/bilibili-asr-archive rev-parse HEAD
    f85fe91a1b9aa5ab3d07d01bef64720cc982ce5c                                   EXIT=0
    + git -C … rev-parse --abbrev-ref HEAD          main
    + git -C … rev-parse refs/remotes/pad/main      f85fe91a1b9aa5ab3d07d01bef64720cc982ce5c
    + git -C … merge-base --is-ancestor ef5e1e8 HEAD   EXIT=0  (0 => fast-forward, not a rewrite)
    + git -C … reflog -3
    f85fe91 HEAD@{0}: merge refs/remotes/pad/main: Fast-forward
    ef5e1e8 HEAD@{1}: merge ef5e1e887e3aeb717e9a1c34b6b531d0e5f938ee: Fast-forward
    + grep -c derive-manifest bilibili-asr-archive/src/bili_asr/cli.py   7     EXIT=0
    + grep -c -- --artifact-root bilibili-asr-archive/src/bili_asr/cli.py  13  EXIT=0
    + git status --porcelain      ?? .env.bak-20260917-181947   (pre-existing, not ours)

The result was produced on commit **`f85fe91a1b9aa5ab3d07d01bef64720cc982ce5c`**.

### §R2-A1 — host self-check, and its cwd fragility

From the product root (the documented invocation):

    $ cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive
    $ VENV=/root/gpu-venv PYTHONPATH=$PWD/src /root/gpu-venv/bin/python -m bili_asr check-asr-env
    check: dxg-detection ok
    check: rocm-loader-path ok
    check: torch-present ok
    check: hsa-runtime ok
    check: device ok name=AMD Radeon RX 7800 XT arch=gfx1101 vram_gb=15.8 hip=7.2.26015-fc0010cf6a
    asr-env: verified
    EXIT=0

From the default login cwd, and again from the repo root:

    check-asr-env: no check script found; looked for /root/workspace/bilibili-asr-archive/scripts/check_asr_env.py,
    /mnt/c/Users/chosenecho/scripts/check_asr_env.py (set BILI_ASR_CHECK_SCRIPT to point at it)
    EXIT=1
    # repo-root run: BOTH candidates print as …/bilibili-asr-archive/scripts/check_asr_env.py, EXIT=1
    $ find /root/workspace/bilibili-asr-archive -name check_asr_env.py -not -path '*/.git/*'
    /root/workspace/bilibili-asr-archive/bilibili-asr-archive/scripts/check_asr_env.py
    $ ls /root/workspace/bilibili-asr-archive/scripts
    ls: cannot access …: No such file or directory

### §R2-A2 — `fetch-meta` never completes (page 3 blocked upstream)

    $ PYTHONPATH=<product>/src /root/gpu-venv/bin/python -m bili_asr fetch-meta \
        --mid 23191782 --archive-root /root/e2e-asr/longform-pair --limit-pages 10     # NO --resume: fresh root
    fetch-meta: metadata gateway failure (shape_error); cursor unchanged at page 3 — re-run fetch-meta to resume.
    sessdata: present
    fetch-meta: collected 3 page(s) for mid=23191782 (outcome=failed)                   [exit 2]

    $ … fetch-meta --mid 23191782 --archive-root … --resume --limit-pages 10
    fetch-meta: metadata gateway failure (rate_limited); cursor unchanged at page 3 — re-run fetch-meta to resume.
    fetch-meta: collected 1 page(s) for mid=23191782 (outcome=risk_interrupted)
    FETCH_EXIT=2

Four-attempt resume ladder (`A2_retry`, 75 s apart, all `--resume`): `ATTEMPT_1..4_EXIT=2`, every one
`shape_error`, cursor unchanged at page 3, store unchanged. Runs recorded in `ingestion_runs`:
`failed, risk_interrupted, failed, failed, failed, failed`.

Read-only gateway probe (no cursor or store writes) — isolates the fault to page 3:

    page 3: RAISED bili_asr.sources.models.GatewayRateLimited code='rate_limited' … in 0.35s
    page 4: OK videos=30 observed_total=1691 in 0.23s

Store after the run (`/root/e2e-asr/longform-pair/archive.db`, 479 232 B; opened read-only):

    videos 60 · video_parts 63 · v_pending_subtitles 63→61 after A3
    cursor: (23191782, next_page=3, observed_total=1691, state='ready', last_error_code=NULL)
    BV1vVDKBvEqL: 1 video / 1 part, page_index 0, cid 37227661829, duration_ms 7766000  (= 7766 s = 129.43 min)
    BV1iMGL6KE9J: 1 video / 1 part, page_index 0, cid 38565707829, duration_ms 5363000  (= 5363 s =  89.38 min)

Both match the scope's declared durations (129.4 / 89.4 min). Titles recorded live —
`BV1vVDKBvEqL` video title `…第六讲 第三个沉思（3）` while its pagelist part title reads
`…第七讲 第三个沉思（4）`; `BV1iMGL6KE9J` both `…第十一讲 存有论（11）…`. The video-vs-part title
divergence on the first item is upstream data, recorded not judged.

### §R2-A3 — the two items took the subtitle branch (determinate)

    $ … harvest-subs --bvid BV1vVDKBvEqL:p0 --archive-root /root/e2e-asr/longform-pair
    sessdata: present
    harvest BV1vVDKBvEqL:p0 stored subtitle-ai ai-zh v1
    harvest-subs: run_id=71c883be… attempted=1 stored=1 unchanged=0 no-subtitle=0 failed=0 remaining_without_transcript=62
    EXIT=0
    $ … harvest-subs --bvid BV1iMGL6KE9J:p0 --archive-root /root/e2e-asr/longform-pair
    harvest BV1iMGL6KE9J:p0 stored subtitle-ai ai-zh v1
    harvest-subs: run_id=3ff7f320… attempted=1 stored=1 unchanged=0 no-subtitle=0 failed=0 remaining_without_transcript=61
    EXIT=0

Store content (read-only):

    transcripts(video_part_id 53) = subtitle-ai / ai-zh / version 1 /
        content_sha256 67f2038d1ac7a1c93dad58c60be7612abda5f7aace54de44f323d07f77d59939
        segments = 2756   first cues: (460,3740,'我们接着来看这个第三个层次啊') (4820,8420,'在45页这边是啊')
    transcripts(video_part_id 24) = subtitle-ai / ai-zh / version 1 /
        content_sha256 0dd7c742db8cd64642102fb46fdb2466e29f09a805dbe1aadd4a189fe4f83cc6
        segments = 1996   first cues: (1070,6630,'这种真正的无限的它的规定不能够在公式当中表达啊')
    acquisition_attempts: both rows outcome='stored', error_code=NULL

### §R2-A4 — the bridge derives exactly the store's queue, and is idempotent

    $ … derive-manifest --archive-root /root/e2e-asr/longform-pair
    BV1147c6sEKs:p0: needs_audio (duration_s=893)  … (61 such lines) …
    BV1zAGL6zENs:p0: needs_audio (duration_s=7407)
    derive-manifest: queue=61 derived=61 already_derived=0 chain_owned=0 identity_mismatch=0   EXIT=0

    store v_pending_subtitles: 61      derived manifest work_ids: 61
    derived - store: []                store - derived: []
    SETS EQUAL: True
    --- BV1vVDKBvEqL:p0: ABSENT        --- BV1iMGL6KE9J:p0: ABSENT

    $ … derive-manifest --archive-root …        (second invocation)
    derive-manifest: queue=61 derived=0 already_derived=61 chain_owned=0 identity_mismatch=0   EXIT=0
    effective rows before: 61 after: 61        EFFECTIVE ROWS UNCHANGED: True
    changed keys: []

`manifest/manifest.jsonl` = 61 lines, 61 distinct work_ids, all `needs_audio`, 15 807 bytes.

### §R2-A5 / §R2-A6 — the plan's chain commands, verbatim, both items

    $ … download-audio --missing-subs --bvid BV1vVDKBvEqL:p0 --artifact-root /mnt/123pan/bili-asr-e2e/longform-pair
    BV1vVDKBvEqL:p0: unresolved; not assigned to a page                                DOWNLOAD_EXIT=1
    $ … asr --pending --bvid BV1vVDKBvEqL:p0 --artifact-root /mnt/123pan/bili-asr-e2e/longform-pair
    BV1vVDKBvEqL:p0: unresolved; not assigned to a page                                ASR_EXIT=1
    $ … download-audio --missing-subs --bvid BV1iMGL6KE9J:p0 --artifact-root …
    BV1iMGL6KE9J:p0: unresolved; not assigned to a page                                DOWNLOAD_EXIT=1
    $ … asr --pending --bvid BV1iMGL6KE9J:p0 --artifact-root …
    BV1iMGL6KE9J:p0: unresolved; not assigned to a page                                ASR_EXIT=1

Per-item wall clock: each pair ran inside one second (A5 12:18:41Z→12:18:41Z log span;
A6 12:19:08Z) — no audio was fetched, so no `rtf` exists for this round.
Artifact root: **0 files** (`find` returns only the two empty directories, one of them created by the
A7 walk probe). State stayed local: `archive.db` 479 232 B, `manifest/manifest.jsonl` 15 807 B,
`coordinator/archive-writer.lock` 0 B. No `manifest` row exists for either target work_id.

### §R2-A7 — the three artifact-root behaviours (commands that produced each)

(i) **Call sites** (`grep -rn 'audio_dir_usage_bytes(' …/src/bili_asr/`):

    coordinator.py:538:        usage = audio_dir_usage_bytes(self.artifact_roots.write_base)
    long_live.py:76            cli.py:2979 (write_base)   cli.py:2995 (write_base)   audio_budget.py:32, :89

**Timed measurement of the exact call the coordinator makes, WebDAV vs local disk**
(3 reps, best of; probe files created under the artifact root's `audio/` and removed afterwards):

     files       mount   webdav ms   local ms  x slower
         0           0        0.39       0.00      86.2
         1        1024        0.39       0.01      60.6
        10       10240        0.41       0.02      22.0
        50       51200        0.53       0.08       6.9
       200      204800        0.97       0.28       3.5

(ii) **fail-open** — the same function on five shapes:

    genuinely empty root (no audio/ dir)                 -> 0 bytes
    root with one 2-byte audio file                      -> 2 bytes
    audio/ is a DANGLING symlink (absent mount shape)    -> 0 bytes
    audio is a regular FILE, not a directory             -> 0 bytes
    nonexistent root                                     -> 0 bytes

The boundary, separately, **is** fail-closed:

    $ … download-audio --missing-subs --bvid BV1vVDKBvEqL:p0 … --artifact-root /mnt/123pan/bili-asr-e2e/definitely-absent-root
    download-audio: artifact root does not exist (…)                                            EXIT=1
    $ … --artifact-root /tmp/a7-probe/symlink-root
    download-audio: artifact root is a symlink (…)                                              EXIT=1

(iii) **validation primitives**, instrumented (`roots_for` with `flag_value` set, so
`configured` is True — the first version of this probe spied nothing because it passed one root):

    roots_for OK -> ArtifactRoots(archive_root=…/archive-root, artifact_root=…/hasfile)
    configured: True
      open(/tmp/a7-probe/hasfile) flags~=O_DIRECTORY
    PRIMITIVE COUNTS: {'open': 1, 'fsync': 0, 'mkdir': 0}
    fsync during validation: 0
    write-mode open during validation: 0

Directory-fsync behaviour of the actual mounts (the primitive `path_policy` uses):

    WebDAV artifact root     open(O_DIRECTORY) ok ; fsync(dir) ok  <-- directory fsync ACCEPTED
    WebDAV parent            open(O_DIRECTORY) ok ; fsync(dir) ok  <-- directory fsync ACCEPTED
    local archive root       open(O_DIRECTORY) ok ; fsync(dir) ok  <-- directory fsync ACCEPTED
    writer sequence on WebDAV  mkdir(fsync-probe-dir) + fsync(parent) ok
    probe dir fsync-probe-dir removed

One A7 sub-probe was **inconclusive** and is reported as such: the read-only-root attempt
(`--artifact-root /tmp/a7-probe/ro-root`) exited 1 with `BV1vVDKBvEqL:p0: unresolved; not assigned to
a page`, i.e. it never reached a write, so it says nothing about write-rejection. Running it against
a `needs_audio` row would have required processing an item outside the two named `work_id`s, which
constraint 4 forbids, so it was not done.

### §R2-A8 — archive evidence (no archived rows exist)

    $ … verify --trusted-local --archive-root /root/e2e-asr/longform-pair \
          --artifact-root /mnt/123pan/bili-asr-e2e/longform-pair
    {"authoritative": false, "checked": 61, "defect_count": 61,
     "defects": [{"code": "retryable_incomplete", "work_id": "BV1147c6sEKs:p0"}, … 61 entries …],
     "diagnostics": ["missing_attempts_sidecar"]}
    EXIT=1

(identical output with `--format json`; all 61 defects are `retryable_incomplete` — the unprocessed
`needs_audio` remainder, which is this code's classification for unfinished work, not corruption.)

    $ … coverage --quality --trusted-local --archive-root … --artifact-root …
    {"denominator":{"count":61,"source":"manifest_snapshot","state":"available","unit":"work_items"},
     "rows":[{"artifact_count":0,"cue_count":0,"reasons":["artifact_missing"],"status":"needs_audio", …}×61],
     "schema_version":"coverage-quality-v1",
     "summary":{"artifact_missing":61, "total_cues":0, "total_work_items":61, "valid_work_items":0, …}}
    EXIT=1

Artifact listings with sizes — **the artifact root holds no products**:

    $ find /mnt/123pan/bili-asr-e2e/longform-pair -printf '%y %10s  %p\n'
    d          0  /mnt/123pan/bili-asr-e2e/longform-pair
    d          0  /mnt/123pan/bili-asr-e2e/longform-pair/audio        <- created by the A7 walk probe, left empty

    $ find /root/e2e-asr/longform-pair -printf '%y %10s  %p\n'          (state, local disk)
    d       4096  /root/e2e-asr/longform-pair
    d       4096  …/manifest
    f          0  …/manifest/manifest.jsonl.lock
    f      15807  …/manifest/manifest.jsonl
    f     479232  …/archive.db
    d       4096  …/coordinator
    f          0  …/coordinator/archive-writer.lock

Four-way artifact consistency (`txt == segments_to_txt(raw)`, `srt == segments_to_srt(raw)`,
`md` body `== txt`) and marker `sha256` recomputation were **not performed**: they need archived
rows, and there are none. The A8 probe written for them is in the runner and would run unchanged
against a root that has products.

**Log paths (target, `/root/e2e-asr/logs/longform-pair-20260920T120858Z/`):**
`A2-fetch-meta-1.log` (196 B) · `A2-fetch-meta-2.log` (220 B) · `A2-fetch-meta-retry.log` (1103 B) ·
`A3-harvest-subs.log` (569 B) · `A5-chain-item1.log` (453 B) · `A6-chain-item2.log` (453 B).

**Target repository not mutated beyond A0:** `git status --porcelain` shows only the pre-existing
untracked `.env.bak-20260917-181947`; HEAD is `f85fe91`.

## Findings and handoff

For each failure: scoped impact, reproduction, evidence, proposed repair owner and bounded
follow-up. Known hypotheses to confirm or refute rather than assume: residual
`iter-2026-09-artifact-root · R2` (per-row WebDAV tree walk, fail-open measurement, missing
write+directory-fsync probe) and `iter-2026-09-artifact-root · R3` (path-to-base pairing
re-implemented across five modules). Defects found here go to bounded repair plans; they do not
reopen the originating iterations by themselves.

### F1 — Target host unreachable for the entire gate window (severity: **blocking**; product defect: *no*)

- **What happened.** Every one of 30 probes to `192.168.3.21:22` over 03:38:16Z–04:08:11Z failed
  with `No route to host` (exit 255). Not a refusal (no `Connection refused`), not an auth failure,
  not a timeout: the packet-level route to the host did not exist for the full 30 minutes.
- **Scoped impact.** All of A0–A8 are blocked; **zero** product behaviour was exercised. This says
  **nothing** about the two features under test (the configurable artifact root, the
  `derive-manifest` bridge) — neither for nor against. No product defect is claimed and no residual
  is opened by this run.
- **Reproduction (operator-side, 30 s).** From the pad:
  `ssh -i /root/.ssh/id_ed25519 -o BatchMode=yes -o ConnectTimeout=15 chosenecho@192.168.3.21 "echo PROBE_OK"`
  → expect the same `No route to host` while the box is off/asleep/off-network.
- **Evidence.** Evidence §E1 (30 timestamps, exit codes, exact error text, log path).
- **Most likely cause, stated as a hypothesis and not as a measurement.** The Windows compute box
  is powered off, asleep, or off-network — an environmental precondition, not a product finding.
  The previous run (`e2e-23191782-season-7686105`, 2026-09-17) used the same host successfully, and
  the scope recorded the same error at scope-lock time, so this is a persistent external condition
  rather than something this run changed.
- **Proposed repair owner: the operator, not a code owner.** Bounded follow-up: the operator brings
  the box up (or reports its new address) and states a time window in which it will stay up;
  PM then re-dispatches this same scope as the one permitted re-dispatch. No product plan, no
  residual, and no code change is warranted by F1.
- **Do not** substitute another host, a local run, or a simulated result: the scope fixed the
  target environment, and constraint 1 forbids exactly that substitution. It was not done.

### F2 — The 30-minute gate is shorter than the box's real availability cycle (severity: low; process)

- **What happened.** The gate's design assumes the host may come back within 30 minutes. Nothing
  observed here supports that: the condition was identical at scope-lock time (~20 h earlier) and at
  every probe in this window.
- **Impact.** A re-dispatch with the same 30-minute gate is likely to spend another ops round
  producing the same `blocked` report.
- **Proposed repair owner: PM.** Bounded follow-up: before the re-dispatch, confirm the box is up
  (one probe, or an operator statement) and only then spend the ops round; keep the 30-minute gate
  as the in-run guard rather than as the only availability test. This is a dispatch-ordering change,
  not a scope change.

### F3 — the prepared A0 bundle went stale during the gate window (severity: low; process; no fix needed)

- **What happened.** The A0 delta bundle was built before this dispatch against `main` = `f22bafd`.
  While the 30-minute gate was running, a harness commit landed on the pad and `main` became
  `f85fe91`, so the pre-built 512 198-byte file no longer delivers the pad's current `main`
  (rebuilt: 516 034 bytes).
- **Impact on the product:** none — `f85fe91`'s only content is harness bookkeeping (workflow
  registration + register rows); the newest product commit is still `3ec23df`. **Impact on A0's
  acceptance:** real, because A0 names "the pad's current `main`" as the identity to install.
- **Not a defect in the helper:** `push-bundle.sh` re-runs `git bundle create … "$PREREQ..main"` on
  every invocation, so re-running it regenerates correctly.
- **Proposed repair owner: PM** (or whoever re-dispatches). Bounded follow-up: re-run
  `push-bundle.sh` at dispatch time rather than shipping the existing `main-delta.bundle`, and
  record the tip it actually delivered.

### Hypotheses this run could **not** confirm or refute

*(Round-1 text, kept as written — superseded by the round-2 verdicts below.)*

Residual `iter-2026-09-artifact-root · R2` and `R3` are untouched — they are triggered by a real
corpus run against the WebDAV mount, which did not occur. A7's three behaviours (per-row walk cost;
fail-open vs measured-empty; missing write+directory-`fsync` probe) are **not answered** here; each
remains an open hypothesis. Nothing in this report should be read as evidence about R2 or R3 in
either direction.

---

## Findings — round 2

*(F1–F3 above are round-1 findings and stand as written. F3 is now resolved in practice: the round-2
helper rebuilt the bundle at invocation time and delivered 518 335 bytes carrying `f85fe91`.)*

### F4 — `check-asr-env` resolves its script relative to the wrong root, so it only works from one cwd (severity: low; real defect)

- **What.** `cli.py` builds `Path(__file__).resolve().parents[3] / "scripts" / "check_asr_env.py"`
  with the comment "src/bili_asr/cli.py -> repository root -> scripts/". In this repository the
  product root is `parents[2]` (`…/bilibili-asr-archive/bilibili-asr-archive`); `parents[3]` is one
  level too high, so that candidate is always `…/bilibili-asr-archive/scripts/check_asr_env.py`,
  which **does not exist**. The only candidate that can hit is `Path.cwd() / "scripts" / …`.
- **Measured.** Exit 0 and the full device line from the product root; exit 1
  `no check script found` from both the default login cwd (`/mnt/c/Users/chosenecho`) and the repo
  root (§R2-A1). The command is the README-published GPU self-check.
- **Impact.** Low — a self-check, and the documented invocation works. But an operator who runs it
  from anywhere else gets a "no check script found" message that names two paths and suggests
  `BILI_ASR_CHECK_SCRIPT`, which reads like a missing install rather than a wrong anchor.
- **Fix shape.** `parents[3]` → `parents[2]`, or resolve from the package's own installed location
  rather than from cwd at all.
- **Proposed repair owner:** the next plan touching `src/bili_asr/cli.py`'s `check-asr-env` handler.
  Bounded: one anchor + a test that runs it from a cwd other than the product root. **Not repaired
  here** — this run is verification-only.

### F5 — the run's premise is stale: both named items now carry AI captions, so the audio→ASR→artifact-root path had no work (severity: **medium**; premise, not product)

- **What.** The scope assumed the two items would exercise the ASR chain and place products on the
  WebDAV mount (that is residual R2's trigger). Live upstream instead served AI subtitles for both
  (`subtitle-ai` / `ai-zh`, 2756 and 1996 segments, §R2-A3), so the chain took its **documented**
  "subtitles first, local FunASR fallback" branch and `derive-manifest` excluded both from the audio
  queue (§R2-A4). A5/A6 then had nothing to select (§R2-A5/A6).
- **Is this a product defect? No.** A3 explicitly sanctions this branch ("either outcome is a
  determinate result, not a failure"), and every command behaved exactly as documented. The gap is
  between A3's two-outcome framing and A4/A5/A6's single-branch expectations — the plan is
  internally inconsistent in the caption-present case, and live data chose that case.
- **Why it matters.** The two most recent iterations' *audio* behaviour and the WebDAV artifact
  placement are still **unverified on a real row**. Residual `iter-2026-09-artifact-root · R2` is
  therefore still un-triggered by a corpus run — see the A7 verdict below for what *was* measured.
- **Proposed repair owner: PM** (planning, not code). Bounded options for a successor run — pick one
  and record it: (a) accept the subtitle branch and re-scope the E2E to the *subtitle* path,
  including the still-missing projection of stored transcripts to srt/txt/md (the long-standing gap
  the scope's own residual R1 names); (b) choose items that genuinely lack captions, or drive the
  audio branch explicitly, so the WebDAV placement is exercised; (c) treat the audio branch as
  covered by the 2026-09-17 season run and close this workflow on the A0/A1/A3/A4/A7 evidence.

### F6 — page 3 of UID 23191782's upload list is blocked by upstream risk control (severity: low; upstream, product handled it correctly)

- **What.** `fetch-meta` could not get past page 3 in 6 attempts (5× `shape_error`, 1×
  `rate_limited`), while a direct gateway probe raised `GatewayRateLimited` for page 3 and returned
  page 4 normally (§R2-A2).
- **Product behaviour was correct.** Bounded failure, bounded scalar code, **cursor unchanged at
  page 3**, `state='ready'`, resume-safe, exit 2 — exactly the taxonomy `_cmd_fetch_meta`'s docstring
  promises. Nothing was lost: pages 1–2 (60 videos / 63 parts, including both target items) stayed
  committed.
- **Impact.** Only on "enumerate the whole channel": the run's own goal was already met from pages
  1–2. A full 1691-video enumeration (`observed_total=1691`) is not currently reachable.
- **Proposed repair owner: none for the product.** Operator/PM: if a full enumeration is ever
  wanted, retry later or start at page 4 (`--start-page`) to step over the blocked page.

### F7 — residual `iter-2026-09-artifact-root · R2`: two of three items **confirmed**, one **not reproducible on this mount** (severity: medium; residual verdict)

- **R2(i) per-row walk over the WebDAV tree — measured, and materially milder than framed.** The
  coordinator does measure the artifact root (`audio_dir_usage_bytes(write_base)`, `coordinator.py:538`,
  invoked per row from `_note_audio_peak`). Measured cost on the live rclone mount: **0.39 ms empty →
  0.97 ms at 200 files** (local disk 0.00–0.28 ms; 3.5×–86× slower, but sub-millisecond in absolute
  terms). The "network round trip per row" is real but cheap at realistic tree sizes — a 1000-row
  batch would spend well under a second in total. **Recommend downgrading this clause's weight.**
- **R2(ii) fail-open measurement — CONFIRMED.** An absent / dangling / non-directory `audio/` all
  return **0 bytes**, indistinguishable from a genuinely empty tree (§R2-A7 ii). The cumulative
  guard is silently disabled and the 0 is printed as evidence. Note the boundary layer is separately
  fail-closed (absent/symlinked configured root → exit 1 named refusal), so the exposure is the
  measurement, not the root resolution.
- **R2(iii) missing write + directory-`fsync` probe — CONFIRMED as a code fact, but the predicted
  failure does not manifest on this mount.** Validation performs exactly `1 × open(O_DIRECTORY)`,
  **0 fsync, 0 write-mode opens** (§R2-A7 iii), so it truly does not probe a write or a directory
  fsync. However, this rclone mount **accepts** directory fsync (`open` ok, `fsync(dir)` ok, and the
  writer's own `mkdir + fsync(parent)` sequence ok), so the "passes validation, then fails every row
  with a raw error" scenario is **not reproducible here**. The gap is latent, not live.
- **Proposed repair owner: the next plan that owns `audio_budget.py`'s call sites or the operator's
  network-mount configuration** (R2's own `target` already says this). Bounded follow-up: sample the
  usage once per batch instead of per row; distinguish "measured empty" from "cannot measure"
  (fail-closed); optionally add a write+fsync probe **or** declare fsync-hostile mounts out of
  contract — the last option is now the cheaper call, since the mount in use accepts fsync.
- **R3 (path-to-base pairing across five modules): untouched.** Nothing in this round exercised a
  second artifact family or a second configured root, so R3 remains exactly as registered.

## Not verified

Excluded scenarios, unavailable capabilities and evidence limits. Known at scope-lock time:
the target host was **unreachable** (`No route to host`, 100 % packet loss) when this scope was
written; no scenario above had run at that moment. The project's full local test suite is out of
scope by the standing directive.

> **The block below is round 1 (host unreachable, 30 probes, all nine scenarios `blocked`). It is
> kept as written as the record of that round. Round 2's own statement is the next section.**

**This run verified nothing about the product.** The list below is complete for A0–A8:

| Not verified | Exact missing prerequisite |
|---|---|
| A0 target build identity + `--ff-only` fast-forward | a reachable target host (`192.168.3.21:22` answered `No route to host` on all 30 probes); **and** a bundle regenerated from the pad's *then-current* `main` (the prepared 512 198-byte bundle pins `f22bafd`; `main` had advanced to `f85fe91` by the end of this run — see §E2) |
| A1 `check-asr-env` on the target GPU | same — no command could be sent |
| A2 `fetch-meta` enumeration, `archive.db`, resumability | same; plus the target's `/root/e2e-asr/longform-pair` was never created |
| A3 `harvest-subs` determinate outcome for the two parts | same; plus no store exists to record an outcome |
| A4 `derive-manifest` == `v_pending_subtitles`, `duration_s > 0`, `needs_audio`, idempotence | same; plus no manifest exists |
| A5 item 1 (`BV1vVDKBvEqL:p0`, 129.4 min) reaching `archived` with products on WebDAV | same; plus no reachable `/mnt/123pan` mount to write to |
| A6 item 2 (`BV1iMGL6KE9J:p0`, 89.4 min) reaching `archived` | same |
| A7 (i) per-row WebDAV tree-walk cost · (ii) fail-open vs measured-empty · (iii) write+directory-`fsync` probe | same; plus no live WebDAV artifact root to measure |
| A8 `verify --trusted-local`, four-way artifact consistency, `sha256` recomputation, `coverage --quality` | same; plus zero archived rows exist to verify |

Additional evidence limits, stated plainly:

- **No command line, exit code, artifact byte size, frontmatter excerpt, wall clock or `rtf` was
  produced for any scenario** — none was executed. Every acceptance criterion that depends on
  produced artifacts (AC2, AC3, AC4, AC6) is therefore unsatisfied, and is reported as unsatisfied
  rather than as an empty pass.
- **The flags in Evidence §E2 were confirmed against the pad's `f22bafd`, not the target's own
  `--help`.** Constraint 5 requires the latter; it was impossible. The target still holds `ef5e1e8`,
  which lacks `derive-manifest` and `--artifact-root`, so the pad's help is not a substitute for
  target confirmation and must not be cited as one.
- **The A7 probe self-test in §E2 is pad-local.** It proves the instrumentation works; it is not an
  observation of the target's WebDAV mount and cannot answer A7 i/ii/iii.
- **Disk discipline (constraint 4) was never exercised** — no product was written anywhere, so
  whether `/mnt/123pan` can hold the products remains unknown, and no fallback to a local path was
  taken or needed.
- **Unreachable-target evidence is bounded to this pad.** The probe was sent from the pad only;
  it cannot distinguish "the box is off" from "the pad's route to it changed". No second vantage
  point was available and none was improvised.
- Not attempted, by standing directive: the project's full local test suite, any product-code,
  docs or config change, and any cleanup on either named root. **The target's repository was not
  mutated in any way** — the single permitted mutation (A0's `--ff-only` fast-forward) did not run,
  so the target's HEAD is still whatever it was, and this report deliberately does **not** claim
  what that is beyond the scope's recorded `ef5e1e8`.

---

## Not verified — round 2

Everything below is what the round-2 run **did not** establish, stated so that no reader infers it
from the passes.

| Not verified | Why / exact missing prerequisite |
|---|---|
| **The audio→ASR chain on either named item** (A5/A6) | Both items now carry AI captions, so the bridge excluded them from the audio queue; no shipped command can put a caption-bearing part back on it. The commands ran and exited 1 (§R2-A5/A6) — this is a determinate *not done*, not an untested claim |
| **Products under the artifact root / split-root placement** | Nothing was written, so "products land under `/mnt/123pan` and state stays local" is verified only as *state stayed local* (`archive.db`, `manifest/`, `coordinator/` all on local disk). The artifact root holds 0 files |
| **Four-way artifact consistency and bundle `sha256` recomputation** (A8) | Needs archived rows; there are none. The probe exists in the runner and is untested |
| **`verify --trusted-local` on archived rows** | The command ran and is recorded verbatim, but with 0 archived rows its "zero defects" clause has no subject. Its 61 `retryable_incomplete` defects are the unprocessed remainder |
| **`coverage --quality`'s doubt surface as a real measurement** | It printed, but `total_cues: 0` / `valid_work_items: 0` — the doubt surface is empty because no artifact was measured |
| **A full channel enumeration (`observed_total` 1691)** | Page 3 is blocked upstream (5× `shape_error`, 1× `rate_limited`); only pages 1–2 (60 videos / 63 parts) were collected |
| **Whether a write-rejecting or fsync-rejecting mount passes validation** | Not reproducible here: this rclone mount accepts both, and the read-only-root probe never reached a write (it exited on `unresolved` first). The *absence* of the write/fsync probes is measured; the *consequence* is inferred, not observed |
| **The audio-branch behaviour of the two features under test on a real row** | Same prerequisite as row 1. Residual `iter-2026-09-artifact-root · R2` was therefore measured **directly** (A7) rather than triggered by a corpus run; `R3` is untouched |
| **Per-item wall clock / `rtf`** | No audio was fetched or transcribed, so no decode rate exists for this round |
| **The project's full local test suite** | Out of scope by standing directive; this run supplies its own evidence |
| **Product code, docs or config on the target** | Deliberately not touched — verification only. The A0 `--ff-only` fast-forward was the sole permitted mutation and it is the only one made |

**Nothing was substituted.** No other host, no local run, no simulated or reused 2026-09-17 result
stands in for any scenario above. Where a measurement was taken on the pad (the A7 instrumentation
self-test) it is labelled as such and is not used as target evidence.

## Constraints the executor must honour

1. **Verification only.** No product code, docs or config changes on the target for this run.
   The only repository mutation permitted is the A0 fast-forward, and it must be `--ff-only`.
2. **Detached long steps.** Every run longer than a couple of minutes (metadata enumeration,
   audio download, ASR) must be launched detached (`nohup … > <log> 2>&1 &`) and polled, so an
   ssh session ending cannot kill it. Record the log path.
3. **Credential handling.** Source `~/.config/bili-asr/session.env`; export `BILI_SESSDATA`;
   never pass `--sessdata` on a command line; refuse a value containing non-ASCII (the repo
   `.env` is known-malformed — do not use it).
4. **Disk discipline.** Products go to `/mnt/123pan` (the operator's choice and the R2 trigger);
   state stays on the local disk. Watch the WSL root filesystem: it has been driven to a
   read-only emergency remount by exhaustion before. If the WebDAV mount cannot hold the
   products, record the failure; do not silently fall back to local paths without saying so.
5. **Scoped work only.** The chain steps must be restricted to the two named `work_id`s via the
   shipped selectors (`--bvid`), so the run transcribes exactly two items. Verify every flag
   against the command's own `--help` on the target before using it; record the flags actually used.
6. **Model/GPU configuration:** the 2026-09-17 run's working values were
   `HSA_ENABLE_DXG_DETECTION=1`, `BILI_ASR_MODEL=/root/e2e-asr/nano/master`,
   `BILI_ASR_MODEL_ID=FunAudioLLM/Fun-ASR-Nano-2512`, `BILI_ASR_DEVICE=cuda`,
   `BILI_ASR_LANGUAGE=中文`, `MODELSCOPE_CACHE=/root/.cache/modelscope`. Treat these as
   *known-good inputs from the previous run*, not as contract: confirm the current names against
   the checkout's README/`--help` and report any divergence.
7. **Report shape.** One outcome per scenario, exact commands, real output. A failed product
   scenario is still a completed verification run — report it as such.

## Acceptance criteria

1. Every scenario A0–A8 carries exactly one outcome from the vocabulary above, with evidence.
2. Both items reach a determinate terminal state in the fresh root, and the artifact families
   produced are listed with sizes.
3. `verify --trusted-local` result on the archived rows is recorded verbatim.
4. The artifact-root behaviours (A7 i/ii/iii) are each answered yes/no/observed-with-error, with
   the command that produced the observation.
5. Any scenario that could not run states the exact missing prerequisite.
6. The report never claims a pass without a command + output pair to support it.

## Completion recommendation (round 1 — superseded by round 2 below)

*(Kept as written: this was round 1's recommendation, made with the host unreachable. Round 2's
final recommendation follows it.)*

- **Assigned 9, completed 0, blocked 9** (A0–A8). Not a single scenario reached a determinate
  product result, because the run's one hard prerequisite — a reachable target host — was absent for
  the whole gate window (30 probes, 0 answers, §E1).
- **Product result: not established, in either direction.** The two features under test (the
  configurable artifact root and the `derive-manifest` store→manifest bridge) were **not exercised**.
  No pass is claimed and no defect is claimed. Residuals `iter-2026-09-artifact-root · R2` and `R3`
  remain exactly as they were: unconfirmed and unrefuted.
- **Run lifecycle outcome (recommended to PM, separate from any product verdict):** this dispatch
  ends as **Blocked**, not as a completed verification run. Per `mstar-e2e`, an execution block that
  stays unresolved is explicit and is not a simulated pass.
- **Recommended next step (PM's call, and the one permitted re-dispatch under this task budget):**
  do **not** re-dispatch on the current information — the condition was identical ~20 h before this
  dispatch. First obtain one of: (a) the box powered on and confirmed answering, or (b) a corrected
  address/reachability path. Then re-dispatch this unchanged scope. Everything needed is prepared and
  waiting: the A0 helper (§E2), the scenario runner, and the confirmed flag set.
- **What PM can close now without the product run:** nothing about the product. The scope,
  scenarios, acceptance criteria and authorization are untouched by this report and need no edit —
  only the `## Results`/`## Evidence`/`## Not verified` sections carry actuals, which is exactly the
  division of labour the header states.
- **Ops does not mark the plan `Done`** and did not modify scope, scenarios, roots or the workflow
  snapshot.

---

## Completion recommendation — round 2 (final)

- **Assigned 9 · passed 4 (A0, A1, A3, A7) · failed 5 (A2, A4, A5, A6, A8) · not-run 0 · blocked 0.**
  Every scenario carries exactly one outcome with a command + output pair behind it.
- **Product result: partly established, and the part that was exercised is sound.**
  - **Verified:** the A0 delivery path (`--ff-only` `ef5e1e8`→`f85fe91`, reflog-confirmed); the GPU
    self-check on the target hardware; the subtitle branch end-to-end into the store (two real
    transcripts, 2756 + 1996 segments); **the `derive-manifest` bridge — the derived queue equals
    the store's `v_pending_subtitles` exactly, and a second invocation is idempotent**; and the
    artifact root's boundary, measurement and fail-open behaviour measured on the live WebDAV mount.
  - **Not established:** anything on the audio→ASR→artifact-placement path, because both named items
    turned out to have AI captions (F5). The five `failed` rows are **not five defects**: A2 is
    upstream risk control, A4 is one unmet clause of four, and A5/A6/A8 are the same single factual
    change.
- **Residual verdict (the round's most useful output):** `iter-2026-09-artifact-root · R2` —
  **fail-open measurement confirmed** (ii); **missing write/fsync probe confirmed as a code fact**
  (iii) but **not reproducible on this mount**, which accepts directory fsync; and the per-row walk
  (i) **measured at 0.39–0.97 ms**, i.e. real but far cheaper than the residual's framing suggests.
  R2 should be re-scoped rather than closed: keep (ii), downgrade (i), and prefer "declare
  fsync-hostile mounts out of contract" over adding a probe. **R3 untouched.**
- **Run lifecycle outcome (recommended to PM, separate from any product verdict):** this dispatch
  **completed** — all nine scenarios have determinate results and the report is fit to accept. It is
  **not** a clean product pass: five scenarios failed, for the reasons above. Per `mstar-e2e`,
  "workflow completed" ≠ "product passed".
- **Recommended next step (PM's call):** decide F5's branch — (a) re-scope to the subtitle path
  (which then needs the stored-transcript→srt/txt/md projection that the residual register already
  names as missing), (b) run items that genuinely lack captions so the WebDAV placement is exercised,
  or (c) close on the A0/A1/A3/A4/A7 evidence and the A7 residual measurement. **No repair plan is
  warranted for A4/A5/A6/A8** — nothing in them is a code defect. F4 (severity low) is the one real
  code defect this round found and it is worth a one-line fix in the next plan that touches
  `cli.py`.
- **Ops does not mark the plan `Done`**, and did not modify scope, scenarios, roots, the workflow
  snapshot, or any residual register.

## PM lifecycle note

PM alone advances this workflow's plan row and closes the workflow; ops returns results and does
not mark `Done`. Scope, authorization and the scenario list were fixed before dispatch; a change
to any of them needs a fresh user decision, not an executor improvisation.

---

## PM acceptance (2026-09-20)

**Verdict: report accepted** against the scenario list. All nine scenarios carry exactly one
outcome from the vocabulary (`blocked`), the single blocking condition is stated per row with its
exact missing prerequisite, and §E1 is a real command + output pair repeated 30 times with
timestamps — nothing is claimed that was not observed, and no scenario is reported as a pass.
The absence of product evidence is the correct result of an unreachable target, not a gap in the
report.

**Lifecycle:** plan row `InProgress → Blocked`; workflow `running → paused` (not terminal — the
scope stays valid and resumable; no `ended_at` is owed because `paused` is not a terminal status).
Nothing in the product was touched, no residual was opened or closed, and residuals
`iter-2026-09-artifact-root · R2`/`R3` remain **open and unrefuted** — A7 never ran, so this run
neither confirms nor weakens them.

**Re-dispatch precondition (from finding F2):** the PM confirms the box is answering *before*
spending another ops round; the unchanged scope, the A0 helper and the A0–A8 runner
(`.tmp/e2e-longform-pair/remote/scenario.sh`) are prepared and waiting. Finding F3 (a stale
pre-built bundle) needs no repair: `push-bundle.sh` regenerates it at invocation time.

**Blocker persistence (pad-side monitoring, 2026-09-20).** After the ops gate closed at
`04:08:11Z`, the PM armed a watchdog on the pad (one probe every 180 s). It ran its full bound and
ended at **`08:45:30Z` with `HOST_STILL_DOWN after 90 attempts (~4.5h)`** — so the single missing
prerequisite was continuously absent from the first PM probe at `03:35Z` to `08:45Z`
(≈5 h 10 min of wall clock), with the identical `No route to host` signature throughout. No
further ops round was spent (finding F2). The plan row stays `Blocked` and the workflow `paused`;
the re-dispatch needs only a reachable box — or a corrected target address/route.

## PM acceptance — round 2 and workflow closure (2026-09-20)

**Verdict: report accepted.** All nine scenarios carry one outcome from the vocabulary with a
command-and-output pair behind it (round-2 counts: **passed 4 · failed 5 · not-run 0 · blocked 0**),
the round-1 history is preserved rather than rewritten, and the failure analysis separates causes
honestly: four scenarios downstream of one stale premise (F5) and one upstream block (F6) are not
presented as five defects. Both delivered features were exercised where work existed: the bridge's
derived set matched the store's queue exactly and was idempotent (A4), and the artifact-root
boundary and measurement behaviour were measured directly on the live mount (A7).

**Product result: PARTLY established — this is NOT a clean product pass.** Positively established
on the delivered build `f85fe91`: the target fast-forward and the GPU self-check (A0/A1); the
caption branch is determinate and the store holds both items' AI transcripts (A3); the
`derive-manifest` bridge equals `v_pending_subtitles` and is idempotent (A4, first two clauses plus
`SETS EQUAL: True`); the artifact-root behaviours (A7 i/ii/iii) are answered with measurements.
Still unverified: the audio→ASR branch and the WebDAV product placement on a real archived row,
four-way artifact consistency and `sha256` recomputation, `verify`'s zero-defect claim on archived
rows, and the quality doubt surface as a real measurement — all because no row reached `archived`.

**Lifecycle closed.** Plan row `Blocked → Done` (the verification ran to completion; `Done` records
the run, not a product pass). Workflow snapshot `paused → completed` with **`ended_at: 2026-09-20`**,
and the document was validated with the engine's own validator before closure was declared — the
discipline residual `iter-2026-09-artifact-root · R4` requires. Root `status.json` entry removed in
the same round (removal-at-terminal); the engine resolves this terminal snapshot cleanly.

**Residuals.** Registered against this workflow: **R1** (F4 — `check-asr-env` anchors its helper at
`parents[3]`, so the published self-check only works from the product root), **R2** (F5 — a
caption-bearing part cannot be routed through the audio branch at all, so the audio path of the two
most recent iterations stays unverified on live data), **R3** (F6 — a page under upstream risk
control makes a full channel enumeration unreachable; the product's stop/resume behaviour is
correct). `iter-2026-09-artifact-root · R2` was **amended with the A7 verdict and left open**
(fail-open confirmed; the missing write/fsync probe confirmed as a code fact but not reproducible on
this fsync-accepting mount; the per-row walk measured sub-millisecond); `R3` of that iteration is
untouched. No residual was closed by this run.
