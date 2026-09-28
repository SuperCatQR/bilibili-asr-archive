# Spec: `bili-asr proofread` — the merge-v2 proofread pipeline

**Status:** active (plan `20260928-proofread-pipeline`, iteration `iter-2026-09-ops-readiness`)
**Primary consumers:** the `proofread` / `proofread-merge` subcommands (`src/bili_asr/proofread.py`, `src/bili_asr/cli.py`), `tests/test_proofread.py`
**Change policy:** requirement changes require PM change-control, the same bar as the frozen specs.

## Problem

A part's transcript exists twice: a local ASR route (the bundle's `raw` sidecar) and a caption route (B站's AI/CC subtitle in `archive.db`). Proofreading against both by hand does not scale; the 2026-09-22 wave's temporary scripts are not repeatable by an operator. This spec fixes the merge-v2 method — measured on that wave's corpus — as the CLI contract.

## Method (ratified, measured 2026-09-22 on `/mnt/123pan`)

- **Blocks are built from ASR VAD segments only** (`BLOCK_GAP_MS = 1500`: a segment starting >1.5 s after the block's current end opens a new block). Subtitles never define block boundaries — letting captions split blocks was the 22.8% raw-segment drift mistake.
- **Block size**: the ~12 s plateau (`BLOCK_TARGET_MS = 12_000`); 12→16 s adds nothing.
- **Similarity**: `difflib.SequenceMatcher` with **`autojunk=False`** (the autojunk default was a documented 2026-09-18 trap). ≥0.85 **agree** / 0.75–0.85 **minor** / <0.75 **review**.
- **The banned criterion**: "subtitle-entry midpoint falls outside the ASR segment" must not exist — it fabricated 23–27% false gaps. The true gap count is ~0 (zero-overlap criterion, 2026-09-22). Guard B is a test that greps `src/bili_asr/proofread.py` for the banned tokens and fails if found.
- **Measured lift**: 78.6% block agreement vs 22.8% raw-segment agreement on the same corpus.

## Count-guards

- **Guard A (coverage)**: every subtitle entry and every ASR character appears in exactly one block; a violation aborts non-zero naming the block (`GuardViolationError`).
- **Guard C (stability)**: same inputs → byte-identical outputs.

## CLI contract

- `bili-asr proofread --bvid <bvid[:pN]>` writes `.tmp/proofread-work/inputs/<bvid>.p<N>.sidebyside.md` (columns: time | ASR | 字幕 — pure mechanical alignment, no adjudication) and `.tmp/proofread-work/align/<bvid>.p<N>.alignment.jsonl`. Exits non-zero with a clear message when a route is missing.
- `bili-asr proofread-merge --bvid <bvid[:pN]>` reads the completed side-by-side copy (the marked-up `.sidebyside.md.定稿` in the same inputs dir), applies per-block decision markers, and writes the final `.proofread` transcript artifact plus corrections accounting.
- **Marker syntax**: appended to a block heading after `>>`: `keep` (default, accepts the 字幕 column), `use-asr`, `use-sub`, `custom: <text>`.
- Write boundary: only `.tmp/proofread-work/` and the `.proofread` transcript variants; the four canonical transcript families stay `publish-transcripts`'.

## Non-goals

The human/agent adjudication loop itself (side-by-side judgement is the operator's), review-wave orchestration (an existing manual protocol), and reading any machine proofread products as fixtures (fixtures are synthetic).
