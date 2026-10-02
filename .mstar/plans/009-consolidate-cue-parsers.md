---
plan_id: 009-consolidate-cue-parsers
project: _default
primary_spec: .mstar/plans/audit-2026-10-02/001-second-pass-asr-cache-bust.md
status: draft
created_at: 2026-10-02
execution_mode: sdd
plan_parallelism: serial
---
# Plan 009 — Consolidate the three cue-parsers into one transcripts module

## Status
- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none (structural precondition for residual C-R3)
- **Category**: tech-debt
- **Confidence**: MED
- **Evidence**: `src/bili_asr/quality.py:645-708`, `src/bili_asr/proofread.py:485-528`, `src/bili_asr/asr.py:1337-1347`
- **Planned at**: commit `ff39fd0`, 2026-10-02

## Problem

Three modules independently parse the same two artefact shapes — SRT blocks and JSON segment lists —
with divergent logic:

- `quality._read_cues(path, text)` (`quality.py:645-708`) accepts **any parseable JSON list** (no source
  guard).
- `proofread.read_asr_route_ms` (`proofread.py:485-528`) guards `source == "asr"` before accepting — it
  refuses a caption-derived or merged sidecar so it cannot put one route on both sides of the table.
- `asr.segments_to_srt` / `segments_to_txt` (`asr.py:1337-1347`) render segments out to SRT/TXT.

Residual **C-R3** ("silent-pass sibling readers of `bundle.raw.json`") names exactly this divergence:
`quality._read_cues` will accept any parseable document, so an all-agree-with-itself table can report
success. Consolidation into one shared reader is the **structural precondition** for closing C-R3 cleanly —
with one reader, the source-guard is applied uniformly instead of being optional per call site.

## Current state (excerpt)

`src/bili_asr/proofread.py:506-517` (the guarded reader):
```python
document = json.loads(raw_path.read_text(encoding="utf-8"))
source = document.get("source")
if source != "asr":
    raise ProofreadRouteError(...)          # the guard quality.py lacks
segments = document.get("segments")
if not isinstance(segments, list) or not segments:
    raise ProofreadRouteError(...)
```

`src/bili_asr/quality.py:645-708` — `_read_cues` parses SRT and JSON sidecars with no `source` check.

## Approach

Create one shared cue module, e.g. `src/bili_asr/transcripts/cues.py`, exposing:

- `read_cues(path: Path, *, require_source: str | None = None) -> ...` — the single parser for SRT blocks
  and JSON segment lists. When `require_source` is set, enforce it (raise on mismatch); when `None`, accept
  any parseable document (preserving `quality.py`'s current lenient behaviour for its own consumers).
- `segments_to_srt(segments)` / `segments_to_txt(segments)` — moved from `asr.py`.

Migrate the three owners to the shared module:

- `quality.py` → call `read_cues(path)` (no source guard) — **must preserve the frozen output order of
  `quality.py`'s reason codes** (the coverage/quality report's reason-code ordering is a pinned contract).
- `proofread.py` → call `read_cues(path, require_source="asr")` — behaviour unchanged (still refuses
  non-ASR sidecars, still names the source found).
- `asr.py` → import `segments_to_srt`/`segments_to_txt` from the shared module.

## Files

- **Create**: `src/bili_asr/transcripts/cues.py` — the shared reader + segment renderers (with an
  `__init__.py` for the `transcripts` package, or place it in an existing module if a new package is
  undesirable — see STOP conditions).
- **Modify**: `src/bili_asr/quality.py` — `_read_cues` delegates to the shared reader.
- **Modify**: `src/bili_asr/proofread.py` — `read_asr_route_ms` delegates with `require_source="asr"`.
- **Modify**: `src/bili_asr/asr.py` — `segments_to_srt`/`segments_to_txt` move to the shared module.
- **Test**: `tests/test_quality.py`, `tests/test_proofread.py`, `tests/test_proofread_routes.py` — confirm
  no behaviour change (see gates).

## Out of scope

- Closing residual C-R3 itself (this plan is the precondition; a follow-up decides which readers gain a
  source guard).
- Changing the coverage/quality reason-code vocabulary or order.
- The raw-sidecar size (residual C-R1) — a separate concern.

## Verification gates

- **Reason-code order preserved**: `python3.12 -m pytest tests/test_quality.py -q` → the coverage/quality
  tests pass unchanged (the frozen reason-code order is intact).
- **Proofread route guard intact**: `python3.12 -m pytest tests/test_proofread_routes.py -q` → the
  refusal-on-non-ASR-source tests still pass (the `require_source="asr"` enforcement is behaviour-identical
  to the current inline guard).
- **ASR render intact**: `python3.12 -m pytest tests/test_asr_qwen.py -q` → the segment-rendering tests pass.
- Single reader: `rg -n 'def _read_cues|def read_asr_route_ms|def segments_to_srt' src/bili_asr/` → the
  parsing logic lives in the shared module, not inline in three places.

## STOP conditions

- If creating a new `transcripts/` package conflicts with the project's packaging (`setuptools.packages.find
  where=["src"]` should pick it up, but confirm), STOP — instead place `cues.py` in an existing module
  (e.g. `bili_asr/cues.py`) and report the packaging reason.
- If the three current implementations **disagree** on a real corpus row (e.g. different stems/fallbacks),
  STOP — report the divergence before consolidating; consolidation must not silently pick one behaviour.

## Done criteria

- [ ] `python3.12 -m pytest tests/test_quality.py tests/test_proofread_routes.py -q` passes (behaviour preserved).
- [ ] `python3.12 -m pytest tests/test_asr_qwen.py -q` passes.
- [ ] `rg -n 'def _read_cues|def segments_to_srt' src/bili_asr/quality.py src/bili_asr/asr.py` → no inline parser remains in the owners.
- [ ] `git diff --check -- src/bili_asr/transcripts/ src/bili_asr/quality.py src/bili_asr/proofread.py src/bili_asr/asr.py` exits 0.
- [ ] No files outside the Files list are modified.

## Drift check

`git diff --stat ff39fd0..HEAD -- src/bili_asr/quality.py src/bili_asr/proofread.py src/bili_asr/asr.py` — if any changed, re-open the excerpts and confirm the three parser shapes still match before consolidating.
