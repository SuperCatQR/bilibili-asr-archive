---
plan_id: 010-dedupe-shared-helpers
project: _default
status: draft
created_at: 2026-10-02
execution_mode: inline
plan_parallelism: serial
---
# Plan 010 — Deduplicate the shared constant/helper clusters

## Status
- **Priority**: P3
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/001-*.md for the hotword two-pass item (land 001 → 010, or together)
- **Category**: tech-debt
- **Confidence**: HIGH
- **Evidence**: six grep-verified clusters (below)
- **Planned at**: commit `ff39fd0`, 2026-10-02

## Problem

The same facts are hand-maintained in 3–4 places each. Drift is invisible until a pair disagrees:

1. **Terminal-status frozenset** — 4 copies:
   `coverage_report.py:20`, `scheduler.py:32`, `coordinator.py:45`, `campaign.py:35` all define
   `frozenset({"archived", "gone"})` under four different names. `manifest.VALID_STATUSES`
   (`manifest.py:26-39`) is the SSOT for status names, but the derived subset is hand-maintained per module.
2. **`utc_now_iso`** — 2 copies + a wrapper:
   `meta_cursor.py:49-50`, `run_ledger.py:79-80` (identical bodies), and `coordinator.py:99-102`
   (`_utc_now_iso` lazy re-export wrapper, 7 call sites). A change to one copy (e.g. second- vs
   microsecond-precision) would silently split timestamps across `attempts.jsonl`, `run-ledger.jsonl`, and
   `meta-cursor.json`.
3. **Dead `cli/meta.py` copies** — `_run_error_codes` / `_format_run_line`:
   byte-identical implementations at `cli/meta.py:148,170` and `cli/_shared.py:431,448`. `meta.py` imports
   the `_shared` versions at its top (`:13,:21`) **and** defines private shadows that are never called — a
   maintainer editing `_shared` would leave the stale `meta.py` copy behind. (`_resolve_sessdata` at
   `cli/meta.py:187` similarly duplicates `config.resolve_sessdata`.)
4. **`_now()` epoch helper** — 2 copies:
   `metadata_ingest.py:61-64` and `subtitle_ingest.py:74-77`. The `subtitle_ingest` copy is injectable as
   `clock: Callable[[], int] = _now` (`:313`); the `metadata_ingest` copy is not — the injectable form is the
   more testable one and should be the single shared helper.
5. **Canonical-stem / artifact-stem** — 3 divergent implementations:
   `quality.py:369-392` (`_canonical_stem`, honours `page_label`), `integrity.py:643-653` (`_canonical_stem`,
   does **not** honour `page_label`), `coordinator.py:969-973` (`artifact_stem_for_entry`, delegates to
   `archive.archive_stem`). A stem-derivation change must be made in three places; the drift is invisible
   until a quality/verify pair disagrees on the same row. **MED confidence — verify the three behaviours
   agree on the same corpus before consolidating** (see STOP).
6. **Hotword two-pass orchestration** — duplicated verbatim:
   `cli/asr.py:203-229` and `coordinator.py:580-603`. Residual **O-R1** registers this as a drift hazard.
   Plan 001 extracts the shared `two_pass_transcribe` helper (with the cache-bust correctness change); this
   plan's item is the **mechanical dedup** — after 001, both call sites call the helper, closing O-R1.

## Approach

Work cluster by cluster; each is a separate, independently verifiable edit. **Do them as separate commits
within this plan** so a regression in one is bisectable.

1. **Terminal statuses**: export `TERMINAL_STATUSES = frozenset({"archived", "gone"})` from `manifest.py`
   (derived from `VALID_STATUSES`); import it in `coverage_report.py`, `scheduler.py`, `coordinator.py`,
   `campaign.py`; delete the four local definitions.
2. **`utc_now_iso`**: define it once (in `run_ledger.py`, the lower-level module) and import it directly in
   `meta_cursor.py` and `coordinator.py`; delete the `_utc_now_iso` wrapper and the `meta_cursor` copy.
3. **Dead `cli/meta.py` copies**: delete `_run_error_codes`, `_format_run_line`, and `_resolve_sessdata`
   from `cli/meta.py`; import `_run_error_codes`/`_format_run_line` from `cli._shared` and call
   `bili_asr.config.resolve_sessdata` at the two sessdata call sites (`cli/meta.py:229,332`).
4. **`_now()`**: move the injectable-clock form to a shared location (import from `subtitle_ingest` into
   `metadata_ingest`, or a tiny `services/_common.py`) and use it everywhere.
5. **Canonical stem**: define one `canonical_stem(row, *, honour_page_label: bool = False)` in
   `page_identity.py` (or `archive.py`) and delegate all three call sites. **Only after** verifying the
   three current behaviours agree on the same corpus (see STOP).
6. **Hotword two-pass**: after plan 001 lands the shared helper, both `cli/asr.py` and `coordinator.py` call
   it — remove the now-dead inline sequence (O-R1's code half).

## Files

- **Modify**: `src/bili_asr/manifest.py`; `src/bili_asr/coverage_report.py`; `src/bili_asr/scheduler.py`;
  `src/bili_asr/coordinator.py`; `src/bili_asr/campaign.py` (cluster 1).
- **Modify**: `src/bili_asr/meta_cursor.py`; `src/bili_asr/run_ledger.py`; `src/bili_asr/coordinator.py`
  (cluster 2).
- **Modify**: `src/bili_asr/cli/meta.py`; `src/bili_asr/config.py` (cluster 3 — config is import-only).
- **Modify**: `src/bili_asr/services/metadata_ingest.py`; `src/bili_asr/services/subtitle_ingest.py`
  (cluster 4).
- **Modify**: `src/bili_asr/quality.py`; `src/bili_asr/integrity.py`; `src/bili_asr/coordinator.py`;
  `src/bili_asr/page_identity.py` or `src/bili_asr/archive.py` (cluster 5).
- **Modify**: `src/bili_asr/cli/asr.py`; `src/bili_asr/coordinator.py` (cluster 6 — after 001).

## Out of scope

- The cache-bust correctness change to the two-pass helper (plan 001) — this plan only removes the
  duplicate inline copy.
- Residual O-R1's register row (PM closes it).
- Any behaviour change beyond dedup: the public signatures and return shapes are preserved.

## Verification gates

Each cluster is a pure refactor — the gates are "same behaviour, one source":

- **Cluster 1 (terminal statuses)**: `python3.12 -m pytest tests/test_manifest.py tests/test_scheduler.py tests/test_campaign.py -q` passes; `rg -n 'frozenset\(\{"archived", "gone"\}\)' src/bili_asr/` → exactly one definition (in `manifest.py`).
- **Cluster 2 (utc_now_iso)**: `python3.12 -m pytest tests/test_run_ledger.py tests/test_meta_cursor.py tests/test_coordinator.py -q` passes; `rg -n 'def utc_now_iso|def _utc_now_iso' src/bili_asr/` → one definition; coordinator imports it.
- **Cluster 3 (dead meta.py copies)**: `python3.12 -m pytest tests/test_metadata_cli.py -q` passes; `rg -n 'def _run_error_codes|def _format_run_line|def _resolve_sessdata' src/bili_asr/cli/meta.py` → no matches.
- **Cluster 4 (_now)**: `python3.12 -m pytest tests/test_metadata_ingest.py tests/test_subtitle_ingest.py -q` passes (or the closest owning test files); one `_now` definition.
- **Cluster 5 (canonical stem)**: `python3.12 -m pytest tests/test_quality.py tests/test_integrity.py -q` passes; `rg -n 'def _canonical_stem|def artifact_stem_for_entry' src/bili_asr/` → the three call sites delegate to one function.
- **Cluster 6 (two-pass)**: after 001, `rg -n 'rebuild_hotwords_from_first_pass' src/bili_asr/cli/asr.py src/bili_asr/coordinator.py` → no inline sequence (only the shared-helper call).

Adjust the exact test-file names to the owning suites if they differ on disk; the gate is "the owning
suites pass + the duplicate is gone", not a specific filename.

## STOP conditions

- **Cluster 5 first**: if the three stem implementations **disagree** on any real corpus row (e.g.
  `quality` honours `page_label` but `integrity` does not, and both are load-bearing for different
  consumers), STOP — report the divergence and which consumer depends on which behaviour; do not pick one
  silently.
- If deleting a "dead" copy in cluster 3 turns out to be reachable (i.e. a test fails), STOP — the copy is
  not dead; report the caller.
- If any cluster's dedup breaks a frozen contract (reason-code order, snapshot determinism, timestamp
  format), STOP and report the contract.

## Done criteria

- [ ] Each cluster's gate above passes (owning suites green + the duplicate removed).
- [ ] No public signature or return shape changed (this is a pure refactor).
- [ ] `git diff --check -- <all touched files>` exits 0.
- [ ] No files outside the Files list are modified.

## Drift check

`git diff --stat ff39fd0..HEAD -- src/bili_asr/` — this plan touches many files; before each cluster's edit,
confirm that cluster's files are unchanged since `ff39fd0`. If a cluster's files changed, re-open the cited
lines and confirm the duplicate is still present before removing it.
