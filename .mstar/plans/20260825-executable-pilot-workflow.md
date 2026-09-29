# Executable Two-Branch Pilot Workflow

> Candidate source: audit `BUG-03` (`.mstar/plans/audit-2026-08-24/README.md`).
> Iteration: `iter-2026-08-pilot-ops`.
> Execution mode: `sdd`.

## Status

- Priority: P1
- Category: bug / product completeness
- Status: Done
- Depends on: none (prior iteration 001/002/005 merged to `main` at `559dfcb`)
- Findings cleanup: zero-residual

## Goal

Make `bili-asr pilot --n N` meet the frozen MVP proof bar: execute and summarize a bounded mixed run (subtitle-hit and audio→ASR) to terminal states, rather than only selecting existing manifest rows. Default N is the spec ~20; `--n` may be lowered for smoke.

## Global Constraints

- Preserve `bili_client.py` as the only HTTP owner; `cli.py` stays the composition layer. Pilot orchestration lives in `cli` (or a cli-owned helper); it must not open sockets or import FunASR at module import time.
- No live HTTP in tests; inject `build_default_transport` + stub `asr.transcribe`. Do not split `harvest_subtitle` into a new HTTP path.
- Missing optional ASR (`funasr`) must raise existing `ASRDependencyError` (install hint `pip install -e "bilibili-asr-archive/[asr]"`) and a nonzero result; never mark the row `archived`.
- Never echo or persist `BILI_SESSDATA`/`--sessdata`; credentials/signed URLs absent from manifests and diagnostics. `--sessdata` is a cookie **value** (same as `harvest-subs` / `_resolve_sessdata`), not a filesystem path.
- No schema migration; JSONL last-write-wins per `work_id`; `VALID_STATUSES` and `classify_risk` taxonomy unchanged.
- Page identity: `work_id` = `bvid:p{page_index}` (zero-based); filesystem names use `artifact_stem` (`bvid.pN`) only — never put `:` in paths. Multi-part bvid: every pagelist page, never silent `pages[0]`.

## Interfaces (locked)

Live seams (do not rename or change signatures):

- `subtitles.harvest_subtitle(client: BiliClient, target: PageIdentity | str, store: ManifestStore, archive_root: str | os.PathLike[str]) -> str` — returns manifest **status** `"subtitle_done"` | `"needs_audio"` (not a path). Bare `str` bvid is allowed only when pagelist length is 1 (`AmbiguousPageError` otherwise). Prefer passing `PageIdentity`.
- `audio.download_audio(client: BiliClient, target: PageIdentity | str, out_path: str | os.PathLike[str], store: ManifestStore | None = None) -> str` — returns the on-disk audio path. Callers derive `out_path` from `artifact_stem` (`{archive_root}/audio/{stem}.m4a`).
- `asr.transcribe(audio_path: str, model_name: str | None = None) -> list[dict[str, Any]]` — `funasr` imported only inside this function.
- `archive.write_archive(archive_root, entry, segments, *, source: str, raw: Any | None = None) -> dict[str, str]` — keyword-only `source`/`raw`; paths keyed by `archive_stem(entry)`.

Pilot composition (cli):

- `_pilot_select(entries: dict[str, dict[str, object]], n: int) -> list[dict[str, object]]` — deterministic, prefers short `duration_s`, reserves both branches when possible. Executable pilot selects from `meta_ok` (and still-processable `subtitle_done` / `needs_audio` / `audio_ok` for resume); it does not invent a second selector.
- For each selected row: resolve `PageIdentity` (existing `_identity_from_entry` / `page_identity`); `harvest_subtitle` if not already `subtitle_done`/`needs_audio`/`audio_ok`/`archived`; subtitle-hit → `write_archive(..., source="subtitle")` without `transcribe`; no-subtitle → `download_audio` then `transcribe` then `write_archive(..., source="asr")`.
- CLI: `bili-asr pilot --n N [--archive-root]`; optional `--sessdata` only if harvest/download run (cookie value via `_resolve_sessdata`). Bounded N; default 20.

## Tasks

### Task 1: Execute a bounded mixed pilot

- [x] Fresh `meta_ok` manifest: deterministic selection preferring short items, reserving both branches when possible.
- [x] Selected items: probe/harvest subtitles first; subtitle hits → `subtitle_done` → archive from subtitle data without ASR.
- [x] Selected no-subtitle items: download audio, invoke local ASR, write transcript artifacts, persist `archived` with `audio_path` + archive paths.
- [x] Per-item failures, branch counts, final terminal states persisted and reported; unavailable branch coverage → nonzero exit identifying what is missing.
- [x] Multi-part selected bvid: every pagelist `work_id` processed or reported failed (no page-1-only success).
- [x] `BILI_SESSDATA`/`--sessdata` only as a cookie **value** (not a filesystem path); never echoed or persisted.

Run: `python -m pytest bilibili-asr-archive/tests/test_pilot_select.py bilibili-asr-archive/tests/test_cli_pilot.py -q` — all pass with fake transport and stubbed ASR.

### Task 2: Pin idempotent reruns and dependency errors

- [x] Completed pilot rerun skips archived rows / produces no duplicate artifacts or manifest rows.
- [x] Missing optional ASR dependency returns a clear nonzero result and does not mark the row archived.
- [x] Subtitle branch never calls ASR; audio branch calls it exactly once.

Run: focused suite above exits 0.

## Acceptance Criteria

- Fresh `meta_ok` fixture drives a bounded `pilot --n N` to both branch outcomes under fakes (operator-visible summary: branch counts, terminal states, missing-branch reason).
- Subtitle-hit rows archived without ASR; audio rows archived only after successful transcript writing.
- Missing ASR dependency leaves row non-archived, nonzero result, install hint (`pip install -e "bilibili-asr-archive/[asr]"`).
- Unavailable branch coverage → nonzero exit identifying what is missing; completed rerun is idempotent (no duplicate artifacts/rows).
- When a selected bvid has multiple pagelist parts, each `work_id` (`bvid:pN`) is processed or reported failed (no silent page-1-only pilot).
- Focused pytest exits 0; README documents execution, branch coverage, rerun, optional-ASR failure.
- `git status --short` shows only in-scope files.

## STOP Conditions

- Frozen spec read as selection-only pilot → STOP and escalate before changing behavior.
- Manifest cannot distinguish subtitle hit from ASR result without a `status` change → STOP, align the status machine first.
- Fake ASR seam cannot be injected without importing FunASR at import time → STOP; preserve lazy import.

## Prepare → Execute Handoff

Interfaces are locked: live harvest/download may use injected fake HTTP; tests never call the network. Execute with fake client + monkeypatched ASR proving both branches, then focused suite before plan B broadens entrypoint integration coverage.

## Durable Review Summary

- Feature HEAD / merge: `c4ce9bbb8b6c0709699df68489619ac3e6ef5ff3` (FF into `iteration/iter-2026-08-pilot-ops`).
- L2: Task 1 Approved (`8de3846`); Task 2 Approved (`301c48e`).
- QC tri + targeted revalidations: Approve (final `qc-consolidated.md`). Open Critical/Warning: 0.
- QA mandatory/full: Approve. `PYTHONPATH=src .venv-pm/bin/python -m pytest -q` → 180 passed (focused pilot suite 13 passed).
- Notable decisions: branch coverage seeded from already-archived ledger rows (resume-safe); completed-rerun skip only when no non-archived rows remain; named per-item failure classes; risk-budget abort prints branch/terminal summary; `audio_ok` resume reuses existing audio path.
