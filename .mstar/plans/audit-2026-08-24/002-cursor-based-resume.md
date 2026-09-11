# Cursor-Based Resumable Metadata Enumeration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `mstar-sdd` (recommended) or inline execution. This audit plan is a candidate for the normal Prepare -> Execute flow; it does not register or execute itself.

**Goal:** Make `fetch-meta --resume` continue from the last unenumerated page after a risk-control stop while preserving already harvested records and an honest terminal summary.

**Architecture:** Keep the JSONL manifest as per-video state SSOT and add a small, durable enumeration checkpoint beside it or in a reserved manifest metadata record. The client exposes the next page/cursor and persists progress after each successful page; retry exhaustion records the failed page and exit 2. Resume reads that checkpoint and starts there, without changing the transport seam or duplicating records.

**Tech Stack:** Python 3.12+, existing `ManifestStore`, `BiliClient`, pytest.

**Execution:** mstar-sdd

## Status
- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `ab3cd97`, 2026-08-24

## Finding and current state

- `BiliClient.fetch_pages()` initializes `pn = 1` on every invocation (`bilibili-asr-archive/src/bili_asr/bili_client.py:357-399`). It exposes `pages_fetched`, but no next-page cursor.
- `_cmd_fetch_meta()` loads existing entries only when `args.resume` is true (`bilibili-asr-archive/src/bili_asr/cli.py:145-154`), then always calls `client.fetch_pages(args.mid, ...)` with no start page (`cli.py:155-156`).
- On retry exhaustion, `_persist_partial()` merges already fetched pages and returns exit 2 (`cli.py:157-168`), but the failed page is only printed; it is not persisted as a resume cursor.
- The spec requires partial progress and resume-safe operation (`.mstar/specs/asr-archive-cli.md:18-22, 93-99,116-120`).

## Interfaces

Preserve:

- `ManifestStore(root, rel_path=...)`
- `ManifestStore.load() -> dict[str, dict[str, Any]]`
- `ManifestStore.upsert(entry) -> dict[str, Any]`
- `BiliClient.fetch_pages(mid, max_pages=None)` compatibility for existing callers

Add an explicit optional cursor interface, for example:

- `BiliClient.fetch_pages(mid: int, max_pages: int | None = None, start_page: int = 1) -> list[list[dict[str, Any]]]`
- a durable checkpoint record or sidecar with `mid`, `next_page`, `total`, `updated_at`, and last terminal code; exact schema must be locked during Prepare.

Do not store cookies, SESSDATA, signed URLs, or raw exception tracebacks in the checkpoint.

## In scope

- `bilibili-asr-archive/src/bili_asr/bili_client.py`
- `bilibili-asr-archive/src/bili_asr/cli.py`
- `bilibili-asr-archive/src/bili_asr/manifest.py` if checkpoint helpers belong there
- `bilibili-asr-archive/tests/test_fetch_meta.py`
- `bilibili-asr-archive/tests/test_manifest.py` if checkpoint persistence is in the store
- `bilibili-asr-archive/README.md` for the exact resume semantics

## Out of scope

- Reworking subtitle/audio/ASR pipeline behavior; media-page identity is a separate concern and is not required by this metadata cursor plan.
- Changing retry limits, backoff values, or risk taxonomy; these are frozen in `.mstar/specs/asr-archive-cli.md:84-93`.
- Full-corpus scheduling, parallel requests, or a database migration.

## Conventions and exemplars

- Atomic persistence follows `ManifestStore.save()` (`manifest.py:59-70`) using a same-directory temporary file and `os.replace`.
- Partial merge behavior follows `_persist_partial()` (`cli.py:128-142`); extend it rather than creating a second merge path.
- Risk summaries must remain actionable but must not echo credentials or signed URLs, matching `cli.py:157-185` and the project security contract.

## Tasks

### Task 1: Persist and consume the enumeration cursor

**Files:** Modify `bilibili-asr-archive/src/bili_asr/bili_client.py`, `cli.py`, `manifest.py` as needed; test `tests/test_fetch_meta.py`, `tests/test_manifest.py`.

- [ ] Define checkpoint ownership and atomic format. It must distinguish different `mid` values and distinguish completed enumeration from a risk-stopped run.
- [ ] Return or expose the next page after each successful response, and persist it after merging that page, not only after a failure.
- [ ] On `RiskBudgetExhausted`, persist the last successful page plus `next_page` and terminal code; preserve exit 2.
- [ ] When `--resume` is supplied, load the checkpoint and start at `next_page`; without `--resume`, start at page 1 and explicitly decide whether stale checkpoint state is replaced.
- [ ] Clear or mark the checkpoint complete when `total` is reached or the configured page limit intentionally ends the run.

Run: `python -m pytest bilibili-asr-archive/tests/test_fetch_meta.py bilibili-asr-archive/tests/test_manifest.py -q` -> all tests pass, including a stop-at-page-2 then resume-at-page-2 scenario.

### Task 2: Document and test idempotency

- [ ] Add a test proving a resumed run does not duplicate JSONL bvid records.
- [ ] Add a test proving an interrupted run keeps the first page and does not claim the failed page was enumerated.
- [ ] Update README workflow text with the checkpoint behavior and the fact that exit 2 is resumable.

Run: `python -m pytest bilibili-asr-archive/tests/test_fetch_meta.py bilibili-asr-archive/tests/test_manifest.py -q` -> exit 0; the new tests assert exact cursor and record counts.

## STOP conditions

- If preserving the cursor requires changing existing manifest rows in a way that breaks older JSONL files, STOP and specify a versioned migration before implementing.
- If `--limit-pages` semantics cannot distinguish intentional stopping from risk interruption, STOP and resolve whether the checkpoint should remain resumable.
- If the client cannot persist after each successful page without coupling HTTP code to filesystem I/O, STOP and redesign around a page iterator/callback at the Prepare gate.

## Drift check

Before execution run:

`git diff --stat ab3cd97..HEAD -- bilibili-asr-archive/src/bili_asr/bili_client.py bilibili-asr-archive/src/bili_asr/cli.py bilibili-asr-archive/src/bili_asr/manifest.py bilibili-asr-archive/tests/test_fetch_meta.py bilibili-asr-archive/tests/test_manifest.py bilibili-asr-archive/README.md`

If any in-scope file changed, compare the cursor and partial-merge excerpts above with live code and STOP on mismatch.

## Done criteria

- [ ] A test demonstrates risk exhaustion on page 2, then a `--resume` invocation begins at page 2.
- [ ] A test demonstrates no duplicate bvid lines after resumption.
- [ ] Checkpoint data contains no cookie, token, signed URL, or raw secret value.
- [ ] `python -m pytest bilibili-asr-archive/tests/test_fetch_meta.py bilibili-asr-archive/tests/test_manifest.py -q` exits 0.
- [ ] `grep -R "start_page\|next_page\|checkpoint" bilibili-asr-archive/src/bili_asr bilibili-asr-archive/tests` finds the documented cursor implementation and tests.
- [ ] `git status --short` shows only in-scope files changed.

## Prepare -> Execute handoff

During Prepare, lock the checkpoint schema, completion/limit semantics, and metadata-only ownership boundary. During Execute, land checkpoint tests alongside the cursor implementation and verify the retry/exit taxonomy remains unchanged.
