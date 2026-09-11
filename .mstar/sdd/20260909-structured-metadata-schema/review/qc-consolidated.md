# QC Consolidated — 20260909-structured-metadata-schema

- Iteration: `iter-2026-09-bilibili-api-sqlite` · Plan: `20260909-structured-metadata-schema` (SDD, Batch 1)
- Review range / Diff basis: `c98f1405bded9bfd4a322c2226de7d85e4939e6e..ff81140411e9e04756055657569c39a0a0c5c2d4`
- Working branch (verified by all seats): `feature/20260909-structured-metadata-schema`, HEAD `ff81140`, worktree clean
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260909-structured-metadata-schema`
- Seats: `qc-specialist` (qc1.md), `qc-specialist-2` (qc2.md), `qc-specialist-3` (qc3.md) — initial tri wave, N=3, same assignment scope
- Findings cleanup: `zero-residual`

## Seat verdicts (initial wave)

| Seat | Verdict | 🔴 Critical | 🟡 Warning | 🟢 Suggestion | ⚪ Unconfirmed |
|------|---------|-------------|------------|----------------|-----------------|
| qc-specialist (qc1) | Request Changes | 0 | 2 | 10 | 3 |
| qc-specialist-2 (qc2) | Approve | 0 | 0 | 12 | 0 |
| qc-specialist-3 (qc3) | Request Changes | 0 | 6 | 8 | 3 |

## Gate decision: **Request Changes** (fix wave required)

Zero Critical across all seats. Six distinct Warnings after cross-seat dedup; all are
Batch-2 contract-readiness gaps (small fixes; none invalidates Tasks 1–3 behavior).
Seat 2's independent Approve confirms the implemented behavior is spec-clean; the
gate blocks on contract integrity only. Under `Findings cleanup: zero-residual` all
fixable Warnings/Suggestions fix now in one wave; no open residual R# is registered.

## Consolidated Warnings (deduped; every row traceable to qcN findings)

| ID | Finding (trigger → impact) | Sources | Fix |
|----|----------------------------|---------|-----|
| W1 | `_record_failed_page` (database.py:402-413) rewrites `ingestion_runs.outcome='failed', finished_at=?` unguarded → a late/stale failed page via public no-payload `record_page` can regress a terminal run (`complete`→`failed`) and move `finished_at` backwards, bypassing `finish_run` discipline; seat 2 extends: `finish_run` re-finish also unguarded | qc1 F-001 (W) · qc3 F-002 (W) · qc2 QC2-001 (S→confirmed+extended) | Transition guard `WHERE outcome='running'` on failure path and re-finish; tests: late/stale failed page, terminal run preserved, re-finish rejected |
| W2 | Canonical-form ambiguity + untested forms: `finish_run` docstring-"preferred" record form has zero tests branch-wide and validates `finished_at` against record's `started_at` (weaker than scalar form's DB baseline); `record_page` `video`/`videos` dual params both live; `upsert_part` explicit-`video_part_id` branch uncalled/untested; `start_run` retry path untested | qc1 F-002 (W) · qc3 F-004 (W) · qc2 (S) | Greenfield API, no speculative compatibility forms: reduce each API to one canonical form (remove uncalled branches); tests for every surviving form; baseline alignment |
| W3 | `MetadataRepository.__init__` accepts any `sqlite3.Connection` without verifying `row_factory=Row` + FK pragma → opaque TypeError on read paths / silent FK-enforcement loss for self-built connections | qc3 F-001 (W) · qc1 F-004 (S) | Validate supplied connection at construction (fail fast); test |
| W4 | Commit-boundary matrix implicit + class docstring over-claims ("low-level methods … without committing" while `start_run`/`finish_run`/`initialize_schema`/`_record_failed_page` commit) → Batch 2 must guess which methods commit | qc3 F-003 (W) · qc1 F-003 (S) | Correct docstrings; explicit commit matrix per public method |
| W5 | `record_page` failure-protocol edges untested/undocumented: failed page + payloads with no write failure silently commits payloads with a `'failed'` page row and leaves run `running`; ok page whose writes fail records no failure evidence (caller must make a second no-payload call) | qc3 F-005 (W) · qc2 QC2-009 (S) | Document + test both edges; align with spec's bounded failure protocol |
| W6 | `open_database` special-cases `file:` paths but `connect()` lacks `uri=True` → branch broken as a URI (stray literal `file:…` file on URI-disabled builds), untested, build-dependent | qc3 F-006 (W) · qc1 F-005 (S) · qc2 QC2-003 (S) | `connect(..., uri=True)` + test, or drop the branch; test what remains |

## Suggestions (disposition — zero-residual)

**Fix now (same wave):**
- S-fix-1: `models.py` comment contradicting its own `__all__` exports → fix comment (qc1 F-010, qc3 S).
- S-fix-2: `storage/__init__.py` export asymmetry → re-export `MetadataRepository` + models (qc1 F-008, qc2 QC2-008).
- S-fix-3: redundant LIKE-marker sweep in no-secret test → drop (qc1 F-011; Task 3 M#2).
- S-fix-4: enum CHECK literals duplicated 4× with no parity test → single shared constants + parity assertion (test-side only) (qc1 F-006, qc3 S).
- S-fix-5: `status=` param vs `processing_status` naming → rename to unambiguous name (qc1 F-012, qc3 S).

**Carried to Batch 2 (durable roadmap, not this plan's code):**
- S-carry-1: schema-level error-code shape CHECK as defense-in-depth; record boundary stays the secret-prevention SSOT per spec → Batch 2 must inherit record-level validation as a hard contract rule (qc3 S; qc2 ⚠️#4).
- S-carry-2: schema version stamp (IF NOT EXISTS silently accepts divergent legacy DBs) → needs spec-level decision in Batch 2 contract acceptance; no legacy DB can exist today (fresh rebuild only) (qc2 QC2-010).
- S-drop-1: FK-child indexes (`videos.mid`, `ingestion_runs.mid`) until ingest volume lands — speculative until then (qc3 S).

**Accepted with rationale (no action):** fixtures `tests/fixtures/__init__.py` beyond brief (import mode) (qc3; Task 3 M#1); formatting-sensitive DDL-substring assertions by design (Task 3 M#4); Task 2 M#6 closed by Task 3's aid-COALESCE test (qc1/qc3); Task 2 M#7 resolved as spec-intended — `error_code` nullable per spec (qc1/qc2); Task 1 Important verified fixed in `5f22fc6`.

## ⚪ Unconfirmed (→ mandatory QA gate; consistent across seats)

- U1: runtime pass counts implementer-reported (21 focused / 714 full) → QA re-runs.
- U2: built-wheel/sdist inclusion of `schema.sql` unverified (no pip/build tooling in environment; offline package-data + importlib.resources contract test is the in-diff evidence).
- U3: QA re-run parity — control checkout `.venv` interpreter + pytest default prepend import mode + exact focused commands (feature worktree has no `.venv`, verified).

## Verdict math

Gate = Request Changes because Approve requires every seat's unresolved Critical=0 AND
Warning=0; seats 1 and 3 carry unresolved Warnings (W1–W6). No Unconfirmed verdict on
any seat (evidence channels intact for all three). Fix wave next: one dispatch carrying
W1–W6 + S-fix-1…5; targeted re-review by seats that raised blocking findings
(`qc-specialist`, `qc-specialist-3`), in-place `## Revalidation` in qc1.md / qc3.md.

## Revalidation round 1 (targeted, N=2: qc-specialist + qc-specialist-3)

Fix wave 1 = commit `6d76ea4` (`ff81140..6d76ea4`, 6 files, +460/−181, schema.sql
untouched). Both targeted seats returned **Approve**: all six Warnings resolved
(test-pinned), no regression found (locked order / 3NF / FK RESTRICT / bounded codes /
offline imports / 21-preserved-test baseline all verified; runtime arithmetic
internally consistent). Consolidated gate after round 1: **Approve on W level — 0
Critical / 0 Warning unresolved**; open items are Suggestions only.

Open Suggestions entering round 2 (PM dispositions, zero-residual):

| ID | Finding | Sources | Disposition |
|----|---------|---------|-------------|
| S-fix-6 | Failure-path run transition lacks ordering check vs run's stored `started_at` while `running` (inconsistent caller clocks could set `finished_at` below start; terminal runs already untouchable) | qc1 F-016 (new) | **Fix now** — mirror `finish_run`'s DB-baseline check (one guarded condition) + test |
| S-fix-7 | Read-path exception discipline: `read_cursor`/`run_stats` raise `ValueError` for type errors (isinstance failures), unlike the `TypeError` discipline used elsewhere | qc3 F-012 | **Fix now (nit)** — normalize exception discipline to `TypeError` for type errors; document return-shape convention in docstrings. Typed read-model unification (dataclass returns for `run_stats`/`list_pending_parts`) is **carried to Batch 3 CLI contract** (consumer-defined shapes) |
| S-fix-8 | `upsert_video`'s aid-COALESCE stable-identifier policy undocumented (test-pinned only) | qc3 F-014 | **Fix now** — one docstring clause stating the policy (first non-null aid wins, backfills NULL, never overwrites) |
| S-fix-9 | Rewritten rollback test dropped the user-row assertion that proved the FIRST write rolled back | qc3 F-018 | **Fix now** — restore one-line assertion (test-only) |
| S-fix-9 | Commit matrix omits the no-payload non-failed page sub-case (behavior verified unchanged) | qc3 F-019 | **Fix now** — one docstring clause making the matrix exhaustive |

Carried unchanged: S-carry-1 (record-level secret-prevention boundary → Batch 2),
S-carry-2 (schema version stamp decision → Batch 2), S-drop-1 (FK-child indexes —
dropped, speculative). ⚪ U1–U3 remain mandatory-QA-gate evidence (not code-fixable).

## Round 2 (final convergence micro-fix)

One implementer dispatch carrying S-fix-6…9 landed as commit `2063a1a`
(`6d76ea4068d04d30e3e4f8123454020c901d4461..2063a1a`, 2 files, +132/−16,
`schema.sql` byte-untouched; TDD red→green: focused 31→33, full 724→726,
implementer-reported). Targeted re-review round 2 (N=2: qc-specialist +
qc-specialist-3), in-place round-2 subsections in qc1.md / qc3.md `## Revalidation`:

- qc-specialist: **Approve** — S-fix-6 resolved (DB-baseline clock guard verified:
  same SELECT shape + identical message as `finish_run`, reject-before-any-write,
  terminal/FK/valid-clock branches preserved, pinned test); no new findings;
  regression lens clean.
- qc-specialist-3: **Approve** — S-fix-7/8/9a/9b all resolved (28-site exception
  discipline sweep of database.py; `list_pending_parts` extension judged sound —
  same finding class, test-pinned, no API redesign; aid-policy docstring matches
  SQL semantics; user-row rollback assertion restored; commit matrix exhaustive);
  no new findings; regression lens clean; implementer's self-caught docstring
  correction verified truthful.

## Final gate decision: **Approve**

- Tri state after convergence: qc-specialist Approve (0C/0W/0 open S) ·
  qc-specialist-2 Approve (0C/0W/0, initial wave) · qc-specialist-3 Approve
  (0C/0W/0 open S). Zero unresolved Critical/Warning across all seats; zero open
  Suggestions (round-2 verified); zero open residual R# (`zero-residual`
  satisfied).
- Evidence channels intact for all seats; the three ⚪ notes (U1 runtime pass
  counts, U2 built-wheel `schema.sql`, U3 interpreter/import-mode parity) are
  QA-routed evidence items, **not** unresolved QC findings — they remain
  **mandatory QA gate** inputs and are NOT closed by this Approve.
- Carry-over contract items remain recorded in the plan's Durable Roadmap
  (S-carry-1 record-level secret-prevention boundary → Batch 2, S-carry-2 schema
  version stamp decision → Batch 2, typed read-model unification → Batch 3).
- Final reviewed head: `2063a1a` on `feature/20260909-structured-metadata-schema`;
  cumulative plan branch `c98f140..2063a1a`.
