# Task 1 Review — Schema contract, bootstrap split, and structural guard

- Plan: `.mstar/plans/20260911-transcript-storage.md` (task 1 of 3)
- Review mode: **A, L2, diff-first** — read-only, leaf executor, no delegation
- Range: base `6ee7c6a` → head `d4cae24` (`feature/20260911-transcript-storage`)
- Worktree: `.worktrees/20260911-transcript-storage` (control harness: `/root/workspace/bilibili-asr-archive`)
- Authoritative spec: `.mstar/iterations/iter-2026-09-subtitle-transcript-sqlite/specs/transcript-storage.md`
- Diff: `.mstar/sdd/20260911-transcript-storage/review/task-1-diff.md` (7 files, +1303/−43)
- Implementer report: `.mstar/sdd/20260911-transcript-storage/implementer-task-1-report.md` (claims treated as unverified)

## Spec Compliance

**✅ Spec compliant — no Critical, no Important findings; 2 Minor (both cross-plan handoff precision, neither blocks Task 1).**

Every locked artifact required by the brief is present, spec-exact, and pinned by a test that fails if reverted:

| Locked decision (spec) | Artifact | Pinning test |
|---|---|---|
| `transcripts` gains `language` + `content_sha256`, `CHECK` on both (§2.1, §2.4) | `schema-transcripts.sql:12` | `test_storage_schema.py:851` (exact column manifest + `EXPECTED_CHECK_ENUMERATIONS`) |
| version key widened to `(video_part_id, source_kind, language, version)` (§2.1) | `schema-transcripts.sql:26` | same test (`EXPECTED_UNIQUE_CONSTRAINTS` + DDL fragment) |
| **partial** unique content index, caption kinds only (§2.2, §2.7) | `schema-transcripts.sql:33-35` | `test_storage_schema.py:1151` + `EXPECTED_INDEXES`/`EXPECTED_PARTIAL_INDEX_CLAUSES` (`:215`, `:233`) |
| `transcript_segments` moved verbatim (§3.1) | `schema-transcripts.sql:37-46` | resource test negative asserts (`:375-390`) + inspection manifest |
| `acquisition_runs` kind-keyed, `credential_present` on the run, no per-part state (§2.3, §2.4) | `schema-transcripts.sql:50-70` | inspection test; `test_acquisition_run_record_validates_the_locked_shape` (`:1492`) |
| `acquisition_attempts` `PK(run_id, video_part_id)` + outcome↔error_code↔transcript_id CHECK matrix (§2.4) | `schema-transcripts.sql:72-96` | `:1363` (5 legal), `:1384` (8 illegal), `:1401` (one outcome per part per run) |
| `ix_acquisition_attempts_part_time` | `schema-transcripts.sql:98-99` | inspection test (`EXPECTED_INDEXES`) |
| `v_pending_subtitles` columns + last-attempt evidence (§2.5) | `schema-transcripts.sql:106-141` | `EXPECTED_VIEW_COLUMNS` loop; behavior: `:1257` |
| `ON DELETE RESTRICT` on every FK (Global Constraints) | `schema-transcripts.sql` (3 new FKs) | inspection test asserts `row["on_delete"] == "RESTRICT"` for **every** FK of every base table |
| 3NF — no derived duplicates in base tables | base tables unchanged in shape | `test_transcript_base_tables_store_no_derived_values` (`:1222`) + exact manifests reject any extra column |
| conditional bootstrap: fresh/current apply, pre-iteration skip (§3.1–3.2) | `database.py:111-119`, `:129-147` | `:1018` (fresh), `:1028` (idempotent re-open), `:1082` (legacy untouched) |
| `require_subtitle_schema` structural guard + `SchemaContractError` (§3.3) | `database.py:43`, `:122-126`, `:150-164`; exported `database.py:658`, `__init__.py` | `:1141` (missing object ⇒ raises), `:1018` (fresh ⇒ passes), `:1082` (legacy ⇒ raises with bounded text) |
| vocabulary + DTOs (§2.4, §4, §5) | `models.py:19-22`, `:282`, `:304`, `:326` | `EXPECTED_LITERAL_SETS`/`EXPECTED_ENUM_COLUMNS` (DDL↔frozenset↔`Literal`), `:1429`, `:1450`, `:1492` |
| new resource ships in the wheel | `pyproject.toml:35` | `test_schema_sql_is_declared_and_read_as_package_resource` (`:365-390`) |

### Verification I performed (independent of the implementer report)

- **Focused suite reproduced:** `pytest tests/test_storage_schema.py -q -p no:cacheprovider` → **`36 passed in 1.31s`** (bytecode/cache writes disabled; `git status --porcelain` empty before and after — the worktree was not mutated).
- **DDL fidelity reproduced mechanically:** all **6/6** statements of spec §2.4/§2.5 (the `transcripts` table, the partial index, `acquisition_runs`, `acquisition_attempts`, the attempt index, the view) are present **verbatim** (whitespace-normalized) in `schema-transcripts.sql`.
- **Verbatim move proven three ways:** the `transcript_segments` text in the new script is identical (whitespace-normalized) to (a) the block removed from `schema.sql` as recorded in the review diff, and (b) `LEGACY_TRANSCRIPT_TABLES_DDL` in the test (`tests/test_storage_schema.py:317`). The legacy constant is therefore a faithful stand-in, not a look-alike.
- **Removed-line census** (nothing silently dropped): `schema.sql` −23/+4 (exactly the two table blocks replaced by a pointer comment; no other hunk), `database.py` −2 (docstring lines only — **no production code removed**), `models.py` +145/−0, `__init__.py` +26/−0, `schema-transcripts.sql` +141, tests −17/+903. Every one of the 17 removed test lines is replaced by a strict superset or an equivalent (imports, `VIEWS`, the widened unique key, the resource assertions, the inlined `literal_sets`, the view loop) — **no assertion relaxed, no test deleted, no skip/xfail added**.
- **`git diff --check` corroborated:** no added line in the diff carries trailing whitespace; the diff contains exactly 7 files.
- **Split safety verified by reading the shipped `schema.sql`:** the remaining 10 tables + `v_video_parts` / `v_ingestion_run_stats` / `v_pending_metadata` reference `transcripts` nowhere (only the new comment mentions it), and no other module reads the schema resource or the reserved tables (grep over `src/`: only `database.py`'s object tuple). The plan's drift-check premise holds.
- **Bootstrap self-healing checked by reasoning:** `initialize_schema` re-applies the transcript script whenever the columns are present, so a crash mid-script (table created, later objects missing) is repaired on the next open; a legacy database takes the skip branch and is left byte-identical (proved by `:1082`).
- **Non-vacuity confirmed against the named mutations:** removing the index `WHERE` clause breaks both the inspection assertion (`_stored_ddl(...).endswith("WHERE source_kind IN ('subtitle-ai', 'subtitle-cc')")`) and the behavioral `:1151`; an unconditional transcript script breaks `:1082` with exactly the half-apply error class claimed. Both target assertions exist and are exact; I did not re-derive the mutations themselves (that requires mutating the checkout).

### ⚠️ Cannot verify from diff (for PM to close)

1. **Full-suite regression claim** (`1120 passed, 3 skipped`; baseline `1096/3`; +24) is implementer evidence only — the full suite was not re-run by me (prohibited). The focused module is verified green, and the +24 arithmetic reconciles exactly with the 13 new test functions / 5+8 parametrized cases in the diff. Confirm at the plan-level gate.
2. **The three red-evidence mutations** are self-reported. I verified the assertions they target exist and are exact (see above), but not the mutation runs.
3. **`docs/metadata-storage.md:13` is now inaccurate** — it still says the bootstrap "initializes the checked-in schema (`src/bili_asr/storage/schema.sql`)". The implementer deliberately left it (the plan's Drift Check and the CLI plan's Files list assign it to `20260911-subtitle-cli-cutover`, whose lines 229-230/243-246 own `docs/metadata-storage.md` + `README.md`). PM: ensure that update lands before plan Done — Task 1 is what made the sentence stale.
4. **The locked pending-view order** (`attempted ASC, last_attempt_at ASC, bvid ASC, page_index ASC`) is deliberately *not* asserted in Task 1 — the view stays unordered and the repository imposes order (spec §2.5). Correctly deferred to Task 3 per the plan; Task 3's review must pin it.
5. **No wheel was built** (instructed). Packaging correctness rests on the declaration (`pyproject.toml:35`, package key `bili_asr.storage` matches the loader's `resources.files(__package__)`, both files live in `src/bili_asr/storage/`) plus the test that pins both entries. If QA wants hard proof, a wheel-content check belongs to the plan-level QA gate.
6. **Guard scope is exactly spec §3.3** (columns + `acquisition_runs` / `acquisition_attempts` / `v_pending_subtitles`; `transcript_segments` is *not* checked). This is safe only because the commands open via `open_database`, which recreates a dropped table — the CLI plan (line 169) does call the guard after opening. Confirm at CLI task review.
7. **Scope:** two files appear beyond the brief's five-file list — `pyproject.toml` (disclosed with rationale; required for the resource to ship in the wheel) and `src/bili_asr/storage/__init__.py` (the brief's own "and export it" locus; listed in the report's Files changed but not framed as an addition). Both changes are minimal and additive; no stray edits elsewhere.

## Strengths

- **The DDL is not "close to" the spec — it is the spec.** Independent extraction confirms 6/6 statements verbatim, and the moved `transcript_segments` block is byte-identical to what shipped before. This is the strongest possible form of fidelity for a locked-DDL task, and the implementer's claim survived mechanical re-derivation.
- **The bootstrap split is the honest reading of the constraint it exists for.** `_accepts_transcript_script` (`database.py:111-119`) encodes exactly §3.2 — absent *or* carries both columns — and the legacy branch is a true skip, so `CREATE TABLE IF NOT EXISTS`'s inability to widen a unique key can never half-apply. The nine-line helper is simpler than any migration-ish alternative and adds no fallback.
- **Structural guard, not a version stamp.** `_has_subtitle_schema` (`database.py:122-126`) checks columns *and* object presence, and `:1028` proves the distinction by dropping a view and observing the raise. The error is bounded (no path interpolation, no raw SQL).
- **Structural guards are genuinely load-bearing, not decorative** — exact column manifests, the exact FK pair set *with* `on_delete == "RESTRICT"`, unique/PK/declared-index sets including the `partial` flag *and* the `WHERE` clause text, CHECK fragments, view columns, and a 3NF column prohibition. Reverting any locked element fails loudly; the declared-index set-equality also rejects an unexpected extra index.
- **Refactor hygiene.** Nothing was weakened to make room for the new contract: `database.py` lost only docstring lines, `models.py` and `__init__.py` are purely additive, and every removed test line is a strict superset of what it replaced. The legacy-DB test is a *faithful* simulation (verified: the constant equals the removed block) rather than a convenient approximation.
- **Vocabulary is wired as one contract across three layers:** DDL CHECK literals ↔ `ALLOWED_*` frozensets ↔ `Literal` aliases (`EXPECTED_LITERAL_SETS`, `EXPECTED_ENUM_COLUMNS`) — so a drift between SQL and Python fails a test from either side.
- **Honest disclosure.** The beyond-brief `pyproject.toml` edit, the Python-only `finished_at` rule on a terminal run outcome, the verbatim `_caption_text` decision, and the `docs/metadata-storage.md` handoff were all surfaced in the report rather than left for the reviewer to find; each of those three choices is defensible and inside the spec, and the DTO's caption-text rule does match the gateway's (`sources/models.py:138-143`) field for field.

## Issues

### Critical

None.

### Important

None.

### Minor

**M1 — "stored trimmed" is enforced by the gateway, not at the storage boundary; the DTO's stated rule reads differently from spec §5.**
`_caption_text` (`src/bili_asr/storage/models.py:84-92`) validates but does not normalize — it returns the caller's string unchanged and only rejects "empty after strip". Spec §5 (spec line 456) says "`text` is stored trimmed". Today the shipped path satisfies §5 because the gateway trims first (`src/bili_asr/sources/bilibili_api_gateway.py:448`: `text = content.strip()`), so the content hash stays stable for identical captions. The risk is latent and documentary: the DTO docstring ("a caption row is stored as upstream returned it") states a *different* rule than §5, and Task 2's implementer will read one of the two as authoritative. Disposition (PM): either Task 2 strips at the storage boundary, or the §5 bullet names the gateway as the trimming point (architect/spec edit). No Task-1 change is required if the second route is chosen — the implementer disclosed the choice (report, *Self-review notes*).

**M2 — the exception message is not the spec §3.3 locked line; the CLI must compose it.**
`SchemaContractError` carries `"archive database predates the transcript schema; rebuild it (delete archive.db and re-run fetch-meta)"` (`src/bili_asr/storage/database.py:161-164`), whereas spec §3.3 locks `<command>: archive database predates the transcript schema; rebuild it (delete {archive_root}/archive.db and re-run fetch-meta)`. Omitting the `<command>:` prefix and the archive root is consistent with the duty split — the CLI knows both, and the CLI plan (line 57) states the command prints that fixed line — but it leaves one failure mode: a CLI that prints `str(exc)` produces a bounded, truthful line that still does **not** match the locked output (no path, no command prefix). Disposition: verify at the CLI task review / CLI-plan acceptance test; no Task-1 change needed.

## Assessment

**Task quality: Approved**

The locked contract is reproduced exactly, the bootstrap split is the correct minimal implementation of the rebuild stance, the structural guard is behavioural rather than a stamp, and every locked element is pinned by a test that fails when reverted. Regression risk is low: the change is additive apart from a verified verbatim block move, no existing assertion was weakened, and the independently re-run focused suite is green with a clean worktree. Both Minor findings are cross-plan precision items with named dispositions and do not require rework of `d4cae24`.

Two follow-ups travel with this approval (see ⚠️ 3 and 4): the `docs/metadata-storage.md` correction owned by the CLI plan, and Task 3's ownership of the locked pending-enumeration order.
