# QA Gate (L4 Acceptance) — 20260911-subtitle-cli-cutover

- Iteration: `iter-2026-09-subtitle-transcript-sqlite` (final plan, serial 3/3)
- Plan: `.mstar/plans/20260911-subtitle-cli-cutover.md`
- Seat: `qa-engineer` (L4, single seat; `Delegation: forbidden`, report-only)
- `Review cwd`: `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-cli-cutover`
- Working branch: `feature/20260911-subtitle-cli-cutover` — HEAD `7e57eb6`, tree clean
- Diff basis: `c5a9b82` (integration branch at cut) → `7e57eb6`
- `QA gate`: mandatory · `QA mode`: acceptance-only + the QC-routed runtime items
- Input: `review/qc-consolidated.md` **FINAL GATE DECISION: Approve** (N=3 targeted re-review of the fix wave
  `8373817..7e57eb6`, Critical 0 / Warning 0 / open Suggestion 0)

**Verdict: Needs fixes** — one new Warning (`F-QA-001`, below) found by the routed runtime exercise of the two
`unreadable archive database` branches. Everything else the gate was asked to verify is green: 1311 passed / 4
skipped at HEAD, the bounded live smoke re-taken successfully with real stored rows, F-001 fixed at runtime, the
legacy-schema and missing-database guards correct, the residual register correct, and A1–A12 standing.

---

## 1. Scope tested

The QC gate's `⚠️ Hand-off to the mandatory QA gate (L4)` list (5 items) plus the Assignment's routed items:

1. checkout/range alignment and diff-artifact composition;
2. the full offline suite at HEAD + the AST import-boundary and no-leak scans;
3. a fresh bounded live smoke (the plan's acceptance-carrying evidence);
4. runtime exercise of the two new `unreadable archive database` branches (seat-1 observation);
5. F-001 at runtime (blank/whitespace `--bvid`) and the pre-iteration-database case;
6. DoD/acceptance-box mapping; 7. the residual register; 8. the iteration-level A1–A12 re-confirmation.

No implementation file was modified. Scratch lived in `/tmp/qa-gate-20260911/` and `tests/`' own `.test-tmp`
(removed). The control venv was only *executed*, never synced. No credential value was read into any artifact,
and the traceback/`pytest` captures were sentinel-scanned (results in §3.3 and §4.3).

## 2. Alignment — PASS

| Check | Result |
|---|---|
| `pwd` | `.worktrees/20260911-subtitle-cli-cutover` — the Assignment's `Review cwd` |
| Branch | `feature/20260911-subtitle-cli-cutover` |
| HEAD | `7e57eb62d35d33b8effee6b21bac8b0b8f4d70c1` = `7e57eb6` (the reviewed fix-wave head) |
| Tree | `git status --porcelain` empty (before and after every run) |
| Base | `c5a9b82` = `iteration/iter-2026-09-subtitle-transcript-sqlite` (checked out in the control worktree) |
| Range | `git diff c5a9b82..7e57eb6` = 16 files, +5415/−585 |

**Diff-artifact composition — proven byte-identical, not eyeballed.** The fenced ```diff body of
`review/branch-diff.md` equals `git diff --no-color c5a9b82..8373817` **byte for byte** (5607 lines, 13 files),
and `review/qc-fix-diff.md` equals `git diff --no-color 8373817..7e57eb6` (1479 lines, 9 files). The two file
sets overlap in 6 files and their union is exactly the 16 files of the live full-range diff — i.e. the reviewed
package composes to the live `c5a9b82..7e57eb6` diff with no file added, dropped, or left unreviewed.

Metadata is text-identical to the QC tri's (`Review cwd`, `Working branch`, `plan_id`, range/base); no
worktree/branch disagreement, so this is not a `Blocked` alignment case.

## 3. Fresh-run evidence

### 3.1 Full offline suite at HEAD — PASS

```
cd .worktrees/20260911-subtitle-cli-cutover/bilibili-asr-archive
/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest -q -rs
```

**`1311 passed, 4 skipped in 50.78s`, exit 0** — exactly the implementer-reported count the QC consolidation
asked to have reproduced. The 4 skips are precisely the opt-in live gates (`test_bilibili_api_gateway.py:3380`,
`test_live_metadata_smoke.py:329`, `test_live_subtitle_cli_smoke.py:271`, `test_live_subtitle_smoke.py:438`),
each `SKIPPED … set BILI_LIVE_SMOKE=1 to request it`. Against the plan's recorded baseline (plan 2 post-merge
`1202 passed, 3 skipped`) the delta is +109 tests and +1 opt-in gate — the new live subtitle smoke.

### 3.2 AST import-boundary and no-leak scans — RAN, PASS

Re-run focused so the run itself is evidence (not just their presence in the 1311):

- Import boundary (AST): `test_only_the_gateway_module_imports_bilibili_api`,
  `test_gateway_imports_stay_on_metadata_surface`, `test_gateway_source_never_names_forbidden_seam_methods`,
  `test_fake_seam_exposes_only_documented_metadata_surface` → **4 passed** (0.57 s).
- No-leak scans: the suite's `assert_leaks_no_markers` callers all ran in the 1311 —
  `test_subtitle_e2e.py` (`:370`, `:741`, `:751` over output *and* every persisted row), `test_subtitle_cli.py`
  (failed-part output, partial-run output), `test_metadata_ingest.py:922` (the scan's own self-test),
  `test_live_subtitle_cli_smoke.py` (credential-gate + probe-surface sentinel cases).

### 3.3 Bounded live smoke, re-taken — PASS (the acceptance-carrying evidence)

```
cd .worktrees/20260911-subtitle-cli-cutover/bilibili-asr-archive
set -a; source /root/workspace/bilibili-asr-archive/.env; set +a
BILI_HTTP_PROXY=http://127.0.0.1:7890 BILI_LIVE_SMOKE=1 \
  /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python \
  -m pytest tests/test_live_subtitle_cli_smoke.py -s -v
```

- **Result: `21 passed in 2.13s`, exit 0** — the live case executed (not skipped); no throttle, no retry needed,
  so the single bounded invocation budget is respected (one run, first attempt).
- **Evidence line (fresh, this run — new `run_id`, not the recorded one):**

  ```
  live subtitle CLI smoke evidence: part_source=fixed-sample work_id=BV1S8hA6MEvy:p0 sessdata=present
  probe_exit=0 probed=1 with_tracks=1 without_tracks=0 probe_failed=0 track_count=1 tracks=ai-zh:ai
  harvest_exit=0 run_id=f483460e60ea45dea71a2b41a9e284de attempted=1 stored=1 unchanged=0 no_subtitle=0
  failed=0 remaining_without_transcript=0 source_kind=subtitle-ai language=ai-zh version=1 segments=2913
  transcripts=1 attempts=1 pending_after=0
  ```

- **`part_source=fixed-sample`**, `sessdata=present` (presence only; resolved by the shipped rule from
  `BILI_SESSDATA` sourced out of the control `.env`, no `--sessdata` flag). Every field matches the plan's
  recorded line field-for-field; only `run_id` differs, as a new run must.
- **It stored, so the bounded-upstream-observation escape hatch does not apply** — the credential gate was
  satisfied (`sessdata=present` is printed by the run's own environment line), and the run's own row assertions
  are what make the fields evidence: `stored=1` / `segments=2913` cannot be printed unless the harvest really
  wrote a version-1 transcript with 2913 ordered segments and the run/attempt evidence rows.
- **Leak scan of the captured log (boolean result only, no value printed):** the `BILI_SESSDATA` value appears
  **0** times; `subtitle_url`, `aisubtitle`, `http(s)://`, `SESSDATA=`, and the proxy address appear **0** times.
  The one line the run prints is bounded facts only, as designed.
- The three-invocation ledger recorded in `implementer-task-3-report.md` (attempt 1 aborted by a smoke-side
  defect, attempts 2–3 the evidence) is **not normalized** by this gate: my re-take is a *fourth, independent*
  invocation of the finished test, and the plan/iteration-close note about the original deviation stays as
  recorded.

## 4. The two `unreadable archive database` branches at runtime — **F-QA-001 (Warning)**

Routed by the QC consolidation as a seat-1 observation, and by the plan's own recorded nit ("neither a test nor
a doc sentence … the QA gate exercises them at runtime"). Exercised on the HEAD code, imported explicitly from
the worktree (`bili_asr.__file__` printed and asserted to be the worktree copy; the control venv ships an
editable install of the *control* checkout, so provenance was pinned).

### 4.1 What works

| Case | `probe-subs` | `harvest-subs` |
|---|---|---|
| `archive.db` is a **text file** (no SQLite magic) | `probe-subs: unreadable archive database at <root> (DatabaseError)`, exit 1, stdout empty | same line with `harvest-subs:`, exit 1 |
| `archive.db` **truncated** to half its size | bounded line, exit 1 | bounded line, exit 1 |
| `archive.db` is **0 bytes** | `probe-subs: archive database predates the transcript schema; rebuild it (delete <root>/archive.db and re-run fetch-meta)`, exit 1 | initializes the schema and exits 0 with `attempted=0` (the shipped `open_database` semantics for an existing file) |
| `archive.db` **absent** | `probe-subs: no archive database at <root>; run fetch-meta to create it`, exit 1, and the root stays **completely empty** (no file, not even `coordinator/`) | same line, exit 1; only `coordinator/archive-writer.lock` appears (the documented writer-lock side effect) |

So the line the assignment asked for is real and reachable for **both** commands. A pinned test is nevertheless
**still owed** for the whole branch — it is asserted nowhere (`grep -rn "unreadable archive database" tests/
docs/ README.md` returns only the two `cli.py` sites).

### 4.2 What does not: a corrupt-but-openable database escapes `probe-subs` as a raw traceback

`archive.db` whose SQLite header is intact but whose page 1 body is damaged (the canonical "database disk image
is malformed" state — unclean shutdown, disk-full, partial copy) passes the existence guard, connects through
the new `mode=ro` path, and passes `PRAGMA schema_version` (a header read). The failure then surfaces on the
**next** statement — `require_subtitle_schema(connection)` inside `_open_subtitle_connection`
(`cli.py:636`) — which sits *outside* the bounded `except (OSError, sqlite3.Error)` handler of
`_open_read_only_connection` (`cli.py:569`). The exception is not a `SchemaContractError`, so nothing catches it:

```
$ … probe-subs --limit-parts 1 --archive-root <corrupt root>
exit=1, stdout empty, stderr = 23 lines of raw Python/SQLite internals, ending:
  File "…/src/bili_asr/storage/database.py", line 116, in _transcripts_columns
    row[1] for row in connection.execute("PRAGMA table_info(transcripts)")
sqlite3.DatabaseError: database disk image is malformed
```

- **Why this is in scope and not an inherited hazard:** the *write-capable* read path
  (`_open_read_connection`) and its `unreadable archive database` line are pre-existing (present at `c5a9b82`,
  `cli.py:511`), and they answer the same corrupt file correctly — the shipped `status` command on the *same*
  database prints `status: unreadable archive database at <root> (DatabaseError)` with exit 1. The
  `mode=ro` path and the `require_subtitle_schema`-after-open discipline were added to this plan by the fix
  wave `7e57eb6` (`git log -S` pins both to that commit). The new read-only path is therefore **strictly less
  bounded than the shipped path it claims parity with**, in its own words: *"an unreadable file is reported
  bounded exactly as the write-capable read path reports it"* (`cli.py:551-554`, new in this range).
- **Contract hit:** the plan's STOP list includes "Any output or row contains a signed URL, raw JSON body,
  cookie, or **traceback** → stop"; the exit taxonomy is "fixed message" per code; and the house rule for the
  whole read-command family is bounded text, never raw SQLite internals.
- **Blast radius, stated honestly:** `harvest-subs` is *not* affected (its `open_database` reads `sqlite_master`
  inside the bounded handler, so it reports the line and exits 1). The exit code also happens to be 1, because
  an uncaught exception exits 1 — the defect is the **output surface**, not the code. No secret is exposed: a
  sentinel scan of the 23 lines found no credential, no `subtitle_url`, no URL, no body. Trigger likelihood is
  low-moderate (it needs a damaged database file), which is why this is a Warning and not a Critical.
- **Fix (minimal, ~4 lines):** in `_open_subtitle_connection`, keep `SchemaContractError` → the rebuild line,
  and add a second handler for `sqlite3.Error` → the same `unreadable archive database at {archive_root}
  ({type(exc).__name__})` line + `return None` (exit 1), so both open paths bound a malformed image identically.
  A pinned regression case (both commands) is owed in the same wave: the branch has no test today.

### 4.3 (context) The fix wave's other new bound

`7e57eb6` also wrapped `_normalize_video_summary_item`'s `VideoSummary` construction into the bounded
`GatewayShapeError("video item is not normalizable")` (`bilibili_api_gateway.py:178-191`) — outside the plan's
declared file list but inside the reviewed range and explicitly re-read by QC seat 1 (`qc1.md:441-448`, focused
gateway run green). I did not re-review its logic (L3's job); no coverage claim is made either way.

## 5. F-001 at runtime — CLOSED

Seeded a valid archive (`archive.db` = shipped schema + one stored part), then:

| Runtime call | stdout | stderr | exit |
|---|---|---|---|
| `probe-subs --bvid ""` | empty | `probe-subs: unknown --bvid ` | **1** |
| `probe-subs --bvid "   "` | empty | `probe-subs: unknown --bvid    ` | **1** |
| `probe-subs --bvid "BV1SubA\x01"` | empty | `probe-subs: unknown --bvid BV1SubA\x01` (byte-exact echo, `od -c` confirmed) | **1** |
| `harvest-subs --bvid "" --limit-parts 1` | empty | `harvest-subs: unknown --bvid ` | **1** |
| `harvest-subs --bvid " " --limit-parts 1` | empty | `harvest-subs: unknown --bvid  ` | **1** |

Nothing is created or written: the root before/after the five calls holds `archive.db` plus the
`harvest-subs` writer lock only, and `acquisition_runs` / `acquisition_attempts` / `transcripts` /
`transcript_segments` are all **0 rows**. The original Warning (a blank `--bvid` answered as `unexpected error`
+ exit 2) is confirmed closed on the shipped code path, not only in the parametrization.

**Pre-iteration database (`tests/test_subtitle_cli.py:1355` legacy case), reproduced at runtime** on a database
built with the shipped metadata script plus the previous iteration's transcript DDL — both commands exit **1**
with the **composed** line carrying the full path (`<command>: archive database predates the transcript schema;
rebuild it (delete <root>/archive.db and re-run fetch-meta)`), stdout empty; and `status --archive-root <root>`
still exits **0** (`users: 1 / videos: 1 / parts: 1 / …`), i.e. the metadata path keeps working.

**Missing database**: both commands exit 1 with the shipped `no archive database at <root>; run fetch-meta to
create it` line; a `probe-subs`-only run on a fresh root leaves the root **empty** (the read-only promise holds
structurally — no lock, no database).

## 6. DoD mapping — plan `## Acceptance / Done Criteria` (11 boxes, all still unchecked; the PM ticks)

| # | Box (abridged) | Evidence | Type |
|---|---|---|---|
| 1 | `harvest-subs` needs a bound (or one `bvid:pN`) and stores normalized transcripts / bounded evidence, idempotent re-runs, immutable versions | Live: `attempted=1 stored=1 … segments=2913` + the smoke's row assertions; offline: `test_harvest_stores_normalized_rows_for_a_cc_and_an_ai_part`, `test_reacquiring_an_unchanged_caption_adds_no_version_and_no_segment`, `test_a_revised_caption_appends_version_two_and_keeps_version_one_readable`, `test_captionless_and_failing_parts_keep_bounded_evidence_and_exit_zero`; bound required: usage parametrization | fresh (live) + reused |
| 2 | `probe-subs` prints track metadata only, prints zero-track parts explicitly, writes nothing, never creates the database | Fresh runtime: fresh root → shipped line, exit 1, root stays empty; live `probe_exit=0 probed=1 with_tracks=1 track_count=1 tracks=ai-zh:ai`; offline `test_probe_subs_prints_the_locked_lines_and_leaves_nothing_behind` | fresh + reused |
| 3 | Summary always prints all four counts incl. zeros, run id, credential presence, remaining-without-transcript; no coverage claim | Live: `run_id=f483460e… attempted=1 stored=1 unchanged=0 no_subtitle=0 failed=0 remaining_without_transcript=0` with `sessdata: present`; fresh runtime zeros-case: `run_id=b0a3633… attempted=0 stored=0 unchanged=0 no-subtitle=0 failed=0 remaining_without_transcript=0` with `sessdata: absent`; offline `test_the_summary_prints_every_count_and_an_empty_selection_exits_zero` | fresh + reused |
| 4 | Selection rule documented, deterministic, overridable with `--language`; source kind/language/version reported per part | Live: `source_kind=subtitle-ai language=ai-zh version=1`; docs shapes at `docs/metadata-storage.md:121,140` match `cli.py:903,1003` field-for-field; property/pinning tests in the suite (QC Q3-01 closed) | fresh + reused |
| 5 | Repeated bounded runs progress; a targeted stored part can be re-acquired (`unchanged` or a new version) | Offline E2E (`unchanged`/no new version; revised body → v2 with v1 readable; never-attempted-first ordering) | reused (green in the fresh 1311) |
| 6 | Pre-iteration database → both commands exit 1 with the fixed rebuild line; metadata commands keep working | **Fresh runtime** (§5) — both commands byte-exact line + exit 1, `status` exit 0 | fresh |
| 7 | No legacy sidecar read/written; neither command writes `subtitles/raw/` or `transcripts/srt/` | Offline `test_neither_command_leaves_a_sidecar_or_a_transcript_projection` + no-legacy assertions; live root file set = `archive.db` + `coordinator/archive-writer.lock` only (the smoke's own assertion, re-run here) | fresh + reused |
| 8 | Exit taxonomy and bounded codes pinned by tests; **docs match behaviour** | Taxonomy/usage/bounded-code tests all green; **but `F-QA-001`**: the `unreadable archive database` branch is unpinned *and* incomplete for `probe-subs`, so the behaviour of the new read-only open path does not match its own documented promise | **partial** |
| 9 | Offline suites green (baseline: plan 2's post-merge count) | **Fresh**: `1311 passed, 4 skipped`, exit 0 (baseline `1202/3` + 109 new tests + the new opt-in gate) | fresh |
| 10 | Bounded live smoke recorded (real transcripts or an explicit bounded blocker) | **Fresh re-take**: 21 passed, exit 0, `stored=1`, `segments=2913`, `sessdata=present`, `part_source=fixed-sample` (§3.3) | fresh |
| 11 | `git diff --check` clean | **Fresh**: `git diff --check c5a9b82..7e57eb6` → clean | fresh |

**10 of 11 boxes are fully evidenced; box 8 is partial solely because of `F-QA-001`.**

## 7. Residual register — CORRECT, no new residual registered by this plan

`{PROJECT_DIR}/_default/residuals.json` holds exactly one entry: **`R1`** (source plan
`20260911-subtitle-gateway`, `severity: low`, `decision: defer`, owner `@project-manager`, target *"the next
plan whose file list includes `src/bili_asr/sources/bilibili_api_gateway.py` (the CLI plan does not; expected:
the audio/ASR iteration)"*, lifecycle `iter-2026-09-subtitle-transcript-sqlite`).

- **Target check:** the plan's *declared* file list (Tasks 1–3) does not include the gateway adapter, so the
  trigger has not fired by its own wording. Note for the record: the fix wave did touch that file
  (`7e57eb6`: `_normalize_video_summary_item` wrap, +14/−7), but that change is a metadata-normalizer error
  bound and does **not** touch the `user`-module import surface R1 is about — R1's substance is untouched and
  its retarget stays honest. (PM may optionally add one clause to R1's target noting that a *touch* of the file
  that does not change the import surface does not fire the trigger; not required.)
- **Nothing else is registered, correctly** — the live-smoke three-invocation deviation has no defect and no
  closure condition, so it stays a durable note (plan summary + QC consolidation + iteration close), not a
  register row.
- **May the plan proceed to Done with `R1` open? Yes.** It is `low`/`defer`, its target is a *future* plan, this
  range's diff contains no `sources/` import-surface change, and the two predecessor plans already merged with
  it open. (Done is still gated on the merge and on `F-QA-001`'s disposition — see §9.)

## 8. Iteration-level re-confirmation — A1–A12 still hold at `7e57eb6`

QC seat 3's mapping (no criterion falsified, A7/A8 strengthened, A9's precision flag lifted) is **re-confirmed**
against my own fresh runs; nothing in my evidence changes it.

| # | My fresh evidence | Status |
|---|---|---|
| A1 | Live probe line shapes (`probed=1 with_tracks=1 without_tracks=0 failed=0`, `track_count=1`, `tracks=ai-zh:ai`); offline zero-track line assertions | holds |
| A2 | Live `transcripts=1 segments=2913 source_kind=subtitle-ai language=ai-zh version=1`, asserted against the persisted rows by the smoke itself | holds |
| A3 | Offline E2E (unchanged re-run, revised body → v2, v1 readable) green in the fresh suite | holds (offline by design) |
| A4 | Offline E2E (`no-subtitle` + timestamped attempt evidence, later-run eligibility) green | holds |
| A5 | Bounded-code taxonomy tests + no-leak scans green in the fresh suite | holds |
| A6 | Plan 2's schema/repository evidence; this range touches no storage schema file | holds (not re-run by me) |
| A7 | Live root file set re-asserted: `archive.db` + writer lock only; no sidecar, no `subtitles/raw/`, no `transcripts/srt/`; offline zero-sidecar assertions | holds (strengthened evidence re-confirmed) |
| A8 | Live `sessdata=present` presence-only; suite no-leak scans over output and every persisted row green; run log carries no credential/URL sentinel; the loud opted-in credential gate exercised (live case *ran*, did not skip) | holds (strengthened re-confirmed) |
| A9 | Live summary line with all four counts incl. zeros + `run_id` + credential presence + `remaining_without_transcript` | holds |
| A10 | Offline enumeration-progress/ordering tests green | holds |
| A11 | Offline suite green **and** the live smoke yields real normalized rows (today's run: `stored=1`, 2913 segments) | holds |
| A12 | Docs' summary shapes (`docs/metadata-storage.md:121,140`) match `cli.py:903,1003`; the recorded live line (`:546-553`) includes `run_id=`; README's workflow block carries the ⚠️ boundary note and the lock paragraph | holds |

## 9. Verdict — **Needs fixes**

- **One Warning, `F-QA-001`** (§4.2): with a damaged-but-openable `archive.db`, `probe-subs` emits a 23-line raw
  Python/SQLite traceback instead of the bounded `unreadable archive database` line, contradicting the new
  read-only path's own documented parity with the shipped write-capable path (`cli.py:551-554`) and the plan's
  STOP-class rule against traceback output. Exit code stays 1; no secret is exposed; `harvest-subs` and the
  shipped `status` are unaffected. Minimal fix: bound `sqlite3.Error` around the post-open
  `require_subtitle_schema` call in `_open_subtitle_connection` → same line, `return None` (exit 1). A pinned
  case for the branch (both commands) is owed in the same wave.
- **Everything else the gate was routed to verify is green**: alignment and byte-exact diff composition; 1311
  passed / 4 skipped + the AST/no-leak scans; the fresh bounded live smoke storing a real transcript; F-001
  closed at runtime for blank, whitespace and control-character selectors on both commands; the legacy-schema
  and missing-database guards; `git diff --check`; the residual register; A1–A12.
- **Where this leaves the merge:** the PM owns the disposition. Either (a) a **narrow fix wave** for
  `F-QA-001` + its pinned test (my recommendation — it is 4 lines and one test, and it closes the exact class
  of gap the QC tri routed to me), or (b) an explicit **residual** with owner/trigger if the PM judges a
  corrupt-database output surface deferrable; on that path I would re-verify the residual text and the plan
  could go to Done with it open, as `R1` is. I do **not** recommend merging as-is while a documented promise in
  the changed code is false at runtime.
- **The plan is not marked Done by this gate** — the merge precedes Done and the PM owns both.

## 10. Reproduction steps

```bash
# 0. alignment
cd /root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-cli-cutover
git rev-parse HEAD    # 7e57eb62d35d33b8effee6b21bac8b0b8f4d70c1
git status --porcelain   # empty (remove .pytest_cache/.test-tmp if a previous run left them)

# 1. offline suite + scans
cd bilibili-asr-archive
/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest -q -rs   # 1311 passed, 4 skipped

# 2. bounded live smoke (credential sourced, never echoed; one run)
set -a; source /root/workspace/bilibili-asr-archive/.env; set +a
BILI_HTTP_PROXY=http://127.0.0.1:7890 BILI_LIVE_SMOKE=1 \
  /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python \
  -m pytest tests/test_live_subtitle_cli_smoke.py -s -v      # 21 passed, exit 0

# 3. F-QA-001 (corrupt-but-openable database)
R=$(mktemp -d)
PY=/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python
python3 -c "import sqlite3;c=sqlite3.connect('$R/archive.db');c.executescript('create table seed(x);');c.commit();c.close()"
python3 -c "f=open('$R/archive.db','r+b');f.seek(64);f.write(b'\x00'*4096);f.close()"
SRC=$PWD/src
PYTHONPATH=$SRC $PY -c 'import sys;from bili_asr.cli import main;sys.exit(main(sys.argv[1:]))' \
  probe-subs --limit-parts 1 --archive-root "$R"     # 23-line traceback, exit 1  ← defect
PYTHONPATH=$SRC $PY -c 'import sys;from bili_asr.cli import main;sys.exit(main(sys.argv[1:]))' \
  status --archive-root "$R"                          # bounded one-liner, exit 1  ← the shipped path

# 4. F-001 + guards: seed a valid archive, then
#    probe-subs --bvid ""            → "probe-subs: unknown --bvid ", exit 1
#    probe-subs --bvid "   "         → same line with the padded value, exit 1
#    harvest-subs --bvid "" --limit-parts 1 → "harvest-subs: unknown --bvid ", exit 1
#    (legacy database) both commands → the composed rebuild line, exit 1; `status` → exit 0
```

## 11. Limitations / not tested

- **No L3 re-review.** I did not re-derive code logic, selection semantics, or the gateway/storage contracts;
  those are the QC tri's lens and its Fix wave verdict stands. My §4.3 note is scope disclosure, not review.
- **One live invocation only** (plus the smoke's own offline rehearsals). A `rate_limited`/`not_found` live
  branch was not produced — the endpoint answered on the first attempt, so no bounded-blocker path was
  exercised live. The anonymous (`sessdata=absent`) live tier was not exercised (the credential was present by
  design of the routed command); its offline rehearsals are green.
- **A9/A12 are output-shape checks, not corpus claims** — nothing here says anything about caption coverage or
  quality, and the fresh run covers one part of one public sample.
- **`F-QA-001`'s blast radius is measured, not exhaustive**: I exercised four database states (valid, missing,
  non-database, truncated, empty) plus the page-1-corrupt state. Other SQLite failure modes (locked database,
  permission-denied, I/O error mid-query) were not enumerated; the permission/OSError class is inside the
  existing bounded handler by inspection only.
- I did not run `uv sync`, commit, checkout, or touch any control-venv state; no file outside
  `review/qa-gate.md` and the plan's `## QA Gate Summary` was modified.

## Recommended owners

| Item | Owner | Trigger |
|---|---|---|
| `F-QA-001` bound + pinned regression case for the `unreadable archive database` branch (both commands) | `fullstack-dev` (fix wave) → `qa-engineer` (re-verify) | before the integration merge, or re-dispatched by the PM as a residual with owner/trigger |
| Tick the 11 acceptance boxes / fill `## Review Gate Summary` with the merge | `project-manager` | after `F-QA-001`'s disposition |
| Keep the three-invocation live deviation as a durable note (not a residual) | `project-manager` | iteration close |
| `R1` stays open, target unchanged (optional: note that a non-import-surface touch of the file does not fire it) | `project-manager` | the audio/ASR iteration |

---

## Re-verification (round 2 — fix wave `0e0ea81`, `F-QA-001`)

**Verdict: Approve (recommend merge).** `F-QA-001` is closed, independently revert-proofed, and pinned by a
regression case that fails without the fix. The wave bounds only the storage-side failure classes, leaves the
exit taxonomy and every locked output shape intact, and changes nothing else (`+151/−0` across the 3 files the
plan already owns). One new **Suggestion** (`F-QA-002`, §R7) is a docstring sentence about a path that is not
user-reachable; it does not block the merge and carries a one-line correction. DoD is now **11/11 boxes**, and
the plan may proceed to Done with `R1` open. The plan is **not** marked Done here — the merge precedes Done and
the PM owns it.

### R1. Alignment at the new HEAD — PASS

| Check | Result |
|---|---|
| `pwd` | `.worktrees/20260911-subtitle-cli-cutover` — the Assignment's `Review cwd` |
| Branch | `feature/20260911-subtitle-cli-cutover` |
| HEAD | `0e0ea812bb9f8e28c8ca036a298c61e7730f3201` = `0e0ea81` (the fix-wave head the Assignment names) |
| Tree | `git status --porcelain` empty before and after every run; HEAD never moved |
| Round-1 HEAD | `7e57eb6` = the fix wave's base; the live range `c5a9b82..0e0ea81` is 17 files |
| Fix range | `git diff --stat 7e57eb6..0e0ea81` = **3 files, +151/−0** (`--numstat`: `15/0` docs, `19/0` cli.py, `117/0` tests — additions only, nothing removed or rewritten); `git diff --check 7e57eb6..0e0ea81` clean |
| In-plan scope | All three files are in the plan's own file lists (Task 1 `cli.py` + test, Task 2 test, Task 3 docs); no `sources/` or storage-schema file is touched, so `R1`'s trigger is untouched |

**`review/qa-fix-diff.md` vs the live diff — diff body byte-identical, header defective.** The fenced body
equals `git diff --no-color 7e57eb6..0e0ea81` **byte for byte** (9697 bytes, 195 lines, all 3 files) — the body
is complete and correct. Its *header* is not: line 5 is cut mid-sentence (`Scope: F-QA-001 (bound the probe`)
and the opening ````` ```diff ````` fence is missing entirely (the closing fence at line 200 is present). Both
sibling artifacts are well-formed (`qc-fix-diff.md:7`, `branch-diff.md:10` carry ```` ```diff ````). This is an
artifact-composition defect, **not** a diff/review-content defect: nothing is missing from the diff itself, so
it does not gate the verdict; it is worth one line in the PM's merge note so the review package is not
misquoted later.

### R2. The fix wave — proven to bound exactly `F-QA-001` (diff read)

`src/bili_asr/cli.py` gains exactly two hunks, no deletions: an 8-line docstring paragraph and one new clause on
the existing `try` in `_open_subtitle_connection` (`cli.py:651-661`, current numbering):

```python
    except (OSError, sqlite3.Error) as exc:
        # The guard executes SQL against the file, so a malformed image surfaces
        # on its first read rather than on ``connect``: answer it exactly as
        # both open helpers answer their own statements (F-QA-001).
        connection.close()
        print(
            f"{command}: unreadable archive database at {archive_root} "
            f"({type(exc).__name__})",
            file=sys.stderr,
        )
        return None
```

The clause sits **after** `except SchemaContractError`, which still wins for a pre-iteration database
(`SchemaContractError` is a `RuntimeError`, not a `sqlite3.Error`, so the ordering is also class-safe), and the
printed text is byte-identical to the two shipped handlers (`cli.py:534-538` write-capable read,
`cli.py:572-576` read-only open). `connection` is provably non-`None` at that point (the `None` early-return is
three lines above), so the unguarded `close()` is safe. `return None` keeps exit `1` via the callers' existing
`if connection is None: return 1`.

### R3. `F-QA-001` re-reproduced at runtime — **CLOSED**

Freshly built damaged-but-openable database in `/tmp` (shipped schema + one stored part, then `seek(64)` +
4096 zero bytes — header left intact, asserted `b"SQLite format 3\x00"`), real CLI in a subprocess with
stdout/stderr separated and `bili_asr` imported explicitly from the worktree
(`bili_asr.__file__ = …/.worktrees/20260911-subtitle-cli-cutover/bilibili-asr-archive/src/bili_asr/__init__.py`;
`tests/conftest.py` also puts that `src` at `sys.path[0]`, so the suite and these runs both used worktree code):

| Command | stdout | stderr | exit | file |
|---|---|---|---|---|
| `probe-subs --bvid BV1SubA` | empty | `probe-subs: unreadable archive database at <root> (DatabaseError)` — one line, byte-exact | **1** | byte-identical afterwards; root holds `archive.db` only |
| `harvest-subs --bvid BV1SubA --limit-parts 1` | empty | `harvest-subs: … (DatabaseError)` — same line with its own prefix | **1** | byte-identical; root holds `archive.db` + the documented writer lock only |

- **The 23-line traceback is gone**: no `Traceback (most recent call last)`, no `File "…"` frame, no
  `sqlite3.` internals anywhere in either stream; a sentinel scan (traceback / `subtitle_url` / `aisubtitle` /
  `SESSDATA=` / URL / `cookie`) is clean. Round 1 measured 23 traceback lines here; this round measures 1
  bounded line.
- **Parity claim verified, not assumed:** shipped `status` and `runs` on the *same* damaged file print
  `status:` / `runs: unreadable archive database at <root> (DatabaseError)` — the new handler's line is
  **identical apart from the command prefix**, exit 1, file unmodified. That is exactly what the new doc
  paragraph promises.

**Revert-proof, run independently (no git writes).** A copy of the whole package with `src/bili_asr/cli.py`
replaced by `git show 7e57eb6:…cli.py` (diff-verified to differ from live *only* by the fix hunk; provenance
asserted, `F-QA-001 handler present: False`):

| Tree | `tests/test_subtitle_cli.py` (whole module) | The 3 new cases |
|---|---|---|
| pre-fix (`cli.py` @ `7e57eb6`) | **83 passed, 1 failed** | `[damaged-page-1]` **FAILS** → `require_subtitle_schema` → `_has_subtitle_schema` → `_transcripts_columns` (`database.py:116`, `PRAGMA table_info(transcripts)`) → `sqlite3.DatabaseError: database disk image is malformed`, escaping through `cli.py:636` into `main` |
| post-fix (`0e0ea81`) | **84 passed** | 3 passed |

The failure reproduces the implementer's reported revert-proof signal exactly, so the new case is a real
regression guard rather than a test written to the fixed behaviour. The wave's **only** behavioural delta in
that module is that one case: the other 83 results are identical pre- and post-fix.

### R4. Neighbouring cases re-checked — no regression

Same driver, all byte-exact assertions on the real CLI (69 behaviour checks, all pass):

| State | `probe-subs` | `harvest-subs` | vs round 1 |
|---|---|---|---|
| not a database at all | bounded line, exit 1, no repair | bounded line, exit 1 | unchanged |
| truncated to half its size | bounded line, exit 1 | bounded line, exit 1 | unchanged |
| **missing** `archive.db` | `no archive database at <root>; run fetch-meta to create it`, exit 1, **root stays empty** | same line, exit 1, only the writer lock appears | unchanged |
| healthy database (full schema, empty selection) | exit 0, `sessdata: absent` + `probed=0 with_tracks=0 without_tracks=0 failed=0`; file byte-identical | exit 0, `attempted=0 stored=0 unchanged=0 no-subtitle=0 failed=0 remaining_without_transcript=0`; schema intact, the run row recorded | unchanged |
| pre-iteration schema | composed rebuild line (full path), exit 1 | same, exit 1; `status` still **exit 0** (`users: 1`) | unchanged |
| zero-byte file | rebuild line, exit 1, file still **0 bytes**, root untouched | initializes the file, exit 0, `attempted=0` | unchanged (the documented asymmetry) |

Run with `BILI_HTTP_PROXY` pointed at a dead local port and no credential in the environment, so any accidental
gateway call would have failed loudly; none did — every healthy-database case resolved an empty selection
before the gateway.

### R5. Full offline suite at `0e0ea81` — PASS

```
cd .worktrees/20260911-subtitle-cli-cutover/bilibili-asr-archive
/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest -q -rs
```

**`1314 passed, 4 skipped in 49.26s`, exit 0** — exactly the implementer-reported count and exactly round 1's
1311 + the 3 new pinned cases. The 4 skips are still precisely the opt-in live gates
(`test_bilibili_api_gateway.py:3380`, `test_live_metadata_smoke.py:329`,
`test_live_subtitle_cli_smoke.py:271`, `test_live_subtitle_smoke.py:438`), each `SKIPPED … set
BILI_LIVE_SMOKE=1 to request it`. Focused module: `tests/test_subtitle_cli.py` → **84 passed**.

### R6. Scope judgment — bounded, and no collateral behaviour change

- **Only storage-side classes are caught.** The new clause is `(OSError, sqlite3.Error)`; there is no
  `except Exception`, no `BaseException`, no bare `except` (asserted by source inspection: exactly 2 handlers in
  the function). A `TypeError` raised inside the guard **escapes** the handler, verified at runtime by
  monkeypatching `bili_asr.storage.require_subtitle_schema` to raise — it propagates out of
  `_open_subtitle_connection` as itself, so no programming error is swallowed or relabelled.
- **Exit taxonomy intact.** The handler returns `None` → the callers' existing `if connection is None: return 1`;
  no new exit code, no changed code, and every neighbouring state keeps the exit code round 1 measured (0 for a
  healthy database, 1 for every refusal). The taxonomy tests remain green inside the 1314.
- **Every locked output shape intact.** The fixed string is character-for-character the shipped
  `unreadable archive database` line; the rebuild line, the missing-database line, the summary line, the probe
  line and the `unknown --bvid` line are all unchanged at runtime (R4, plus round 1's `F-001` table, whose code
  path this wave does not touch).
- **Nothing beyond `F-QA-001` moved.** Additions only (`+151/−0`), 2 hunks in one function, 2 doc paragraphs,
  3 test cases; every other subtitle-CLI test result is identical pre- and post-fix (R3). The doc paragraphs
  match observed behaviour, including the truncated-file and zero-byte claims and the `status`/`runs` parity
  sentence.

### R7. `F-QA-002` (Suggestion — documentation accuracy, **not** blocking)

The new docstring paragraph ends: *"anything outside that class escapes as the unexpected internal error the
command handlers report."* That is **false at runtime** for this call site. `_open_subtitle_connection` is
invoked **before** the command's `try` (`cli.py:876` in `_cmd_probe_subs`, `cli.py:979` in `_cmd_harvest_subs`),
and `main`/`_dispatch_command` (`cli.py:2598-2613`) catch nothing broad, so a non-storage exception from the
guard prints a **raw traceback and exits 1** instead of the documented
`<command>: unexpected error` + exit 2:

```
$ runner-with-guard-raising-TypeError probe-subs --limit-parts 1 --archive-root <healthy root>
exit=1, stderr = traceback … File "…/cli.py", line 644, in _open_subtitle_connection
                                   require_subtitle_schema(connection)
                                  TypeError: guard programming error
```

- **Why it does not block.** The path needs a Python-level bug inside `require_subtitle_schema`, which only
  executes SQL and compares sets — both of its failure modes are `sqlite3.Error`/`OSError`, i.e. exactly the
  bounded class. No user-reachable input reaches the false sentence, no user-visible behaviour differs from the
  pre-fix code (this escape behaviour is identical at `7e57eb6`), and no DoD box is falsified: box 8's doc
  claim is about `docs/`, whose two new paragraphs I verified against runtime behaviour. Severity is a
  Suggestion, not a Warning, and a new fix wave for one comment would be disproportionate.
- **One-line correction, if the PM wants zero open findings.** Replace that final clause with the truth, e.g.
  *"a failure outside that class is a programming error and is not bounded here: it escapes this function (the
  guard is called before the command handlers' own `try`), so it reaches the interpreter as a traceback and
  exit 1 — the bounded `unexpected error` line covers only failures raised inside those handlers' `try`."*
  Comment-only edits cannot change behaviour, so folding it into the merge commit needs no re-verification;
  it is equally legitimate to record it as a durable note for the next touch of `cli.py`.

### R8. DoD — **11/11 boxes fully evidenced**

Box 8 (*"Exit taxonomy and bounded codes are pinned by tests; docs match behaviour"*) was the only partial box
in round 1, and solely because of `F-QA-001`. It is now fully evidenced:

- the `unreadable archive database` branch is pinned for **both** commands in the two damage variants
  (`test_an_unreadable_archive_database_is_one_bounded_line_on_both_commands[damaged-page-1]` — the variant
  that fails pre-fix — and `[not-a-database]`), with the exit code, the empty stdout, the byte-exact stderr line,
  the no-repair byte comparison and the archive-root file set all asserted;
- the zero-byte asymmetry is pinned (`test_a_zero_byte_database_is_initialized_by_harvest_and_refused_by_probe`);
- the two new `docs/metadata-storage.md` paragraphs match observed behaviour (damaged / not-a-database /
  truncated → one bounded line, exit 1, both commands; zero-byte asymmetry; `status`/`runs` parity; no repair);
- the taxonomy tests and the AST/no-leak scans remain green in the fresh 1314.

Boxes 1–7 and 9–11 keep their round-1 evidence (unchanged code paths; box 9's suite is re-run fresh above).
**Round-1 `10/11` (box 8 partial) → round-2 `11/11`.**

### R9. Residual register — unchanged and correct

`{PROJECT_DIR}/_default/residuals.json` still holds exactly one entry: **`R1`** (source plan
`20260911-subtitle-gateway`, `severity: low`, `decision: defer`, owner `@project-manager`, target *"the next
plan whose file list includes `src/bili_asr/sources/bilibili_api_gateway.py`"*,
lifecycle `iter-2026-09-subtitle-transcript-sqlite`). This plan holds **none** — correctly, since `F-QA-001` is
closed in code rather than deferred, and no new finding of this round is register-worthy (`F-QA-002` is a
comment-accuracy Suggestion with no defect state to track).

**May the plan proceed to Done with `R1` open? Yes** — unchanged from round 1: `low`/`defer`, its target is a
future plan, this range touches no `sources/` import surface, and both predecessor plans already merged with it
open. Done remains gated on the merge, which the PM owns.

### R10. Live evidence — round-1 re-take **stands**; not re-run (agree with the Assignment)

I did **not** set `BILI_LIVE_SMOKE` and did not source the credential file: `F-QA-001` is a damaged-database
error path with no dependency on the live path or on credentials. The added handler executes **only** when
`require_subtitle_schema` raises; on a healthy database the guard returns normally — that is the path round 1's
bounded live smoke exercised at `7e57eb6`, and this wave changes nothing on it (no line of the live probe or
harvest flow is modified). Round 1's recorded evidence therefore remains valid for the unchanged live path:
one invocation, exit 0, `21 passed`, `part_source=fixed-sample sessdata=present probe_exit=0 probed=1
with_tracks=1 track_count=1 tracks=ai-zh:ai harvest_exit=0 … stored=1 … segments=2913`, log sentinel-clean, with
the three-invocation deviation kept as recorded. A1–A12 are likewise untouched by this wave (storage-side error
path only) and stand on round 1's re-confirmation.

### R11. Limitations

- **No L3 re-review** of the wave: I verified the handler's class boundary, ordering, call sites, exit path and
  output parity, and probed the escape behaviour; I did not re-derive unrelated logic — that is the QC lens.
- **`F-QA-002`'s path is probed by injection, not by natural occurrence**: no shipped input reaches it (by
  construction), which is precisely why it is a Suggestion. If a future change makes the guard able to raise
  outside the storage classes, the false sentence would then matter.
- **SQLite failure modes remain non-exhaustive**: I exercised damaged-page-1, not-a-database, truncated,
  zero-byte, missing, pre-iteration and healthy; locked-database / permission-denied / mid-query I/O error were
  not enumerated (the permission/`OSError` class is inside the bounded handler by inspection and by the same
  class tuple as the shipped paths).
- **One artifact defect is recorded, not fixed** (`qa-fix-diff.md`'s truncated header, §R1): it is outside my
  write scope and does not affect the diff content.
- No `uv sync`, no commit, checkout or push, no control-venv mutation; scratch lived in
  `/tmp/qa-reverify-20260911/` and was removed. Files written this round: this report's `## Re-verification`
  section and the plan's `## QA Gate Summary` Evidence line — nothing else.

### R12. Verdict and owners

**Approve (recommend merge).** `F-QA-001` closed and revert-proofed; suite `1314 passed, 4 skipped`; DoD 11/11;
residual register clean with `R1` open and its target unfired; no blocking item remains. The plan stays
`InProgress` — the merge precedes Done and the PM owns both.

| Item | Owner | Trigger |
|---|---|---|
| Merge `feature/20260911-subtitle-cli-cutover` (HEAD `0e0ea81`) into `iteration/iter-2026-09-subtitle-transcript-sqlite`, then tick the 11 boxes and fill `## Review Gate Summary` | `project-manager` | now |
| `F-QA-002` one-line docstring correction (`cli.py:626-632`) — fold into the merge commit or record as a durable note; comment-only, no re-verification needed | `fullstack-dev` / `project-manager` | at or before the merge |
| Optionally repair `review/qa-fix-diff.md`'s header line 5 + opening fence (content already byte-correct) | `project-manager` | merge-note hygiene |
| `R1` stays open, target unchanged | `project-manager` | the audio/ASR iteration |
