# Implementer report — Task 3: Bounded live subtitle probe evidence

- Plan: `20260911-subtitle-gateway` (iteration `iter-2026-09-subtitle-transcript-sqlite`)
- Task: 3 of 3 (SDD, leaf, `Delegation: forbidden` — no subagent dispatched)
- Working branch: `feature/20260911-subtitle-gateway` (feature worktree
  `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-gateway`)
- Base commit: `7f7156acd7ce7b6c421576d209024f3c20f87d9f`
- Commit: `c3d362cbcbbc137b05b7943690c6076640f8cb1b`
  `feat(subtitles): add the bounded live subtitle probe and the Task-2 tightenings`
- Status: **DONE**

## Status rationale

All three brief items and all three PM-authorized tightenings (M1, M2, M4) are
implemented, tested and committed on the working branch. The focused files and
the full offline suite are green with no regression; the M4 coverage pin is
mutation-verified red→green; and the opt-in live probe was executed for real
(operator credential + proxy) and returned the bounded evidence the plan asks
for: the locked call shape **does** reach the player endpoint. No STOP
condition fired, no fingerprint parameter or undeclared parameter was added,
nothing was weakened to make room, and no credential or signed URL reached any
file, DTO, message, or output.

Two things are recorded for the reviewer/PM rather than silently absorbed:

1. **The live fallback is the plan's "fixed public sample", not a live
   discovery.** The first implementation followed the assignment's example
   fallback (discover a part through the delivered metadata gateway for UID
   23191782). Its first live run was refused `rate_limited` **by that metadata
   route**, so the probe never reached the endpoint under test. The plan's own
   wording for this case is "a fixed public sample when the archive is empty";
   the fallback was therefore changed to the constant sample discovered during
   the successful second live run, removing the unrelated live dependency.
   Evidence for both runs is below.
2. **The plan bullet "Record the probe command and the observed outcome in the
   plan/README for the CLI plan"** is only half mine to do: the command lives in
   the probe module's docstring (product file, committed), while the plan /
   CLI-plan README are harness artifacts I must not edit. The observed outcome
   is recorded here for PM to carry into the plan and the CLI plan's README.
   See "Handoff — PM-owned".

## Implemented (brief items)

1. **Opt-in live probe** — new `bilibili-asr-archive/tests/test_live_subtitle_smoke.py`.
   `BILI_LIVE_SMOKE=1` opts in; a default run skips it; an opted-in run
   loud-fails (`pytest.fail` with install guidance) when the pinned
   distribution is absent or unimportable, and also when the adapter module
   cannot be imported.
   The probed `(bvid, cid)` resolves in two steps: the operator's archive
   database first — `BILI_LIVE_ARCHIVE_DB` when set, else `archive/archive.db`
   below the package directory (the `fetch-meta` default root) — opened through
   a `mode=ro` SQLite URI, newest `video_parts` row; then the fixed public
   sample (`SAMPLE_BVID` / `SAMPLE_CID`). A missing, unreadable, or part-less
   database is not a failure. The archive database at the operator path named in
   the assignment (`/root/workspace/bilibili-asr-archive/bilibili-asr-archive/archive/archive.db`)
   **does not exist on this host** (`test -f` → absent; no `archive.db` exists
   anywhere in the control checkout), which is exactly the "archive is empty"
   case the plan's fallback covers.
2. **Bounded assertions and bounded output only** — the run prints and asserts:
   `sessdata=present|absent` (the shipped `redact_sessdata` label),
   `proxy=present|absent`, the part source with its `bvid`/`cid`, `track_count`
   with `language:ai|cc` per track, and `segments` with `first_start_ms`,
   `last_end_ms` and the timeline fact. It never prints a signed URL, a response
   body, a display label, or a credential: the track evidence renderer is
   asserted (offline) to drop label text even when the label carries a URL/body
   sentinel, and the probe never holds a URL at all — `subtitle_url` resolution
   stays inside the adapter.
3. **Recorded outcome and the refusal path** — a `rate_limited` answer is
   recorded as the plan's bounded blocker: the bounded code and the stage are
   printed and the run reports a skip (never a green pass, never a bent call
   shape). A listed track whose document carries nothing usable is printed as
   `segments=not_found` and also reported as a skip, so a run without segment
   evidence cannot read green. Every other bounded code (`transport_error` from
   a dead proxy, `response_error`, `shape_error`) fails loudly, because those
   are environment/adapter defects rather than upstream refusal. An empty
   inventory is a legitimate pass with `track_count=0`, recorded together with
   credential presence — never "this video has no captions".

## Implemented (PM-authorized tightenings)

- **M1 — adapter `video` import narrowed.** `from bilibili_api import
  Credential, request_settings, user, video` became `... user` plus
  `from bilibili_api.video import API as VIDEO_API, Video`; the two
  `video.Video(...)` call sites now use `Video(...)` and the player endpoint
  description is `VIDEO_API["info"]["get_player_info"]`. Binding the module can
  no longer make `Episode`, `VideoOnlineMonitor`, `get_api`, `get_cid_info` or
  `get_client` source-reachable. `ALLOWED_PACKAGE_IMPORTS` stays an **exact
  equality** and now records `"bilibili_api.video": {"API", "Video"}`
  (the AST check records the imported attribute name; the local alias
  `VIDEO_API` is documented in the constant's comment and the test docstring,
  and keeps the endpoint description visually apart from the `Api` request
  class). Only the three comments/docstrings that described the old shape were
  updated. This reverses the Task-2 commit's recorded consequence ("the adapter
  imports the `video` module from the package root (like `user`)"), as the
  review asked.
- **M2 — `download` back in `FORBIDDEN_SEAM_METHOD_TOKENS`.** The tuple is now
  `playback, playurl, play_url, download, danmaku, audio, asr, export`;
  `AUTHORIZED_SEAM_METHOD_TOKENS` is `("subtitle", "player")`, so the positive
  control still proves the authorized removal is load-bearing (all three
  asserted attributes carry `subtitle`). This iteration acquires no media, and a
  future `get_download_url` in the adapter is caught again.
- **M4 — the fetch's own initial-listing transport failure pinned.** New
  parametrized test
  `test_fetch_subtitle_segments_maps_a_transport_failure_on_its_own_listing`
  (`FakeNetworkException(503)` and a non-package `RuntimeError`): the mapped
  code is `transport_error`, `detail == "fetch_subtitle_segments"`, upstream
  text absent from the message, and the exact call list is **one** listing — the
  bounded re-list is never armed by a listing that never answered.

## Tests

Focused (`cd bilibili-asr-archive && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest …`):

```
tests/test_bilibili_api_gateway.py -q      →  308 passed, 1 skipped in 1.15s
tests/test_live_subtitle_smoke.py -q       →  7 passed, 1 skipped in 0.15s
                                              (the skip is the opt-in live probe)
```

Full offline suite:

```
$ python -m pytest -q
1082 passed, 3 skipped in 43.31s
```

Baseline before this task: 1073 passed, 2 skipped. Delta = +9 passed
(+2 from M4's two parameters, +7 new offline rehearsals), +1 skip (the opt-in
live probe), 0 failures. No existing test was weakened, renamed, or removed;
`git diff --check` is clean.

### Red → green evidence (M4, mutation-verified)

The M4 behaviour was already correct, so the test was proven load-bearing by
mutation: the adapter's initial listing was temporarily moved inside the
re-list `try` block (backup taken and restored; the mutation was never
committed):

```
mutation applied: initial listing moved inside the re-list try block
FAILED test_fetch_subtitle_segments_maps_a_transport_failure_on_its_own_listing[listing_failure0]
FAILED test_fetch_subtitle_segments_maps_a_transport_failure_on_its_own_listing[listing_failure1]
2 failed, 307 deselected in 0.47s
E  AssertionError: assert ['player.trac…J, cid=2222)'] == ['player.trac…J, cid=2222)']
E    Left contains one more item: 'player.track_list(bvid=BV1AbCdEfGhJ, cid=2222)'
--- mutation reverted ---
2 passed, 307 deselected in 0.38s
```

### Offline rehearsal coverage of the probe's own logic

The probe module carries seven offline rehearsals that run in every default
`pytest` run and make no network call:

| Rehearsal | What it pins |
|---|---|
| `test_archive_part_selection_reads_the_shipped_schema_and_stays_read_only` | the `(bvid, cid)` query runs against a database the **real storage layer** created, and the connection URI is pinned to `?mode=ro` (recorded by a `sqlite3.connect` wrapper); missing and part-less databases answer `None` |
| `test_probe_part_selection_prefers_the_archive_and_falls_back_to_the_sample` | the archived part wins; without one the fixed sample answers — and the fallback needs no live call at all |
| `test_probe_part_selection_ignores_an_archive_without_a_part` | a schema-present, part-less archive (the pre-collection shape) falls through to the sample instead of failing |
| `test_missing_pinned_distribution_fails_loudly` | the opted-in loud-fail guard |
| `test_live_smoke_switch_is_opt_in` | only the literal `1` opts in (`""`, `0`, `true`, `yes`, `2` do not) |
| `test_track_evidence_carries_counts_languages_and_ai_cc_only` | the evidence line is exactly `track_count=2 tracks=ai-zh:ai,zh-CN:cc` even when the labels carry a signed-URL/raw-body sentinel — labels are never printed |
| `test_segment_evidence_requires_a_non_decreasing_timeline` | the timeline assertion passes for a forward document and raises for an unordered one and for an empty one |

## Live probe evidence

Environment: run **from the worktree package dir** with the control
interpreter, the operator credential sourced from the control checkout's `.env`
(value never echoed, never copied into the worktree, never written anywhere) and
`BILI_HTTP_PROXY=http://127.0.0.1:7890`. Command (single live attempt, then one
cooldown retry, as authorized):

```
cd /root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-gateway/bilibili-asr-archive
BILI_LIVE_SMOKE=1 /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python \
    -m pytest tests/test_live_subtitle_smoke.py -v -s
```

**(a) First attempt — bounded blocker, recorded honestly.** With the original
discovery-based fallback:

```
tests/test_live_subtitle_smoke.py::test_live_subtitle_probe_reports_one_real_part_inventory
live subtitle probe environment: sessdata=present proxy=present
live subtitle probe evidence: part_source=none stage=part-discovery refusal_code=rate_limited
SKIPPED
```

That refusal came from the **arc/search metadata route** the fallback used, not
from the player endpoint; the endpoint under test was never reached. Per the
plan's STOP-condition discipline nothing was bent to make the call pass, and the
cooldown retry (~120 s) was used.

**(b) Second attempt — real evidence.** Same command; the discovery call
succeeded and returned the sample part, which is now the pinned constant:

```
live subtitle probe environment: sessdata=present proxy=present
live subtitle probe part: source=sample-discovery bvid=BV1S8hA6MEvy cid=41314223900
live subtitle probe evidence: stage=track-listing track_count=1 tracks=ai-zh:ai
live subtitle probe evidence: stage=subtitle-body track=ai-zh:ai segments=2913 first_start_ms=460 last_end_ms=7896020 timeline=non-decreasing
PASSED
```

**(c) Definitive run after the fallback was simplified** (same part, no metadata
call — the shipped implementation):

```
live subtitle probe environment: sessdata=present proxy=present
live subtitle probe part: source=fixed-sample bvid=BV1S8hA6MEvy cid=41314223900
live subtitle probe evidence: stage=track-listing track_count=1 tracks=ai-zh:ai
live subtitle probe evidence: stage=subtitle-body track=ai-zh:ai segments=2913 first_start_ms=460 last_end_ms=7896020 timeline=non-decreasing
PASSED
```

Bounded reading of the evidence:

- **Part source**: not the archive database (absent on this host, see above);
  the fixed public sample `BV1S8hA6MEvy` / cid `41314223900`, discovered through
  the delivered metadata gateway during run (b) — a public part of the archive
  owner's own collection. Both identifiers are public; the report carries no
  signed URL and no credential.
- **Track list**: `track_count=1`, one track, language `ai-zh`, classified **AI**
  (`tracks=ai-zh:ai`) — so the inventory is non-empty and `is_ai` discriminates
  as the spec promises. No CC track was listed for this part at this moment.
- **Body**: 2913 segments normalized; `first_start_ms=460`,
  `last_end_ms=7896020` (≈ 2 h 11 m 36 s, a plausible length for the source
  lecture); the start timeline is non-decreasing; every segment satisfied the
  DTO invariant `end_ms > start_ms >= 0` with non-empty trimmed text (enforced by
  `SubtitleSegment` and covered offline).
- **Exit outcome**: `1 passed` for the live test — no bounded blocker on the
  endpoint under test.
- **Answer to the plan's question**: the locked call shape (`dm=False`,
  `verify=False`, `{bvid, cid, isGaiaAvoided: False, web_location: 1315873}`, no
  `need_login_subtitle`, no `w_webid`) **reaches the player endpoint**, and the
  signed document it lists is fetchable through the package transport with the
  empty credential. No STOP condition was triggered.
- **Bounded blocker recorded**: the run (a) `rate_limited` refusal of the
  *metadata* discovery route — upstream risk control on that route, not on this
  plan's endpoint; it is recorded here and drove the fallback simplification
  rather than any change to the locked contract.
- **Honest limit of the evidence** (per the spec's product semantics): one part,
  one moment, one credential. It is not a caption-coverage claim.

No archive database, sidecar, fixture, or any other file was created or
modified by the live runs (`git status` after the runs: only the three committed
product files).

## Files changed

| File | Change |
|---|---|
| `bilibili-asr-archive/tests/test_live_subtitle_smoke.py` | **new** (+535): opt-in bounded live probe, bounded-evidence renderers, read-only archive part selection, and seven offline rehearsals |
| `bilibili-asr-archive/tests/test_bilibili_api_gateway.py` | M2 (`download` back in `FORBIDDEN_SEAM_METHOD_TOKENS`, authorized tokens narrowed), M1's `ALLOWED_PACKAGE_IMPORTS` equality + the three comments/docstrings that described the old import shape, M4's focused test (+75 / −30) |
| `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py` | M1 only: narrowed `video` import, `Video(...)` at the two call sites, `VIDEO_API` for the player endpoint description, comment recording the rationale (+9 / −4) |

`tests/test_live_metadata_smoke.py` was deliberately **not** modified: the brief
allowed "a sibling opt-in test", and that module's docstring claims no subtitle
code is invoked — adding one there would have falsified its stated boundary.

## Self-review notes

- **`git diff --check`**: clean (checked before commit, re-checked after).
- **No assertion weakened**: the diff removes/alters nothing that was asserted
  before except the two token constants M2 explicitly authorizes and the
  `ALLOWED_PACKAGE_IMPORTS` entry M1 explicitly authorizes; the exact-equality
  semantics of both stay (`assert imports == ALLOWED_PACKAGE_IMPORTS`, exact
  forbidden-token scan with its two positive controls). The M2 change makes the
  scan *stricter*, never looser. Every pre-existing call-list assertion in the
  seam tests is untouched.
- **No credential/URL anywhere**: a full-tree scan for the credential value
  (read from the environment, never printed) over every non-`.git` file → **0
  hits**; the only `.env*` file in the worktree is the pre-existing tracked
  `.env.example`; no `archive.db`/`*.sqlite` exists in the tree; the new probe
  file contains no URL, no `subtitle_url`, and no upstream payload text (it
  carries only counts, codes, milliseconds and the two public sample
  identifiers). Nothing in the live run persisted anything.
- **No live behaviour in the offline path**: the probe's live test is skipped
  without `BILI_LIVE_SMOKE=1`, the seven rehearsals use only the storage layer,
  the seam scripted double, and DTOs, and no test module import touches the
  network.
- **`simplify:` / `temporary` markers**: none introduced.
- **Deliberate design decisions recorded** (for the L2 reviewer to confirm):
  - the segment-timeline assertion is a bounded fact *about one document*. The
    spec preserves upstream order verbatim, so a violation would mean upstream
    sent an unordered document; the assertion's failure message says exactly
    that, and it is checked live (non-decreasing for the probed part). Its
    purpose is to make "monotonic milliseconds" a real check rather than a
    printed claim.
  - a `not_found` body on a listed track is a **skip**, not a pass: a run
    without segment evidence must not read green.
  - the `rate_limited` refusal path records and skips instead of failing, so a
    risk-control refusal is not misread as an adapter defect — while the skip
    message names the STOP condition and forbids bending the call shape.
- **Observation, not acted on** (outside M1's authorized scope): the `user`
  module import is still bound whole (`user.API`, `user.User`,
  `user.VideoOrder`), which is the same class of looseness M1 removed for
  `video`. Flagged for the reviewer; changing it was not authorized by M1 and
  would touch a second surface in the same commit.
- **No scope creep**: nothing outside `sources/bilibili_api_gateway.py` and the
  two test modules changed; no spec, plan, snapshot, status, compass, or
  iteration artifact was written; no push, no branch mutation, no harness
  artifact in the commit (verified: `git show --name-only` lists exactly the
  three product files).

## Handoff — PM-owned (not done by me)

1. Carry the probe command and the observed outcome (this report's "Live probe
   evidence") into the plan's Task-3 checkbox and the CLI plan's README; both are
   harness/next-plan artifacts outside this assignment's write boundary.
2. The locked contract needs no change: no STOP condition fired. The only
   recorded bounded blocker is the metadata discovery route's `rate_limited`
   refusal (run (a)), which the shipped probe no longer depends on.
3. If the fixed sample is ever removed upstream, the evidence line names the
   probed `bvid`/`cid` and the module documents that replacing the two constants
   is a one-line change.

## Boundary compliance

- Leaf executor: no subagent/task dispatched; all work done in this session.
- Writes: only the three product files inside the feature worktree plus this
  report. No plan/snapshot/status/compass/spec/iteration artifact touched.
- Git: one commit on `feature/20260911-subtitle-gateway`
  (`c3d362cbcbbc137b05b7943690c6076640f8cb1b`); no push; `main` and the
  integration branch untouched; working tree clean.
- Credential handling: presence-only statements throughout (`sessdata=present`);
  the value was loaded from the control checkout's `.env` into the probe
  process, never echoed, printed, copied into the worktree, or persisted.
