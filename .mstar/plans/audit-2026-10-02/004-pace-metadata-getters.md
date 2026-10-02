# Plan 004 — Pace all three per-row metadata getters (detail / parts / tags)

## Status
- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: perf
- **Confidence**: HIGH
- **Evidence**: `src/bili_asr/services/metadata_ingest.py:336-375` — three sequential unpaced `await` loops per 30-video page; no gateway pacing primitive
- **Planned at**: commit `ff39fd0`, 2026-10-02

## Problem

Full-corpus `fetch-meta` fires **three sequential unpaced upstream calls per video** — detail
(`Video.get_info`), parts (pagelist), and tags — across three `await` loops in `metadata_ingest.py`. With
~30 videos per page that is ~90 sequential round-trips per page, with **zero delay between calls**. This is
the exact load pattern that triggers Bilibili's `-412` risk-control, which terminates the whole enumeration
mid-run and forces a resume from cursor.

Residual **M-R1** registers only the **tag** leg. The identical unpaced per-row shape of the **detail** and
**parts** legs is unregistered. This plan covers all three legs behind one shared pacing mechanism so the
tag leg is not double-planned with M-R1.

## Current state (excerpt)

`src/bili_asr/services/metadata_ingest.py:336-375` (abridged):
```python
for summary in page.videos:
    ... await self._completed_summary(summary, mid)   # detail: one call per video
for summary in summaries:
    ... await self._gateway.get_video_parts(summary.bvid)   # parts: one call per video
for summary in summaries:
    ... await self._gateway.get_video_tags(summary.bvid)    # tags: one call per video
```

The gateway (`src/bili_asr/sources/bilibili_api_gateway.py:722-841`) issues direct `_await_upstream` calls
with only `-412`/`-429`/`-352` classification (`:59-61`) — there is **no** sleep/pacing primitive.

## Approach

Add a single gateway-level pacing decorator/helper, applied to all three getters, with a small fixed delay
+ jitter between calls — mirroring the existing inter-page pacing in `fetch_pages` (the `0.8–1.6 s`
sleep that already exists for the legacy page-fetch path). Sequential execution is fine; the point is the
delay, not concurrency (do **not** add bounded concurrency — `sequential-no-daemon` is by-design).

1. Add a `_pace()` helper on the gateway (or a module-level pacing wrapper) that sleeps a small random
   interval (matching the documented inter-page range) before each upstream call.
2. Apply it inside `get_completed_video_summary`, `get_video_parts`, and `get_video_tags` so all three
   legs pace uniformly.
3. Cross-reference residual M-R1 when closing this plan so the register records that the tag leg is covered
   here (PM action).

## Files

- **Modify**: `src/bili_asr/sources/bilibili_api_gateway.py` — add the pacing helper; apply it to the three
  getters (`:722-841` region).
- **Modify**: `src/bili_asr/services/metadata_ingest.py` — no logic change expected (the pacing lives in the
  gateway), but confirm the three loops call the paced getters; only touch if a call bypasses the gateway.
- **Test**: `tests/test_bilibili_api_gateway.py` — add the pacing assertion below.

## Out of scope

- Adding bounded concurrency / parallelism between calls (`sequential-no-daemon` by design).
- The legacy `fetch_pages` inter-page pacing (already correct; do not change).
- M-R1's register row (PM closes it; this plan covers the code).

## Verification gates

- **Pacing test** in `tests/test_bilibili_api_gateway.py`: drive one full per-page sequence (detail + parts
  + tags for K videos) against a stubbed upstream and assert a pacing sleep is invoked between consecutive
  calls (e.g. patch `time.sleep` / `asyncio.sleep` and assert the call count ≥ the number of upstream calls
  − 1). Assert all three getters are paced, not just tags.
  - Run: `python3.12 -m pytest tests/test_bilibili_api_gateway.py -k pacing -v` → passes.
- Existing gateway behaviour unchanged:
  - Run: `python3.12 -m pytest tests/test_bilibili_api_gateway.py -q` → the shape/classification tests
    still pass (pacing must not break the `-412`/`-429`/`-352` handling).

## STOP conditions

- If applying pacing to the detail/parts legs measurably conflicts with an existing test that asserts an
  exact call count or timing on those legs, STOP — report the test and reconcile before proceeding.
- If the gateway already has a pacing knob you did not see (e.g. a session-level delay), STOP and use it
  rather than adding a second mechanism.

## Done criteria

- [ ] `python3.12 -m pytest tests/test_bilibili_api_gateway.py -k pacing -v` passes.
- [ ] `python3.12 -m pytest tests/test_bilibili_api_gateway.py -q` passes.
- [ ] All three getters (detail, parts, tags) route through the shared pacing helper.
- [ ] `git diff --check -- src/bili_asr/sources/bilibili_api_gateway.py tests/test_bilibili_api_gateway.py` exits 0.
- [ ] No files outside the Files list are modified.

## Drift check

`git diff --stat ff39fd0..HEAD -- src/bili_asr/sources/bilibili_api_gateway.py src/bili_asr/services/metadata_ingest.py tests/test_bilibili_api_gateway.py` — if any in-scope file changed, re-open the excerpt and confirm the three-loop shape is still present.
