# QA Gate Report (L4) — 20260911-transcript-storage

- Iteration: `iter-2026-09-subtitle-transcript-sqlite` · Plan: `20260911-transcript-storage`
- QA mode: `acceptance-only` + the QC-consolidated hand-off items (suite re-run, shipped-path legacy
  guarantee, ordering-pin discrimination, CLI-plan readiness, residual check)
- Seat: `qa-engineer` (L4), single session, no delegation
- Date: 2026-09-11
- Inputs read: `plans/20260911-transcript-storage.md`, `plans/20260911-subtitle-cli-cutover.md`,
  `sdd/20260911-transcript-storage/review/{qc1,qc2,qc3,qc-consolidated}.md`,
  `review/{branch-diff,fix-1-diff,fix-2-diff}.md`, `review/task-{1,2,3}-review.md`,
  implementer reports (tasks 1–3, fix waves 1–2), `progress.md`, `projects/_default/residuals.json`

## 1. Alignment (verified, not assumed)

| Probe | Value |
|---|---|
| Review cwd | `/root/workspace/bilibili-asr-archive/.worktrees/20260911-transcript-storage` |
| Working branch | `feature/20260911-transcript-storage` |
| HEAD | `4dcbf5dae7624aa704a00070c7cccad80b0c021b` (parent `5f93e05`) |
| Worktree base | `6ee7c6a` — equals `git rev-parse iteration/iter-2026-09-subtitle-transcript-sqlite` |
| `git status --porcelain --untracked-files=all` | empty **before and after** every QA run |
| `git diff --check 6ee7c6a..4dcbf5d` | clean (exit 0) |
| `.orig` / `.rej` / `.bak` residue | none |

Range arithmetic: `6ee7c6a..5f93e05` = 4 commits, 8 files, **+4028/−58** (the QC tri pack);
`5f93e05..4dcbf5d` = 1 commit, 2 files, **+57/−5** (fix wave 2); full `6ee7c6a..4dcbf5d` = 5 commits,
same 8 files, **+4080/−58**. Nothing outside the plan's declared file list changed.

### Diff-package integrity (recomputed, not read off the summary)

- `branch-diff.md`'s fenced body (175 910 bytes, 4 443 lines) is **byte-identical** to live
  `git diff 6ee7c6a..5f93e05` (`cmp` clean, md5 prefix `3c91379a73de`).
- `fix-2-diff.md`'s fenced body (6 460 bytes) is **byte-identical** to live `git diff 5f93e05..4dcbf5d`
  (md5 prefix `ea7687f8b93c`).
- **Composition replayed, not argued:** `git archive 6ee7c6a` → apply `branch-diff` → apply `fix-2-diff`
  → `diff -r` against `git archive 4dcbf5d` → **identical tree**. The two artifacts therefore describe
  exactly the reviewed state, and fix wave 2 is fully contained in the QA range.
- `fix-1-diff.md` (3 059 bytes) is a *subset* record of the L2 fix wave (`1019000..5f93e05`) already
  inside `branch-diff.md`; it is documentation of that wave, not a third composition term.

## 2. Fresh-run evidence (this seat)

All runs offline, no network, from the **worktree** package dir with the control venv interpreter
(`/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python`). Provenance was pinned
with a pytest probe: `bili_asr.storage` resolved to
`…/.worktrees/20260911-transcript-storage/bilibili-asr-archive/src/bili_asr/storage/__init__.py`
(the control venv's editable install points at the *control* checkout, so `tests/conftest.py`'s
`sys.path.insert(…/src)` is what makes the run exercise the reviewed code — verified, not assumed).

| Run | Command | Result |
|---|---|---|
| Full offline suite at HEAD | `python -m pytest -q -rs` | **1202 passed, 3 skipped in 47.71s**, exit 0 |
| Focused metadata/schema/repository set | 9 files incl. `test_storage_schema.py`, `test_transcript_repository.py`, `test_metadata_repository.py`, `test_metadata_e2e.py`, `test_metadata_cli.py`, `test_metadata_ingest.py`, `test_fetch_meta.py`, `test_meta_cursor.py`, `test_run_ledger.py` | **275 passed** |
| Named ordering test | `test_pending_enumeration_orders_never_attempted_before_the_oldest_attempt` | 1 passed |
| Collection | `test_storage_schema.py` 37, `test_transcript_repository.py` 81 | both collected and green |

The **three skips are exactly the opt-in live gates** (`BILI_LIVE_SMOKE=1`):
`tests/test_bilibili_api_gateway.py:3300`, `tests/test_live_metadata_smoke.py:329`,
`tests/test_live_subtitle_smoke.py:438`. None of those files is in the plan's 8-file range, so this plan
**adds no skip**; the count is unchanged from the pre-plan baseline (1168 → 1201 → 1202 passed, same 3).

## 3. Legacy-database guarantee on the **shipped** path (reproduced)

Method — two processes, no synthetic fixture reused:
1. **Stage 1:** `git archive 6ee7c6a` into `/tmp`, and build a genuine pre-iteration `archive.db`
   with the **old shipped bootstrap** (`open_database` from the base commit) plus committed metadata:
   one user, one video, one part, one cursor, and one legacy `transcripts` row with its segment
   (written raw, because the legacy shape has no `language`/`content_sha256`).
   Legacy objects confirmed: `transcripts` columns `{created_at, model_id, source_kind, transcript_id,
   version, video_part_id}`, no `acquisition_*`, no `v_pending_subtitles`.
2. **Stage 2:** open the same file with the **HEAD** `open_database` (shipped bootstrap, `resources.files`
   loader for both schema resources) and probe.

**18/18 checks passed**, covering every part of the routed item:

- **(a) left intact and usable**
  - pre-iteration `transcripts` columns unchanged; no new column leaked in; pre-existing legacy transcript
    row *and* its segment still readable;
  - pre-existing cursor read back (`next_page=7`) and part row intact (`cid=900001`);
  - **metadata writes work**: a new video + part + cursor written through `MetadataRepository` (in its
    documented transaction group) survived a close/re-open → `next_page=8`, `list_pending_parts()`
    served `['BV1LEGACY1:p0']`.
- **(b) no half-applied transcript objects** — `acquisition_runs`, `acquisition_attempts`,
  `v_pending_subtitles` all absent, `ux_transcripts_subtitle_content` absent, and still absent after a
  second bootstrap pass. The transcript script is *skipped*, not partially executed.
- **(c) bounded failure, not a raw SQLite error** — `require_subtitle_schema(connection)` raises
  `SchemaContractError` with the rebuild line
  `"archive database predates the transcript schema; rebuild it (delete archive.db and re-run fetch-meta)"`;
  **`TranscriptRepository(connection)` also raises `SchemaContractError`** on that database (the QC3-002
  fix wave 2 landed, verified live — not merely in the diff). The contrast was measured too: an unguarded
  `SELECT language, content_sha256 FROM transcripts` raises `sqlite3.OperationalError: no such column: language`,
  i.e. the guard replaces exactly the failure mode QC3-002 described.
- Control: a **fresh** database at the same HEAD still gets the full contract (3/3 objects) — the skip is
  legacy-specific, not a bootstrap regression.

One environment note worth keeping: the metadata repository **defers commits to its caller**, so any
pre-iteration database built by hand must commit (my first attempt silently produced an empty legacy DB
because the writes were rolled back — a probe bug, not a product defect).

## 4. QC3-001 ordering pin (independently confirmed both ways)

**(a) The fixture makes the last key falsifiable.** Replaying the committed fixture's own helper
(`_video_with_parts`) and then the fix-wave pair (page 5 inserted before page 4) through the shipped
`MetadataRepository.upsert_part` gives, inside `BV1A`:

```
(rowid, page_index): [(1,0), (2,1), (3,2), (4,3), (5,5), (6,4)]
rowid order: [0,1,2,3,5,4]     page order: [0,1,2,3,4,5]     equal? False
```

So rowid order and page order genuinely disagree inside the affected `bvid` — the key can be falsified.

**(b) Dropping the key fails the named test.** Mutations were applied to **`/tmp` copies** produced by
`git archive 4dcbf5d` (the shared checkout was never mutated; the copies are byte-identical trees):

| Mutation of the guarded `ORDER BY` | Named test |
|---|---|
| none (baseline) | passes |
| drop **`page_index ASC`** (both query variants) | **FAILS** — `At index 4 diff: 'BV1A:p5' != 'BV1A:p4'` (`test_transcript_repository.py:1424`) |
| drop `bvid ASC` | FAILS |
| drop `last_attempt_at ASC` | FAILS |
| drop the whole `ORDER BY` | FAILS |
| drop `attempted ASC` | passes — see finding **QAF-1** (provably order-preserving) |

QC3-001 is closed in both directions on the committed artifact.

## 5. Immutability and content-idempotency on the shipped database

**Static scan (`src/` + `tests/`):** the only write verbs against the transcript tables are
`INSERT INTO transcripts` / `INSERT INTO transcript_segments` / `INSERT INTO acquisition_attempts`.
There is **no `UPDATE`/`DELETE` against `transcripts`, `transcript_segments` or `acquisition_attempts`
anywhere**; the single `UPDATE` is `acquisition_runs`' documented terminal transition
(`SET finished_at, outcome WHERE run_id = ? AND outcome = 'running'`). The only `DELETE` statements in the
repository are the two FK-RESTRICT assertions in `test_transcript_repository.py` (they *expect*
`sqlite3.IntegrityError`). `src/bili_asr/storage/*` imports nothing outside the stdlib + `.models`
(no `sources` import, no sidecar/manifest/JSONL reference at all).

**Live probe (scratch DB in `/tmp`), 13/13 checks:** first acquisition → `stored`, version 1, 2 segments;
a *repeated identical* acquisition under a new run → `unchanged`, same `transcript_id`/version, **no new
transcript row, no new segment row**, and a SHA-256 digest over all transcript/segment rows and rowids is
**byte-identical** before and after (only append-only attempt evidence grew); changed content → version 2
while version 1's rows are untouched; default read returns the latest version, an explicit version stays
readable, `list_transcript_versions` lists both oldest-first (the documented order); counts survive a
re-open (2 transcripts / 5 segments / 3 attempts).

**"No subtitle visible" path (DoD box 4) probed live:** a `no-subtitle`/`not_found` attempt on a part
leaves it in `v_pending_subtitles` with `attempted=1`, `last_attempt_at=110`, the bounded code and
`credential_present`, writes **no** transcript row (`read_transcript` → `None`), and a later successful
acquisition of the same part stores version 1 normally under a new run (two runs, two attempt rows) —
evidence, not a terminal state. The pending order also behaved as locked on this data:
never-attempted parts first (`BV1ORD:p0`, `BV1ORD:p2`, `BV2ORD:p0`), then the oldest attempt
(`BV1ORD:p1` @20) before the newer one (`BV1ORD:p3` @30).

## 6. DoD mapping (`## Acceptance / Done Criteria` — 9 boxes, all still `[ ]`; PM ticks)

| # | Acceptance box | Evidence | Source |
|---|---|---|---|
| 1 | Locked schema + inspection tests + fresh/current/pre-iteration bootstrap | `test_storage_schema.py` (37 tests) green; **QA**: legacy bootstrap 18/18 incl. the skip-not-half-apply proof and the fresh-DB control | L1 + **QA fresh** |
| 2 | Writes transactional, versioned, immutable, content-idempotent | `test_transcript_repository.py` (81) green; **QA**: 13/13 immutability/idempotency probe + UPDATE/DELETE static scan clean | L1 + **QA fresh** |
| 3 | Per-part source kind / language / version / created_at / ms segments; latest by default; explicit version readable | **QA**: `read_transcript` returns `TranscriptRecord` with source kind, language, version, segments; default = latest (v2), explicit v1 readable, both listed oldest-first | **QA fresh** |
| 4 | "No subtitle was visible" = timestamped per-part evidence, not a row, not terminal | **QA**: no-subtitle probe (pending row keeps outcome/time/credential; no transcript row; later success stores v1); L1 E2E tests | **QA fresh** + L1 |
| 5 | Explicit process records; `ingestion_runs` semantics untouched | Range diff changes only the transcript block of `schema.sql` (replaced by a pointer comment); `ingestion_runs`/`v_ingestion_run_stats` DDL unchanged; 275-test metadata subset green | Diff inspection + L1 |
| 6 | Pending view order + last-attempt columns pinned by tests | **QA**: rowid probe + mutation matrix (page_index / bvid / last_attempt_at / whole ORDER BY all fail); last-attempt columns read back live; caveat → QAF-1 | **QA fresh** + L1 |
| 7 | Offline suites green, no metadata-path regressions | **QA**: 1202 passed / 3 skipped (47.71s), focused metadata subset 275 passed, 3 skips = the pre-existing live gates | **QA fresh** |
| 8 | No sidecar file created or read by any new path | L1: `test_transcript_repository.py` opened-file intercept (repaired in the Task-3 audit) + `test_storage_schema.py`; **QA**: zero manifest/JSONL/sidecar references anywhere in `src/bili_asr/storage/` | L1 + **QA grep** |
| 9 | `git diff --check` clean | **QA**: exit 0 over `6ee7c6a..4dcbf5d` | **QA fresh** |

Task-level gates reused: all three SDD task reviews returned **Task quality: Approved**
(`task-1-review.md:85`, `task-2-review.md:125`, `task-3-review.md:258`); the plan's 19 task boxes are `[x]`,
including the two PM-authorized follow-ups (M3 non-monotonic/overlapping body, M2 `run_id` consistency).
QC tri: 2× Approve + 1× Request Changes → fix wave 2 → targeted N=1 re-review **Approve** (`qc3.md:206`).

## 7. Findings

### QAF-1 — `attempted ASC` is unfalsifiable by any test (observation, no action required)

Severity: **note** (not a defect, not a residual). The mutation matrix shows that dropping `attempted ASC`
from the guarded `ORDER BY` leaves the named test green, and a **full-suite run on that mutation is also
green** (`1202 passed, 3 skipped`). I then proved the key cannot change any result: the view defines
`attempted = CASE WHEN latest.video_part_id IS NULL THEN 0 ELSE 1 END` and joins on that same part, so
`attempted = 1 ⟺ last_attempt_at IS NOT NULL`; with SQLite sorting NULLs first,
`ORDER BY attempted ASC, last_attempt_at ASC` is order-equivalent to `ORDER BY last_attempt_at ASC` —
measured on a mixed pending set (`locked == mutated`). The code's own docstring states this
("The key list stays verbatim even though `attempted` is implied by `last_attempt_at IS NULL` … it is the
locked contract the CLI reads, not a query to be shortened"), and QC seat 3's first pass counted
"the other three keys of the locked order" as verified.

Consequence: DoD box 6 ("order … pinned by tests") holds — every key that can affect the sweep is now
falsifiable, and the remaining key is provably redundant by construction, not untested by accident.
The only inaccuracy is the fix-wave-2 report's claim that the pin is falsifiable "for all four keys";
PM may want that wording corrected while consolidating (a one-line note, no code change).

### QAF-2 — `Review Gate Summary` in the plan still reads "pending" (PM bookkeeping)

Severity: **bookkeeping, PM-owned** (explicitly outside my write scope — I may only fill
`## QA Gate Summary`). With the QC tri concluded and the re-review Approve, the `Review Gate Summary`
decision/range/bundle/bundle inputs should be filled at merge/Done time. QC seat 3 already recorded this
and also asked for a fix-wave-2 ledger entry — that entry now exists (`progress.md:155+`), so only the
plan section is outstanding.

### QAF-3 — `docs/metadata-storage.md:51-56` is stale-by-design until the CLI plan lands (carry verified)

Severity: **deferred, correctly owned**. The section still says no transcripts are written yet, which
becomes false on merge. Confirmed live: `20260911-subtitle-cli-cutover.md:229` lists
`bilibili-asr-archive/docs/metadata-storage.md` in its Task-3 file list, and its carry block (QC3-003,
`:297-299`) makes updating that sentence an obligation. No action in this plan.

No critical, warning, or blocking finding was found. No residual is registered by this plan (see §8).

## 8. Residual register check

`projects/_default/residuals.json` holds **exactly one** entry — **R1** (`20260911-subtitle-gateway`,
`severity: low`, `decision: defer`, owner `@project-manager`, target *the next plan whose file list includes
`src/bili_asr/sources/bilibili_api_gateway.py`*). Verified correct: the full range `6ee7c6a..4dcbf5d`
touches **0** files under `src/bili_asr/sources/` (the 8 files are storage + tests + `pyproject.toml`), so
R1 is untouched and must stay open. This plan registers no residual of its own — consistent with
`Findings cleanup: zero-residual` (QC3-001/QC3-002 fixed in branch; QC3-003/QC3-005 carried in the CLI plan;
QC3-004 + QC1/QC2 items recorded in the durable roadmap with owners).

**May the plan proceed to Done with R1 open?** Yes. R1 is a deferred, low-severity gateway import-surface
item with an executable target on a later plan; zero-residual here means "no *new* residue from this plan",
not "R1 closed". R1 remains the iteration's only open register entry and is unaffected by this merge.

## 9. CLI-plan readiness (`20260911-subtitle-cli-cutover`)

Confirmed from the artifacts (all present in its carry block, `:278-302`):

- **F3** (two subtitle methods on the shared `FakeGateway`) — `:191` (Task-1 item) and `:287`;
- **R1's carriage** — `:287-290`: R1 is retargeted to the next plan touching
  `src/bili_asr/sources/bilibili_api_gateway.py` and explicitly stays open past the CLI plan;
- **QC3-002** — `:293-296`, including the note that fix wave 2 additionally makes `__init__` fail fast
  (verified live by this seat);
- **QC3-003** — `:297-299`, naming `docs/metadata-storage.md:51-56` as the sentence Task 3 must update;
- **QC3-005** — `:300-302`: the printed line must carry both the `<command>:` prefix and the archive root,
  with an assertion, because `SchemaContractError` only has a connection;
- plus plan-2 QC1-003 (`:278-286`: argument validation, guard scope, and the two row shapes of
  `list_pending_subtitle_parts` / `list_selected_parts`);
- **`docs/metadata-storage.md` is in its file list** (`:229`, Task 3 Modify, with the docs bullet at `:243`).

Nothing is missing for plan 3 to be dispatched; the item that stays that plan's obligation is landing the
doc + the bounded live smoke before its own Done.

## 10. Verdict

**Approve — recommend merge.** Checkout alignment, diff-package integrity, the full offline suite
(1202/3 at HEAD, no new skips), the shipped-path legacy guarantee, the QC3-001 ordering pin, the
immutability/idempotency contract, the residual position, and the CLI-plan carriage all reproduce.
The single observation (QAF-1) is a wording/bookkeeping nuance with a proof attached and no behavioural
consequence; QAF-2 is PM bookkeeping. I do not mark the plan `Done` — the merge precedes Done and the PM
owns both.

## 11. Limitations and disclosure

- **Network:** none used (storage-only plan; no live command attempted).
- **Git:** read-only throughout — `rev-parse` / `status` / `log` / `diff` / `archive` only; no commit,
  checkout, push, or stash; no `uv sync` or control-venv modification. All mutations for the ordering
  experiment were applied to **`/tmp` trees extracted from `git archive 4dcbf5d`**; the shared checkout's
  `git status --porcelain --untracked-files=all` is empty after the session.
- **Reused, not re-derived:** the three SDD task reviews, the QC tri/consolidated conclusions, the L1
  mutation runs other than the ordering pin, the live-smoke results of the gateway plan, and the QC3-004
  performance characteristic (recorded, still unmeasured — reproduced as O(subtitle attempts) by reading
  the view, no timing taken).
- **Not exercised here:** the CLI surface itself (plan 3; `probe-subs` / `harvest-subs` do not exist yet),
  the audio/ASR reservations (untouched by design), and any operator-visible end-to-end run.
- **Scratch cleanup:** all scratch artefacts were created under `/tmp` only
  (`/tmp/qa-legacy`, `/tmp/qa-immut`, `/tmp/qa-probe-copy`, `/tmp/qa-mutate`, `/tmp/qa-mutate-attempted`,
  `/tmp/qa-compose`, `/tmp/qa_probe.py`, `/tmp/qa-full-suite.log`) and were removed at the end of the
  session; both scratch databases (`/tmp/qa-legacy/archive.db`, `/tmp/qa-immut/*.db`) are gone. The only
  files this seat wrote are this report and the plan's `## QA Gate Summary` line.
