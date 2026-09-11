# Task 2 L2 review — Prove idempotency and security

- Review range: `7d4161f9d73c5dbfa97ac5c4c1d5406b48c8cd66..ef21ddeb4f8bc65d01c7c0827b219873fc661e6a`
- Diff file: `review/task-2.diff`
- Implementer report: `task-2-report.md`

### Spec Compliance

- ✅ Spec compliant
- ⚠️ Cannot verify from diff: full-suite `162 passed` (PM pytest on `ef21dde`; not re-run here)

Task 2 adds the page-2 stop/resume idempotency path, sidecar secret rejection, and README resume/exit-2 docs. Cursor schema, atomic `os.replace`, `--resume` only on matching-mid `risk_interrupted`, and `complete` vs `limited` remain Task 1 behavior; this diff does not regress them. HTTP stays in `bili_client`; `_validate` still returns only `_SCHEMA_KEYS`. Extra payload keys (`cookie`, signed URL, traceback) are dropped before write. `last_api_error_code` strings over 64 chars or containing `SESSDATA` / `cookie` / `http(s)://` / `Traceback` are rejected. CLI interrupt still persists `exc.last_code` / `exc.code` (API scalars), not exception text.

### Strengths

- End-to-end `test_cli_page2_stop_resume_is_idempotent` matches the brief: 412 exhaust on pn=2 → `next_page=2` / `risk_interrupted` / JSONL `{BV1A, BV1B}` only; `--resume` first `pn` is 2, BV1C appended, unique `work_id` lines, terminal `complete`.
- Failed page is not claimed complete (`state != complete` after interrupt).
- README table distinguishes exit 0 (`complete` vs `limited`, no auto-resume) from exit 2 (`risk_interrupted`, resume at unmerged `pn`).

### Issues

#### Critical

None.

#### Important

None.

#### Minor

- Secret filter is substring-on-dumped-schema, not a typed code allowlist. Extra keys with secrets are stripped rather than rejected (test asserts this). A short `last_api_error_code` string without the listed markers (no `Traceback` / URL / `cookie`) could still persist. CLI interrupt paths pass API codes, so this is residual defense-in-depth, not a current write bug.
- Resume overlap (page 2 re-emitting a page-1 `work_id`) is not asserted; uniqueness relies on existing ManifestStore last-write-wins. Out of this task’s new scenario, acceptable for plan QC.

### Assessment

**Task quality:** Approved
