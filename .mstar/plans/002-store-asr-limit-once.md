---
plan_id: 002-store-asr-limit-once
project: _default
primary_spec: .mstar/plans/audit-2026-10-02/001-second-pass-asr-cache-bust.md
status: draft
created_at: 2026-10-02
execution_mode: inline
plan_parallelism: serial
---
# Plan 002 — Apply `--limit` once on the store-sourced `asr` queue

## Status
- **Priority**: P2
- **Effort**: XS
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Confidence**: HIGH
- **Evidence**: `src/bili_asr/cli/asr.py:104-105` — the store-route `todo` is sliced a second time after the store already applied `LIMIT ?`
- **Planned at**: commit `ff39fd0`, 2026-10-02

## Problem

On the default store route, `bili-asr asr --limit N` applies the bound **twice**:

1. The store applies it: `_store_transcript_todo(args, command="asr")` passes `args.limit` into
   `select_transcript_queue(limit=args.limit)` (`src/bili_asr/cli/_shared.py:210`), which issues
   `LIMIT ?` on the gap view (`src/bili_asr/storage/database.py:1855-1857`).
2. The CLI re-slices: `todo = todo[:args.limit]` (`src/bili_asr/cli/asr.py:104-105`).

Today the second slice is a no-op (it re-slices the already-limited N rows). But it is a live trap: any
future change that makes the store-side limit a per-bvid cap or an over-fetch turns the CLI slice into a
silent row-dropping bug, and today the redundant slice already masks whether the store limit or the CLI
limit owns the bound. The two queue routes disagree — the manifest route applies `--limit` exactly once
(`src/bili_asr/cli/queue.py:278`).

## Current state (excerpt)

`src/bili_asr/cli/asr.py:99-108`:
```python
rows, queue_source, failed = _store_transcript_todo(args, command="asr")
if failed:
    return 1
queue_conn = queue_source.connection
todo = [e for _key, e in rows] if rows else []
if args.limit is not None:
    todo = todo[:args.limit]
if not todo:
    print("asr: queue empty (no parts need transcription)")
```

The `if args.limit is not None: todo = todo[:args.limit]` block is the redundant second application.

## Approach

Drop the `todo[:args.limit]` re-slice in the store branch of `_cmd_asr`. `--limit` is owned by the
queue-source read (the store-side `LIMIT ?`), matching the `download-audio` store branch
(`src/bili_asr/cli/queue.py:330`), which relies solely on `_store_audio_todo`'s limit and does not
re-slice. Do **not** change the manifest-route limit handling (it is correct at `queue.py:278`).

## Files

- **Modify**: `src/bili_asr/cli/asr.py` — remove the `if args.limit is not None: todo = todo[:args.limit]`
  block in the store branch (keep the manifest branch's limit semantics untouched).
- **Test**: `tests/test_cli_queue_source.py` — add the store-route limit assertion below.

## Out of scope

- `src/bili_asr/cli/queue.py` (the manifest route) — its single application is correct; do not touch.
- `src/bili_asr/storage/database.py` — the store-side `LIMIT ?` is the correct owner of the bound; do not
  touch.
- `src/bili_asr/cli/_shared.py` — `_store_transcript_todo` correctly forwards the limit; do not touch.

## Verification gates

- **New test** in `tests/test_cli_queue_source.py`: seed a store-backed `asr` queue with more than N
  candidate rows, invoke the store-route selection with `--limit N`, and assert exactly N rows are read
  (i.e. the store-side bound is the single authority and no second slice changes the count). This test
  passes both before and after (the second slice is currently a no-op), but it pins the single-application
  contract so a future over-fetch cannot silently reintroduce the double application.
  - Run: `python3.12 -m pytest tests/test_cli_queue_source.py -k store_limit -v` → passes.
- Existing queue-source behaviour unchanged:
  - Run: `python3.12 -m pytest tests/test_cli_queue_source.py -q` → the store-vs-manifest route pins
    still pass.

## STOP conditions

- If removing the slice changes any observable row count on the store route today (i.e. the store side was
  *not* actually limiting), STOP — report the store-side limit behaviour you observed before proceeding;
  that would mean the store `LIMIT ?` is not the authority and the fix shape changes.

## Done criteria

- [ ] `python3.12 -m pytest tests/test_cli_queue_source.py -k store_limit -v` passes.
- [ ] `python3.12 -m pytest tests/test_cli_queue_source.py -q` passes.
- [ ] `rg -n 'todo\[:args.limit\]' src/bili_asr/cli/asr.py` → no match in the store branch.
- [ ] `git diff --check -- src/bili_asr/cli/asr.py tests/test_cli_queue_source.py` exits 0.
- [ ] No files outside the Files list are modified.

## Drift check

`git diff --stat ff39fd0..HEAD -- src/bili_asr/cli/asr.py tests/test_cli_queue_source.py` — if either file changed, re-open the excerpt above and confirm the store branch still matches before editing.
