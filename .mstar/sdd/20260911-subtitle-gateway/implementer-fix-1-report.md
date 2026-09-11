# Task 3 fix wave — implementer report (Minors 2, 3, 4)

- Plan: `20260911-subtitle-gateway` · Task 3 (final) · iteration `iter-2026-09-subtitle-transcript-sqlite`
- Round: fix 1 — the three actionable Minors from `review/task-3-review.md`
- Working branch: `feature/20260911-subtitle-gateway` (worktree `.worktrees/20260911-subtitle-gateway`)
- Base: `c3d362c` · Commit: `6002f99` (working branch only, 1 file, +394/−47; no push, `main` and the iteration
  branch untouched) · Scope: **test module only** (`bilibili-asr-archive/tests/test_live_subtitle_smoke.py`)
- Live-run discipline: no `BILI_LIVE_SMOKE` was ever set (`BILI_LIVE_SMOKE is: '<unset>'`), no credential file
  was sourced, no network call was made; every run below is offline.

## Status

**DONE**

## Implemented — per-finding disposition

### Minor 2 — module docstring vs. a listing `not_found` — **fixed by handling it (the brief's preferred option)**

Chosen: record an explicit bounded evidence line and skip, mirroring the body path.

`tests/test_live_subtitle_smoke.py:333-406` (`_probe_one_part`, the extracted live flow):
a second `except` clause on the listing call (`:351-371`) prints
`live subtitle probe evidence: part_source=<label> stage=track-listing track_count=not_found` and skips with the
bounded reason. Module docstring `:42-48` gains the matching bounded-outcome bullet, and `:31-33`
("a sample that upstream has since removed is visible rather than silent") is now true as written.

Why this option rather than "docstring says it fails loudly by design":

1. The listing's `GatewayNotFound` is **not only a deleted video**. The adapter passes
   `_SUBTITLE_NOT_FOUND_API_CODES = {-404, -62002, -101}` for the subtitle listing
   (`bilibili_api_gateway.py:727`, `:722-728`), and the L2 review's own re-derivation records `-101` as
   "the credential in effect saw nothing for this part", which the spec says the caller records as
   `no-subtitle`. So under the old code an **anonymous** probe (`-101`, no SESSDATA) could die with an
   uncaught exception instead of producing the documented "saw nothing under this credential" record —
   a real robustness gap, not just stale documentation.
2. It keeps the probe honest: the run still does **not** read green (pytest reports `skipped`), and the
   line names the bounded code, the stage, and the part. A traceback carries no bounded evidence at all.
3. It mirrors the already-accepted body-path treatment (`segments=not_found` → record + skip), so the two
   halves of the same document boundary behave the same way, and it is the option the brief marks preferred.

Disclosed cost: a stale sample (or a part the credential cannot see) now **skips** instead of failing
loudly. That is the one intended strictness change in this wave; the skip reason is explicit that no
listing evidence was obtained and that the run must not read as green.

### Minor 3 — newest-part selection is not status/format aware — **fixed**

`tests/test_live_subtitle_smoke.py:226`: the query is now
`SELECT bvid, cid FROM video_parts WHERE cid > 0 AND processing_status != 'gone' ORDER BY video_part_id DESC LIMIT 1`
(`gone` is the shipped part status, `storage/schema.sql:28-30`, `storage/models.py:15`).
`tests/test_live_subtitle_smoke.py:134` adds `BVID_PATTERN = re.compile(r"^BV[a-zA-Z0-9]{10}$")` (the shape the
adapter enforces, `bilibili_api_gateway.py:68`, `:157`) and `:236-237` rejects a selected row whose `bvid` does not
match, so the row answers `None` and the probe takes its documented sample fallback instead of the adapter's
`ValueError`. Both are documented in the function docstring (`:200-216`).

`BVID_PATTERN` is a **mirror**, not an import: importing the adapter's constant would pull the pinned
distribution into this module's import (module-scope `bilibili_api` import in the adapter), and the probe must
stay importable — and its rehearsals runnable — without it. Stated in the comment at `:129-133`.

### Minor 4 — no offline rehearsals for the unguarded branches — **fixed (plus the one adjacent branch)**

The live flow's two boundary calls moved into `_probe_one_part` (`:333-407`) **unchanged** — that extraction is
what makes the branches drivable offline; the live test (`:409-442`) keeps the gate, the version guard, the
credential/proxy resolution, the part resolution and both prints, and then delegates.

New offline rehearsals (`_ScriptedGateway` double, `:722-760`; no I/O, no network):

| Branch | Rehearsal |
|---|---|
| `_load_gateway` ImportError guard | `test_unimportable_pinned_module_fails_loudly` (`:648-667`) — adapter module replaced by `None` on `sys.modules` |
| listing risk-control refusal | `test_probe_records_each_bounded_blocker_and_never_reads_green[listing-risk-control-refusal]` (`:787-858`) |
| listing `not_found` (Minor 2) | `…[listing-not-found]` (same test) |
| body risk-control refusal | `…[body-risk-control-refusal]` |
| body `not_found` | `…[body-not-found]` |
| empty listing → early return, no body call | `test_probe_records_an_empty_listing_and_stops_before_the_body` (`:774-784`) |
| visible-track evidence chain, no label leak | `test_probe_records_the_whole_evidence_chain_without_leaking_a_label` (`:861-882`) |

The empty-listing rehearsal is **one branch beyond** the review's list, added because the docstring sentence
this wave writes ("every branch of that ladder is rehearsed offline") must be exactly true; the early return
(`:375-382`) was the only remaining unrehearsed branch. The blocker rehearsal also pins the call list, so a
listing that never answered is never followed by a body fetch — the M4 discipline applied to the probe itself.

Supporting changes in the same module: `_seed_archive` (`:455-477`) gained two defaulted keywords
(`processing_status`, `extra_parts`); existing call sites and their assertions are untouched. Two new Minor-3
rehearsals: `test_probe_part_selection_skips_a_part_the_archive_marked_gone` (`:556-600`) and
`test_probe_part_selection_ignores_a_row_that_is_not_a_bv_id` (`:603-633`).

## Tests

All commands run from the worktree package dir with
`/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python`; `BILI_LIVE_SMOKE` unset.

**Focused (the brief's command, verbatim):**

```
$ /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest \
    tests/test_live_subtitle_smoke.py tests/test_bilibili_api_gateway.py -v
======================== 324 passed, 2 skipped in 1.26s ========================
```

(Review baseline: `315 passed, 2 skipped` → **+9 passed**, exactly the 9 new cases: 2 Minor-3 + 1 import
guard + 1 empty listing + 4 blockers + 1 evidence chain.)

**Probe module alone:**

```
$ … -m pytest tests/test_live_subtitle_smoke.py -v -rs
======================== 16 passed, 1 skipped in 0.32s =========================
SKIPPED [1] tests/test_live_subtitle_smoke.py:422: live subtitle probe is opt-in: set BILI_LIVE_SMOKE=1 to request it
17 tests collected
```

The live test is still collected, its gate is still the test's first statement, the skip reason is verbatim
unchanged, and it is the only test in the module that can reach the network.

**Full offline suite (before commit):**

```
$ … -m pytest -q
======================== 1091 passed, 3 skipped in 45.97s ======================
```

Baseline `1082 passed, 3 skipped` → +9 passed, skip count unchanged.

### Non-vacuity (revert the guard → the pinned rehearsal fails; restore → green)

Driver: `/tmp/mutate_probe.py` (outside the repo). Each mutation is applied to the pristine module, a
bytecode-cache purge runs first, the targeted rehearsal runs, the file is restored, and a SHA-256 check
confirms the worktree is byte-identical afterwards.

```
M1 Minor 2: drop the listing not_found branch (re-raise)      1 failed, 3 passed  FAILED …[listing-not-found]
M2 Minor 3: drop `AND processing_status != 'gone'`            1 failed           FAILED test_probe_part_selection_skips_a_part_the_archive_marked_gone
M3 Minor 3: drop the bvid shape check                         1 failed           FAILED test_probe_part_selection_ignores_a_row_that_is_not_a_bv_id
M4 Minor 4: `except ImportError` → `except ZeroDivisionError`  1 failed           FAILED test_unimportable_pinned_module_fails_loudly
M5 Minor 4: risk-control skip → print (no skip)               2 failed, 2 passed  FAILED …[listing-risk-control-refusal], …[body-risk-control-refusal]
M6 Minor 4: body not_found skip → print (no skip)             1 failed, 3 passed  FAILED …[body-not-found]
M7a empty listing: change the no-track evidence wording       1 failed           FAILED test_probe_records_an_empty_listing_and_stops_before_the_body
M7b empty listing: drop the early return                      1 failed           FAILED test_probe_records_an_empty_listing_and_stops_before_the_body
M8 success path: print the track label in the body line       1 failed           FAILED test_probe_records_the_whole_evidence_chain_without_leaking_a_label
ALL MUTATIONS CAUGHT — file restored byte-identical after every run
```

Two honest notes on that evidence:

- The **first** driver run was discarded: M5 and M6 mutants happen to have the same file size and landed in the
  same mtime second, so the M6 process executed M5's cached bytecode and reported M5's failure ids (both runs
  showed "2 failed"). Re-running with a cache purge before every case and `PYTHONDONTWRITEBYTECODE=1` gives the
  table above, and M6's failure id was additionally confirmed by a manual, single-mutation run.
- M7b fails via `IndexError` at `tracks[0]` (the body fetch the early return prevents), not via a clean assertion
  — a mutation artefact, not a gap: M7a shows the branch's own evidence line is pinned too.

## Files changed

- `bilibili-asr-archive/tests/test_live_subtitle_smoke.py` — +394/−47 (882 lines; `git diff --check` clean,
  no line over 88 columns). **No other file in the repo was touched** (git status: one modified file).
- This report (`.mstar/sdd/20260911-subtitle-gateway/implementer-fix-1-report.md`) — the only harness file written.

Nothing else was changed: no adapter, no plan/snapshot/compass/spec/iteration, no other test module.

## Disclosures

**Changed assertions — every one.**

- **0 assertions removed or loosened.** Verified two ways: (a) the moved live-flow block was diffed old-vs-new
  (old inline body in `c3d362c` vs. the new `_probe_one_part`) and differs **only** by the added
  `except GatewayNotFound` clause; (b) `git diff` shows the only removed assertion-shaped lines are that moved
  code re-added verbatim (`assert _pinned_package_version() == PINNED_PACKAGE_VERSION`, two `print(`, one
  `pytest.skip(`).
- **21 added assertion lines**, of which 20 are new assertions and 1 is the moved-verbatim
  `assert _pinned_package_version() == PINNED_PACKAGE_VERSION`: 4 in the Minor-3 gone test, 2 in the Minor-3
  shape test, 3 in the import-guard test, 3 in the empty-listing test, 3 in the blocker test, 5 in the
  evidence-chain test (one of them the multi-line body-evidence assert). No existing assertion was edited.
- **One behaviour change, authorized by the brief (Minor 2):** the listing's `GatewayNotFound` no longer
  propagates; it is recorded and skipped. Strictness of the *content* of what the probe asserts/prints is
  unchanged — same renders (`_track_evidence`, `_assert_bounded_segment_facts`), same monotonic-timeline
  assertion, same four skips, same bounded output discipline.
- No live assertion was made laxer: the live test still asserts the pinned version, still prints
  `sessdata=<presence>` / `proxy=present|absent`, and still fails loudly on `transport_error`,
  `response_error`, and `shape_error`.

**Boundary discipline.** The new printed material is `part_source` (one of two fixed labels), the stage, the
bounded code, and the existing refusal code — no URL, no body, no credential, no label body. The evidence-chain
rehearsal asserts `assert_leaks_no_markers` over everything `_probe_one_part` prints, with both sentinels planted
inside a track label.

**Reviewed but deliberately not changed.**

- Minor 1 (plan Evidence Index) and Minor 5 / R1 (`user.User` docstring wording) — out of this wave, as the
  brief states; the adapter is untouched.
- Minor 6 (monotonic-timeline strictness) — disclosed design choice, left as is.
- The pre-existing body-path line `stage=subtitle-body segments=not_found` (`:391-400`) carries no `part_source`
  while the new listing-side line does. I left it byte-identical to the delivered/recorded format rather than
  normalizing it: the live test prints the probed part (`part: source=… bvid=… cid=…`) before both lines, so the
  record is complete either way. Flagged as a cosmetic asymmetry, not a finding.

## Self-review notes

1. **Probe honesty.** Every new branch either records bounded facts or fails loudly; no new path can make the
   probe read green without evidence, and the `track_count=0` path still prints the credential presence.
2. **No live surface added.** The double is the only new collaborator and it performs no I/O; the live test's
   call sites are unchanged (`asyncio.run(gateway.<method>(...))`).
3. **Importability.** The module still imports neither the adapter nor the pinned distribution at module scope;
   `_load_gateway` remains the only place the adapter is imported, and its failure mode is now rehearsed.
4. **Mirror risk.** `BVID_PATTERN` duplicates the adapter's `_BVID_PATTERN` by design; if the adapter's pattern
   ever changes, the probe's check must follow. The duplication is stated at the constant with the reason.
5. **Scope.** One test module, one commit, no push, no worktree mutation outside it; the report is the only
   harness artifact written. Nothing here re-tests or re-implements adapter behaviour — those offline assertions
   are untouched and still green.
6. **Residual risk (unchanged by this wave).** The `archive-db` branch still has never executed live (no archive
   DB on this host), and the `-101` reading of the listing's `not_found` is derived from the adapter's mapping
   and the spec, not observed live.
