# Task 1 review (L2) — Define identity and migrate legacy rows

Reviewer: code-reviewer
Range: `a79b84b6f9586410941503a5e04989eca020efe6..d15f50f72cb978848308e369258cf7551e918168`
Diff: `.mstar/sdd/20260824-multipart-page-aware-pipeline/review/task-1.diff`

### Spec Compliance

- ✅ Spec compliant with the Task 1 brief and architecture SSOT for identity, `ManifestStore` keys, `get_compatible`, atomic migrate/freeze, and status identifiers.
- ⚠️ Cannot verify from diff:
  - Implementer pytest `127 passed` was not re-run (L2 does not execute suites).
  - `migrate_legacy_rows` is not wired into a CLI/command path in this diff; only `bili-asr status` prints unresolved ids. Later tasks must call migration.

Checked against brief + `archive-foundations-architecture.md`:

| Requirement | Evidence |
|---|---|
| `PageIdentity`, `format_work_id`, `parse_work_id`, `artifact_stem` | `page_identity.py`; frozen dataclass; stem `{bvid}.pN` with colon guard |
| Key store by `work_id`; `bvid` required; `get_compatible` | `manifest.py` `_entry_key` / `upsert` / `get` / `get_compatible` |
| Migrate only pagelist length 1 and no colliding `{bvid}.pN` (N≠0) | `unambiguous` + `_foreign_page_stems` |
| Ambiguous: preserve original fields + additive unresolved flags; no invented page fields | freeze path + `test_freeze_multipart_bare_row_byte_stable` |
| Report count + identifiers | `LegacyMigrationReport` + `cli._cmd_status` |
| Tests: stem no `:`; single-page migrate; freeze multi-page | `test_page_identity.py`, `test_manifest.py` |

Global constraints: no risk-taxonomy / SESSDATA / signed-URL edits; no live network or media; harvest/audio still on bare bvid (compatibility adapters preserved).

### Strengths

- Clear split: `:` only in `work_id`; filesystem uses `artifact_stem`.
- `get_compatible` does not guess among multiple processable pages.
- Migration is all-or-nothing via in-memory `next_entries` then existing atomic `save` (`.tmp` + `os.replace`). `dest_occupied` raises before persist.
- Ambiguous rows keep original keys and add only the three specified flags; tests assert no invented `work_id` / `page_index` / `cid`.
- `page_query_index` matches the locked helper even though harvest rewiring is out of this task.

### Issues

#### Critical

None.

#### Important

None that block Task 1.

Architecture `upsert` “rejects missing `work_id` for new automatic rows” is not implemented: `upsert` still accepts bare-bvid rows. That matches this task’s need to load/migrate legacy and keep current harvest callers compiling. Enforce the automatic-row reject when those callers start emitting `work_id`.

#### Minor

- `manifest.py` (migrate unambiguous block): `if colliding_stems: raise ManifestMigrationCollision` is unreachable; `colliding_stems` already falsifies `unambiguous`. Artifact collisions freeze (spec “Ambiguous … conflicting artifacts”); work_id overwrite still STOP-raises. Dead raise is noise, not a behavior bug.
- “Byte-for-byte” is object-key preservation after `json.dumps` rewrite, not the original JSONL line bytes/key order. Additive flags make a full-line identity impossible; the test’s original-field equality is the right bar.
- `cid is None` on `PageIdentity` is typed as `int`; the missing-cid branch is defensive for injected pagelists, not a typed None.

### Assessment

**Task quality:** Approved
