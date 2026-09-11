# Implementer Fix Wave 1 — `20260911-subtitle-cli-cutover`

- Plan: `20260911-subtitle-cli-cutover` · Iteration: `iter-2026-09-subtitle-transcript-sqlite`
- Role: `@fullstack-dev` (leaf; `Delegation: forbidden` — no subagents used)
- Working branch: `feature/20260911-subtitle-cli-cutover` · HEAD before this wave: `8373817`
- **Commit of this wave: `7e57eb6`** — `fix(subs): answer an unstorable --bvid as unknown and bound every per-part anomaly` (`7e57eb62d35d33b8effee6b21bac8b0b8f4d70c1`)
- Worktree: `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-cli-cutover` (package root `bilibili-asr-archive/`); worktree clean after the commit
- Input: `{SDD_DIR}/review/qc-consolidated.md` (dedup of `qc1.md` / `qc2.md` / `qc3.md`)
- No push; the integration branch and `main` were never touched. **No live network run**: `BILI_LIVE_SMOKE` was never set and no credential was read (presence-only helpers were not invoked outside the seam).

## Status

**Complete — all 12 wave items landed; the inherited WIP was audited and one regression it introduced was fixed before completing the missing items.**

| # | Item | Disposition |
|---|------|-------------|
| 1 | F-001 (Warning) blank/control-char `--bvid` → `unknown --bvid <value>`, exit 1 | verified in the inherited WIP, kept (non-vacuity proven) |
| 2 | F-003 DTO rejects `\x00`/`\r`/`\n` in `lan_doc` | verified, kept — **but its shared-`_text` form regressed caption body text; fixed** |
| 3 | QC2-002 storage-ceiling `ValueError` → bounded per-part `failed` | verified in the WIP; one inaccurate comment corrected |
| 4 | QC2-003 probe opens its connection read-only | verified in the WIP, kept |
| 5 | QC2-009 (1st half) assert `with_tracks`/`stored`/`run_id` | **was NOT in the WIP — implemented here** |
| 6 | QC2-001 failed part before a successful one | verified in the WIP (`test_partial_failure_...` re-scripted), kept |
| 7 | QC2-009/Q3-03 (2nd half) forgotten credential must be loud | **implemented here** |
| 8 | QC2-004/Q3-02 probe stdout sentinel scan + docs scope | **implemented here** |
| 9 | Q3-01 prose fix + cross-family pinning test | **implemented here** |
| 10 | Q3-04 docs live line carries `run_id=` | **implemented here** |
| 11 | Q3-05 lock-before-DB-check, rebuild bound, README ⚠️6 pointer | **implemented here** |
| 12 | F-002 rebuild line shown as one line + stated to go to stderr | **implemented here** |

## What I fixed in the inherited WIP (audit first, not trust)

### A. Regression introduced by the F-003 change: caption BODY text was rejected

`src/bili_asr/sources/models.py::_text` was hardened for **every** DTO text field, including
`SubtitleSegment.text`. The storage contract deliberately splits those rules: `storage.models._text`
rejects control characters, `storage.models._caption_text` **keeps** them ("a stored caption is verbatim
apart from trimming"). Proof of the regression, run before the fix:

```
$ .venv/bin/python -c "... SubtitleSegment(start_ms=0, end_ms=1500, text='第一行\n第二行') ..."
DTO REJECTS multi-line caption text: ValueError text contains invalid control characters
storage accepts multi-line caption text: '第一行\n第二行'
```

Reachability matters: `_normalize_subtitle_segment` (`bilibili_api_gateway.py:438-458`) is **not** wrapped
in `except (TypeError, ValueError)` (its siblings at `:210`, `:243`, `:312` are), `ValueError` is not a
`GatewayError`, so the escape path was `fetch_subtitle_segments` → `_acquire_part` (catches only
`GatewayError`) → `harvest`'s `except BaseException` → `harvest-subs: unexpected error`, exit 2 — the exact
failure class this wave removes, on ordinary upstream data (a two-line cue).

Fix: `sources/models.py` now mirrors the storage split — `_caption_text` (`:46-60`) for
`SubtitleSegment.text` (`:176`), strict `_text` (`:25-43`) for the operator-facing fields. Regression test:
`tests/test_bilibili_api_gateway.py::test_caption_text_keeps_interior_control_characters_as_one_row`
(`:2730`), driven through the real adapter over the package seam.

### B. Inaccurate claim in the QC2-002 comment

The WIP comment said the storage boundary rejects the body "having rolled its own transaction back". The
ceiling is enforced in `_canonical_segments` (`storage/database.py:1228-1240`), which runs **before**
`with _transaction(...)` at `:892` — nothing is written, so nothing is rolled back. Corrected the comment
(`services/subtitle_ingest.py:527-536`); the behaviour and its docstring claim are unchanged and correct.

## Per-item disposition, with anchors and proof

### 1. F-001 — blank/whitespace/control-character `--bvid` (verified, kept)

- `cli.py:665-679` `_selector_cannot_name_a_part` (decided on the argument, before the database is opened),
  called at `:850` (probe, before `_open_subtitle_connection`) and `:945` (harvest).
- Usage table gained the three cases at `tests/test_subtitle_cli.py:228-238`; dedicated test at `:258`
  (7 parametrized selectors, both commands, exact stderr equality, `out == ""`, no run/attempt row,
  probe leaves no file); priority-over-the-missing-database-guard case at `:310`.
- **Runtime reproduction** (offline, temp root outside both checkouts):
  `probe-subs --bvid "" --archive-root /tmp/.../rt` → stderr `probe-subs: unknown --bvid `, **exit 1**.
- Mutation `item-1-F-001-blank-bvid` (`return not bvid.strip() or ...` → `return False`): **7 failed, 15 passed**.

### 2. F-003 — DTO rejects control characters in `lan_doc` (verified, kept; scope corrected)

- `sources/models.py:39-42` (strict `_text`, used by `SubtitleTrack.language`/`label`/`track_id`,
  `VideoSummary.title`, `VideoPart.title`); gateway construction sites already wrap it into
  `GatewayShapeError` (`bilibili_api_gateway.py:179-190` for `VideoSummary`, `:236-244` for `VideoPart`,
  `:305-313` for `SubtitleTrack`).
- Tests: `test_subtitle_track_rejects_invalid_fields` gained 9 control-character params (label, language,
  `track_id`); `test_get_subtitle_tracks_rejects_an_unreadable_inventory` gained 4 interior-character
  cases; `test_get_user_video_page_rejects_a_title_with_control_characters` (`:540`).
- Caption body text is exempted — see "What I fixed" A.
- Mutation `item-2-F-003-control-chars`: **13 failed, 32 passed**.

### 3. QC2-002 — storage-ceiling rejection stays one part's bounded outcome (verified, kept)

- `services/subtitle_ingest.py:509-537`: the repository call is wrapped, `ValueError` →
  `_record_failed_part(..., GatewayShapeError(), ...)` → attempt `failed`/`shape_error`, run continues.
- Test `tests/test_subtitle_cli.py:1128` scripts `end_ms = MAX_TIMELINE_MS + 1` on part 0 and a good body on
  part 1: exact 4-line stdout (`failed shape_error` then `stored`), attempt rows
  `[("failed","shape_error",False),("stored",None,True)]`, run `partial`, refused part stores nothing and
  stays pending.
- Mutation `item-3-QC2-002-storage-valueerror` (`except ValueError` → `except ZeroDivisionError`): **1 failed**.

### 4. QC2-003 — the probe's connection is structurally read-only (verified, kept)

- `cli.py:542-583` `_open_read_only_connection` (`sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)`,
  `row_factory`, `PRAGMA foreign_keys=ON`, a first `PRAGMA schema_version` read inside the bounded handler);
  `cli.py:858` passes `read_only=True` for `probe-subs` only. `open_database`'s schema scripts + commit are
  therefore off the probe path entirely.
- Test `tests/test_subtitle_cli.py:1266`: records `sqlite3.connect`, asserts exactly one connection,
  `kwargs == {"uri": True}` and the exact `?mode=ro` URI; then uses that URI directly and asserts `CREATE
  TABLE`, `DELETE` and `INSERT` all raise `sqlite3.OperationalError`; then asserts one file and four empty
  evidence tables.
- Mutation `item-4-QC2-003-read-only-probe`: **1 failed**.

### 5. QC2-009 (1st half) — the live line's fields are asserted, not just printed (implemented)

- `tests/test_live_subtitle_cli_smoke.py`:
  - `_read_probe_output` (`:384`, ties at `:430-455`) ties `with_tracks` / `without_tracks` / `failed` to the
    part line and to each other;
  - `_read_harvest_output` (`:461`, ties at `:499-521`) ties the four outcome counts to the part line's
    outcome and to `attempted`;
  - `_assert_stored_rows` (`:587`, `run_id` tie at `:648-650`) and `_assert_no_transcript_rows` (`:689`,
    `run_id` tie at `:735-737`) take the printed `run_id` and assert it against the persisted
    `acquisition_runs.run_id`;
  - the live body (`:913`, `:933`) passes `harvest.run_id` and asserts `(stored, unchanged)` against the
    outcome.
- Because the helpers are the live body's own readers, the ties are exercised by the offline rehearsals, so
  they cannot rot unseen. Mutations: `item-5a-run-id-tie` (printed `run_id` → `tampered`): **2 failed**;
  `item-5b-with-tracks-tie` (probe summary `with_tracks` → `0`): **1 failed**.

### 6. QC2-001 — a failed part before a successful one (verified, kept)

- `tests/test_subtitle_cli.py:1063`: `listing_failures={101: ...}`, `segments={102: BODY}`; asserts the
  exact 4-line stdout in order, `gateway.listing_cids == [101, 102]`, `gateway.body_cids == [102]`, the
  stored transcript is p1's, attempts `[("failed","rate_limited",False),("stored",None,True)]` in part order,
  run `partial`, exit 0.

### 7. QC2-009 / Q3-03 (2nd half) — a forgotten credential is loud (implemented)

- `tests/test_live_subtitle_cli_smoke.py:236-258`: `_require_live_credential()` fails loudly (never skips)
  when no credential resolves, and `_live_preconditions()` (`:260-275`) applies the three preconditions **in order** —
  opt-in (`pytest.skip`), pinned distribution (`pytest.fail`), credential (`pytest.fail`). The live body now
  calls `_live_preconditions()` (`:846`) instead of inlining them.
- Offline rehearsal `test_the_live_preconditions_gate_in_the_documented_order` (`:1052`): not opted in →
  `skip`; opted in with `BILI_SESSDATA` unset → `fail` naming the variable and "benign skip"; blank value →
  `fail`; resolvable value → returns cleanly. So the default run still skips without a credential, and the
  gate order itself is pinned offline rather than resting on a live run.
- Docs: `docs/metadata-storage.md:519-527` ("Opt-in requires a resolvable credential … A default (not
  opted-in) pytest run still skips, credential or not"), README `:704-710`.
- Mutation `item-7-live-credential-gate` (drop the credential step from `_live_preconditions`): **1 failed**.

### 8. QC2-004 / Q3-02 — the probe's stdout is scanned, and the docs sentence is scoped (implemented)

- Live smoke: `assert_leaks_no_markers(probe_out + probe_err, context="live probe output")` (`:871`).
- Offline rehearsal `test_the_probe_surface_scan_catches_a_sentinel_arriving_as_a_track_label` (`:1139`):
  scripts a label carrying `SIGNED_SUBTITLE_URL_MARKER` through the seam, asserts the real CLI printed it as
  metadata on the documented track line, asserts the scan **fires** (`pytest.raises(AssertionError)`), and
  asserts the scan is silent once the sentinel is replaced — so the probe-surface scan is neither vacuous nor
  a formality. Mutation `item-8-neutered-scan-helper` (neuter the scanner): **1 failed**.
- Docs `docs/metadata-storage.md:153-159`: the blanket "No output carries … upstream message text" is now
  scoped to "The error and evidence paths", and names the one upstream metadata value that *is* printed —
  the `lan_doc` label, trimmed and `shape_error`-rejected when it carries a control character.
  (The separate No-JSONL sentence at `:296-298` lists credentials/signed URLs/bodies/exception text only and
  stays accurate: the adapter never reads `subtitle_url` into a DTO.)

### 9. Q3-01 — the family-blind CC-before-AI term: prose fixed, corner pinned (implemented)

- Prose: `docs/metadata-storage.md:210-219` and `README.md:629-636` now state that the CC-before-AI term is
  deliberately family-blind — it decides across two distinct non-default families, and upstream order
  settles only same-family, same-kind ties. The code (`_family_rank` + the `(family_rank, is_ai,
  upstream_index)` key) is the locked spec's and was **not** changed.
- Pinning test `tests/test_subtitle_cli.py:506`: `(ai-ja @0, fr-CC @1) → fr-CC` in both upstream orders
  (family rank and upstream index each disagree with the outcome on their own), plus `fr` vs `fr-CA`
  same-family/same-kind ordering.

### 10. Q3-04 — the quoted live line carries `run_id=` (implemented)

- `docs/metadata-storage.md:548` now reads `… harvest_exit=0 run_id=1de9b7cb7cd141bfa7114112212188db
  attempted=1 stored=1 …`, matching `tests/test_live_subtitle_cli_smoke.py:946`'s print and the recorded
  implementer line byte for byte.

### 11. Q3-05 — failure/rebuild-path documentation (implemented)

- (a) `docs/metadata-storage.md:195-200` and `README.md:673-679`: the writer lock is taken by the dispatcher
  **before** the handler's database check, so a failed or mistyped harvest still creates
  `<root>/coordinator/` and leaves `archive-writer.lock` there while exiting 1.
  **Runtime check**: `harvest-subs --limit-parts 1 --archive-root /tmp/.../rt/absent` → exit 1 with the
  missing-database line; the walked root contains exactly `coordinator/archive-writer.lock`.
- (b) `docs/metadata-storage.md:264-271` and `README.md:651-661`: the rebuild's bare `fetch-meta` stops at
  the implicit `DEFAULT_PAGE_LIMIT = 10`, so a corpus collected beyond page 10 needs `--limit-pages <n>` or
  repeated `--resume` runs.
- (c) `README.md:102-110`: the Workflow block now opens with a ⚠️ pointer that the `probe-subs` /
  `harvest-subs` pair writes to `archive.db` and feeds nothing below it (`download-audio --missing-subs`
  gains no entries; `asr --pending` does not see the stored transcripts), linked to the boundary bullet.
- (d) `specs/subtitle-cli-contract.md:304-306`'s now-false sentence stays a **spec errata at iteration
  close**: `qc-consolidated.md` records it as PM-dispositioned with no fix round, and the spec is outside this
  wave's file list.

### 12. F-002 — the rebuild line is one line, on stderr (implemented)

- `docs/metadata-storage.md:255-262`: the message is shown as a **single** line (<command>: archive database
  predates the transcript schema; rebuild it (delete <archive-root>/archive.db and re-run fetch-meta)) and the
  text states it goes to **stderr** while the part/summary output is stdout, with nothing on stdout on that
  path; the sentence "It is one line; the wrap below is the page's, not the command's" prevents a repeat of
  the confusion. The README bullet (`:653-658`) says "one line on stderr" for the same reason.

## Tests — commands and outputs

TDD triple: test files `tests/test_subtitle_cli.py`, `tests/test_bilibili_api_gateway.py`,
`tests/test_live_subtitle_cli_smoke.py` (plus `tests/test_subtitle_e2e.py` in the focused command);
interpreter `/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python` (absolute: a linked
worktree has no `.venv` of its own).

Focused (assignment command), at the committed revision:

```
$ cd /root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-cli-cutover/bilibili-asr-archive
$ /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest \
    tests/test_subtitle_cli.py tests/test_subtitle_e2e.py tests/test_live_subtitle_cli_smoke.py \
    tests/test_bilibili_api_gateway.py -q
438 passed, 2 skipped in 4.10s
```

The 2 skips are the two opt-in live smokes (no network, gate decided first). Before this wave's additions the
same command reported `434 passed, 2 skipped`; the inherited WIP's own two-module state was
`406 passed, 1 skipped`.

Full offline suite, at the committed revision:

```
$ /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest -q
1311 passed, 4 skipped in 48.96s
```

Baseline `1279 passed, 4 skipped` → `1311 passed, 4 skipped`: **+32 = 28 cases from the inherited WIP's own
new tests + 4 added here** (caption-text regression, cross-family preference corner, live preconditions gate,
probe-surface sentinel scan). The arithmetic reconciles exactly, so no case was lost or silently skipped.

Targeted evidence:

```
$ .venv/bin/python -m pytest tests/test_live_subtitle_cli_smoke.py -q
20 passed, 1 skipped in 0.97s          # 1 skipped = the opt-in live smoke
$ .venv/bin/python -m pytest tests/test_bilibili_api_gateway.py -q
327 passed, 1 skipped in 1.23s
```

Runtime (offline) reproduction of the F-001 acceptance clause and the Q3-05(a) clause:

```
$ PYTHONPATH=src .venv/bin/python -c "from bili_asr.cli import main; main(['probe-subs','--bvid','','--archive-root','/tmp/.../rt'])"
probe-subs: unknown --bvid            # stderr, exit 1
$ PYTHONPATH=src .venv/bin/python -c "... main(['harvest-subs','--limit-parts','1','--archive-root','/tmp/.../rt/absent'])"
harvest-subs: no archive database at /tmp/.../rt/absent; run fetch-meta to create it   # exit 1
files under the mistyped root: ['/tmp/.../rt/absent/coordinator/archive-writer.lock']
```

### Non-vacuity (mutation) evidence — 9 cases, all RED, all restored byte-identically

Harness: `/tmp/mstar-fix1-scratch/mutations.py` (scratch **outside** both checkouts, absolute paths only).
Each case reverts one shipped guard in the working tree, runs the named test(s), restores from a backup taken
outside the checkouts, and re-hashes every touched file:

```
caption-text-regression: RED (as expected) :: 1 failed in 0.50s
item-1-F-001-blank-bvid: RED (as expected) :: 7 failed, 15 passed in 1.01s
item-2-F-003-control-chars: RED (as expected) :: 13 failed, 32 passed in 0.92s
item-3-QC2-002-storage-valueerror: RED (as expected) :: 1 failed in 0.49s
item-4-QC2-003-read-only-probe: RED (as expected) :: 1 failed in 0.47s
item-5a-run-id-tie: RED (as expected) :: 2 failed in 0.59s
item-5b-with-tracks-tie: RED (as expected) :: 1 failed in 0.48s
item-7-live-credential-gate: RED (as expected) :: 1 failed in 0.18s
item-8-neutered-scan-helper: RED (as expected) :: 1 failed in 0.51s
restored: True
cases: 9, problems: 0
```

Anchors: `caption-text-regression` = `_caption_text(self.text, ...)` → `_text`; `item-1` =
`_selector_cannot_name_a_part` → `return False`; `item-2` = the control-character branch removed;
`item-3` = `except ValueError` → `except ZeroDivisionError`; `item-4` = `read_only=True` → `False`;
`item-5a` = printed `run_id` → `tampered`; `item-5b` = probe summary `with_tracks` → `0`; `item-7` = the
credential step dropped from `_live_preconditions`; `item-8` = `assert_leaks_no_markers` neutered.
Restore was verified by SHA-256 per file and by `git status` (clean) after the harness finished; a green
focused rerun followed.

### No-vacuity limits, stated honestly

- The live test **body** is not executed offline (the rehearsals drive its helpers, not the function), so the
  live-only lines (the two `main()` calls against upstream) cannot be mutation-proven here. Everything the
  body derives from a printed value is now asserted inside helpers the rehearsals drive, which is what items
  5/7 moved.
- No live network run was performed in this wave: `BILI_LIVE_SMOKE` was never set and no credential was read.
  The recorded live line at `docs/metadata-storage.md:544-555` is still the operator's evidence from
  `d5c0f9e`, re-quoted (now complete with `run_id=`); the QC hand-off item "re-take the bounded live smoke"
  remains QA's.

## Files changed (commit `7e57eb6`, 9 files, +899/−92)

| File | What |
|------|------|
| `src/bili_asr/cli.py` | `_archive_database_exists` extraction; `_open_read_only_connection` + `read_only=True` for the probe; `_selector_cannot_name_a_part` and its two call sites (inherited WIP, audited) |
| `src/bili_asr/services/subtitle_ingest.py` | per-part `ValueError` → bounded `failed`/`shape_error` (inherited WIP); comment corrected to the real (pre-transaction) enforcement point |
| `src/bili_asr/sources/models.py` | strict `_text` (F-003, inherited WIP) **plus the new `_caption_text` mirror** so caption body text is not regressed |
| `src/bili_asr/sources/bilibili_api_gateway.py` | `VideoSummary` construction wrapped into bounded `GatewayShapeError` (inherited WIP, audited) |
| `tests/test_subtitle_cli.py` | unstorable-`--bvid` tests, failed-before-success ordering, storage-ceiling case, read-only probe case, cross-family preference pin, usage-table cases (mostly inherited WIP) |
| `tests/test_bilibili_api_gateway.py` | control-character DTO/label cases (inherited WIP) **plus the caption-text regression test** |
| `tests/test_live_subtitle_cli_smoke.py` | evidence-field ties, `run_id`↔row ties, `_require_live_credential`/`_live_preconditions`, probe-output scan + its firing rehearsal |
| `docs/metadata-storage.md` | items 8, 9, 10, 11(a)(b), 12 |
| `README.md` | items 9, 11(a)(b)(c), 7 |

## Mutation hygiene confirmation

- All work happened in the feature worktree
  `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-cli-cutover`; the commit is on
  `feature/20260911-subtitle-cli-cutover` only. No push, no checkout switch, no branch creation.
- The **only** harness file written is this report
  (`{SDD_DIR}/implementer-fix-1-report.md`). No plan / snapshot / status / spec / compass / residual file was
  edited. The control checkout's `git status` shows three modified harness files
  (`plans/20260911-subtitle-cli-cutover.md`, `workflows/.../snapshot.json`,
  `iterations/.../specs/subtitle-cli-contract.md`) whose mtimes are 16:20–17:33 — **PM bookkeeping from
  before this session** (this wave's first tool call was at ~18:05); I did not touch them.
- Scratch (`mutations.py`, backups, logs, runtime roots) lives in `/tmp/mstar-fix1-scratch/`, outside both
  checkouts. Mutation runs touched working-tree files only, inside the feature worktree, and every touched
  file was restored byte-identically (SHA-256 checked; `git status` clean afterwards).
- `git diff --check` was clean before the commit (`git diff` is now empty: the tree is committed).
- Credentials: presence-only helpers only (`resolve_sessdata`/`redact_sessdata` through the smoke's own
  helpers); `BILI_LIVE_SMOKE` never set; no `.env` sourced; no value read, printed, or persisted.

## Residuals / follow-ups for the PM (not implemented here, by design)

- `QC2-005` (`--language` not persisted on the run row) and `Q3-06` (owner/trigger for the legacy-retirement
  deferral and nit M2) are PM-owned plan/roadmap edits, per `qc-consolidated.md`.
- The `specs/subtitle-cli-contract.md:304-306` errata line at iteration close (item 11(d)).
- The QA gate hand-off still owns: re-taking the bounded live smoke with `sessdata=present` required, and
  re-verifying F-001 at runtime against the QA checkout (done here offline as well).
