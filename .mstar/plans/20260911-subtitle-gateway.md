# Subtitle Gateway and Typed Subtitle Contract

> Iteration: `iter-2026-09-subtitle-transcript-sqlite`.
> Execution mode: `sdd`.
> Findings cleanup: `zero-residual`.

## Status

- Priority: P0 (iteration-critical, serial 1/3: Plans 2–3 consume these DTOs, and the
  secret/no-leak boundary is enforced here; no operator-visible value lands before Plan 3)
- Task category: backend / external integration
- Status: Todo
- Depends on: none (extends the delivered `sources/` boundary)
- Primary spec: `.mstar/iterations/iter-2026-09-subtitle-transcript-sqlite/specs/subtitle-gateway.md`
- Owner: fullstack-dev
- QA gate: mandatory

## Goal

Give the archive one typed, application-owned boundary for AI/CC subtitle acquisition —
track listing plus subtitle-body fetch — so the caption path stops using the raw
`bili_client` HTTP surface and every failure becomes a bounded scalar code, with the signed
subtitle URL and the credential confined to process memory.

**What the operator gets from this plan.** The inventory that `probe-subs` will print is
expressed in application terms — language, display label, and AI vs CC — so the operator can
judge what a part actually exposes before anything is downloaded; and every later failure is
a stable code they can act on (retry later vs. no track visible vs. unusable upstream
response) instead of a raw upstream error. This plan ships no CLI surface of its own: it is
the contract the storage and CLI plans build on, and it is where "never persist or print a
secret" becomes an enforced, tested property.

## Architecture

`sources/models.py` gains `SubtitleTrack` (language, label, is_ai, track_id) and
`SubtitleSegment` (start_ms, end_ms, text) DTOs plus two protocol methods;
`sources/bilibili_api_gateway.py` (the only module importing `bilibili_api`) issues the
WBI-signed player call from the pin's own endpoint description
(`video.API["info"]["get_player_info"]`) with two adapter-owned overrides — `dm=False`
(fabricated device-fingerprint placeholders; the sibling WBI endpoint answered HTTP 412 with
them) and `verify=False` (in the pinned `Api`, `verify=True` only raises locally when no
SESSDATA is configured, which would turn an honest anonymous probe into an exception) — and
with the description's declared parameter set using `bvid` instead of `aid` so no extra
aid-resolution call is paid. It sends **no** `need_login_subtitle` and **no** `w_webid`: neither
is declared for this endpoint in the installed pin. The subtitle body is fetched through the
package transport with `raw=True` and an empty `Credential()` (SESSDATA never reaches the CDN
host).

No-usable-track signalling is per method, as locked by the spec: `get_subtitle_tracks` returns
an **empty tuple** (never `not_found` for an empty inventory), and `fetch_subtitle_segments`
**raises `GatewayNotFound`** (never returns an empty tuple). Both reach the caller as the
`no-subtitle` outcome; credential presence carries the "anonymous probe saw nothing" versus
"authenticated probe saw nothing" distinction at the operator surface.

`fetch_subtitle_segments` resolves the signed URL itself — the URL never crosses the boundary —
by listing once and matching the requested track on `language` + `is_ai` (then `track_id` to
break a tie, `shape_error` when still ambiguous), and it allows exactly **one** additional
listing + fetch pair when the signed-URL fetch fails in the expiry/transport class.
`bili_client` keeps its subtitle methods for the legacy manifest path until the cutover plan
retires that path's use of them (this plan changes nothing outside `sources/` and `tests/`).

## Tech Stack

Python 3.12, `bilibili-api-python==17.4.2` (pin retained), `curl_cffi` transport, pytest,
the existing fake-`bilibili_api` seam.

## Global Constraints

- Only `sources/bilibili_api_gateway.py` imports `bilibili_api`; the AST import-boundary
  test keeps enforcing this.
- Reuse the existing bounded taxonomy (`rate_limited`, `not_found`, `response_error`,
  `transport_error`, `shape_error`) and its mapping style; no new code vocabulary. The two
  subtitle methods extend the not-found API-code set with `{-101}`; the metadata path's mapping
  is unchanged and a test pins that.
- Endpoint mirror: `url`/`method`/`wbi` come from `video.API["info"]["get_player_info"]`;
  `dm` and `verify` are the only overrides, both documented in the adapter docstring; the
  recorded call shape (flags plus the exact parameter set) is asserted by the seam. A pin bump
  that changes the description fails the parity test loudly.
- No invented parameters: `need_login_subtitle` and `w_webid` are not sent on the player call,
  because the installed pin declares neither for that endpoint and the package's own player
  call sends neither.
- Signed `subtitle_url` values, raw subtitle JSON, cookies, and response bodies are
  process-local: never in DTOs, messages, logs, fixtures, or rows. The body fetch uses an empty
  `Credential()` so the API credential never reaches the CDN host.
- `SESSDATA` comes only from `BILI_SESSDATA`/`--sessdata` and stays presence-only in display.
- Segment conversion is `floor(seconds * 1000)` (never `subtitles.json_to_srt`'s `round()`);
  what the call returns satisfies `end_ms > start_ms >= 0` with text non-empty after trimming,
  and the spec's section 3 boundary decides how rows get there: a row that reads but violates
  those bounds, or whose `content` is empty after stripping, is **dropped**; an entry that is not
  readable as a segment at all (non-numeric or non-finite `from`/`to`, absent/`null`/non-string
  `content`, `body` absent/`null`/not an array) is a document-level `shape_error`. A track whose
  `lan` has no non-empty primary subtag is a `shape_error`, because the service derives the
  language family from it.
- Product semantics carried by this boundary: `is_ai` is an operator-visible fact
  (AI-generated vs uploader/human captions) and survives normalization; a track whose
  upstream marker is absent is reported as CC and the docs state that conservative reading;
  a part with no usable track is surfaced so the caller can record honest `no-subtitle`
  evidence — never an empty success and never an unexpected failure.
- Selection preference is not decided here: tracks are returned in upstream order and the
  gateway never picks for the operator (the documented preference lives in the service).
- All tests offline; the opt-in live probe stays bounded and skipped by default.
- No retries beyond the package's bounded `-403` re-sign (the pin's `wbi_retry_times`) and the
  single bounded re-list on a signed-URL expiry failure.

## Interfaces

- Consumes: the existing `Credential` construction, `_await_upstream` mapping, `_BVID_PATTERN`
  and `_require_positive_argument` guards, and the fake seam.
- Produces, for Plans 2 and 3:
  - `sources.models.SubtitleTrack(language, label, is_ai, track_id)`,
  - `sources.models.SubtitleSegment(start_ms, end_ms, text)`,
  - `BilibiliGateway.get_subtitle_tracks(bvid: str, cid: int) -> tuple[SubtitleTrack, ...]`,
    empty tuple when nothing is visible,
  - `BilibiliGateway.fetch_subtitle_segments(track, bvid, cid) -> tuple[SubtitleSegment, ...]`,
    non-empty or `GatewayNotFound`,
  - the adapter implementations and the extended fake seam (`FAKE_PLAYER_ENDPOINT`, scripted
    track lists, scripted bodies, recorded call list).
- Consumed by Plan 2 as data only: `storage` never imports `sources`; the service maps
  `SubtitleSegment` → `storage.models.TranscriptSegmentRecord`.

## Tasks

### Task 1: Subtitle DTOs, protocol methods, and seam extension

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/sources/models.py`
- Modify: `bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py`
- Test: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`

**Interfaces:**
- Consumes: existing DTO/validation style and the fake seam's recorder.
- Produces: frozen `SubtitleTrack` / `SubtitleSegment` with `__post_init__` validation and two
  protocol methods; seam scripting for the player endpoint and subtitle bodies.

- [ ] Add `SubtitleTrack(language, label, is_ai, track_id)` with validation (language/label
      non-empty after trim; primary subtag non-empty; `track_id` a non-empty string or `None`)
      and `SubtitleSegment(start_ms, end_ms, text)` with validation (`start_ms >= 0`,
      `end_ms > start_ms`, text non-empty after trim); keep `work_id` and URLs out of both.
- [ ] Add the two protocol methods; keep the existing four methods' signatures untouched.
- [ ] Extend the seam with `FAKE_PLAYER_ENDPOINT` (a literal mirror of
      `video.API["info"]["get_player_info"]`, `dm: True` included), scripted `subtitles[]`
      payloads, scripted subtitle bodies (absolute and protocol-relative URLs), and a recorded
      call list that captures the flags and parameter set of every issued call; preserve every
      existing exact call-list assertion.
- [ ] Test DTO validation and the seam's new scripting without importing the real package.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_bilibili_api_gateway.py -v`

### Task 2: Adapter subtitle acquisition in the locked call shape

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py`
- Test: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`

**Interfaces:**
- Consumes: the Task-1 DTOs/protocol and the pin's player endpoint description.
- Produces: normalized `SubtitleTrack` tuples (possibly empty) and non-empty
  `SubtitleSegment` tuples with the bounded taxonomy and no URL leakage.

- [ ] Implement `get_subtitle_tracks`: `Api` built from the description's
      `url`/`method`/`wbi` with `dm=False`, `verify=False`, credential attached, params exactly
      `{bvid, cid, isGaiaAvoided: False, web_location: 1315873}`; normalize `lan`/`lan_doc`/AI
      marker into DTOs; return an empty tuple when upstream lists nothing.
- [ ] Implement `fetch_subtitle_segments`: re-list, resolve the track by `language` + `is_ai`
      (`track_id` breaks a tie, ambiguity is `shape_error`, absence is `not_found`), normalize
      protocol-relative URLs to `https:` internally, fetch with
      `Api(url=..., method="GET", wbi=False, dm=False, verify=False, raw=True,
      credential=Credential())`, and convert `from`/`to`/`content` with `floor(seconds*1000)`.
- [ ] Implement the bounded re-list: at most one extra listing + fetch pair on an
      expiry/transport-class body-fetch failure; never on `rate_limited`; no loop.
- [ ] Extend the not-found mapping for the two subtitle methods with `{-101}` while leaving the
      metadata path's mapping untouched.
- [ ] Preserve the taxonomy mapping for every failure path (HTTP statuses, malformed payloads,
      rate control) and keep the endpoint parity tests green: the seam's description must equal
      the installed pin's field for field, and the adapter's only overrides must be `dm`/`verify`.
- [ ] Tests: normalization (AI vs CC, labels, primary-subtag rejection), conversion, every
      drop trigger of the spec's section 3 boundary (inverted/zero-length interval, negative
      start, empty-after-strip `content`) with the surviving rows asserted, every `shape_error`
      trigger (non-numeric/non-finite `from`/`to`, absent/`null`/non-string `content`, `body`
      absent/`null`/not an array, an entry not readable as a segment), each taxonomy row, the
      recorded call shape, the single re-list call list, the `-101` divergence between subtitle
      and metadata paths, the empty-tuple vs `not_found` distinction (an all-degenerate document
      is `not_found`, never `shape_error`), and no-leak scans (URL/cookie sentinels absent from
      DTOs, messages, rows).

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_bilibili_api_gateway.py -v`

### Task 3: Bounded live subtitle probe evidence

**Files:**
- Modify: `bilibili-asr-archive/tests/test_live_metadata_smoke.py` (or a sibling opt-in test)
- Test: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`

**Interfaces:**
- Consumes: the Task-2 adapter and the operator's credential/proxy environment.
- Produces: opt-in live evidence that a real track list is returned and, when a track exists,
  that segments normalize as expected; and a recorded answer to "does the locked call shape
  reach this endpoint".

- [ ] Add an opt-in `BILI_LIVE_SMOKE=1` probe for one `(bvid, cid)` read from the operator's
      archive database (or a fixed public sample when the archive is empty); skip by default,
      loud-fail when opted in without the required environment.
- [ ] Assert only bounded facts (track count, languages, `ai|cc`; segment count and monotonic
      milliseconds) — never print URLs, bodies, or credentials.
- [ ] Record the probe command and the observed outcome in the plan/README for the CLI plan,
      including the bounded code when the endpoint refuses the locked shape.

Run: `cd bilibili-asr-archive && BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_live_metadata_smoke.py -v`

## STOP Conditions

- The player endpoint refuses the locked shape (`dm=False`, `verify=False`, no invented
  parameters) with a risk-control code → stop and escalate with the recorded evidence; do not
  enable the fabricated `dm` fingerprint parameters and do not add undeclared parameters
  (`w_webid`, `need_login_subtitle`) to make the call pass.
- The pinned package cannot reach the player endpoint without a call shape that leaks
  signed URLs or credentials into application DTOs → stop and escalate the contract gap.
- Subtitle acquisition requires playback/audio APIs or a different library → stop; that
  crosses into the next iteration's scope.
- A required normalization rule cannot be satisfied without storing raw JSON → stop and
  update the spec instead of persisting payloads.
- The fake seam cannot mirror the pin's endpoint description without weakening existing
  assertions → stop and report; do not loosen another test to make room.

## Durable Roadmap and Dependencies

- This plan is the acquisition half of the iteration; `20260911-transcript-storage` persists
  what it returns and `20260911-subtitle-cli-cutover` exposes it. No plan claims caption
  coverage on its own, and this plan claims none at all: a returned track list describes what
  the current credential could see for one part at one moment.
- Deferred: retiring `bili_client`'s subtitle methods (only after the CLI cutover plan proves
  the new path); audio/playback APIs stay out of this iteration entirely.
- Deferred with a named owner (`project-manager`, trigger "this iteration delivered"):
  promoting the iteration's durable storage/transport contract out of
  `{ITERATION_DIR}/iter-2026-09-subtitle-transcript-sqlite/specs/` at iteration-close. No file
  is written directly into `{SPECS_DIR}` during Prepare, so the frozen copy is authored once the
  code and tests have confirmed it.

## Drift Check

Before implementing, inspect `src/bili_asr/subtitles.py`, `src/bili_asr/bili_client.py`
(probe/download methods), and the existing fake seam; confirm the new DTOs do not duplicate
`subtitles.pick_subtitle` behaviour (selection stays in the service layer) and that
`subtitles._LAN_PREFERENCE` is not reused anywhere on the new path.

## Acceptance / Done Criteria

- [ ] Subtitle DTOs + two protocol methods exist with validation and are covered offline.
- [ ] The adapter issues the WBI-signed player call in the locked shape (description mirror,
      `dm=False`, `verify=False`, `bvid`-based parameter set) and normalizes tracks/segments per
      the spec, so a probe result distinguishes language, display label, and AI vs CC.
- [ ] A part with no usable track yields an empty tuple from the listing and `not_found` from
      the body fetch — bounded, non-error outcomes the caller records as `no-subtitle`.
- [ ] Every failure maps to a bounded scalar code; no signed URL or credential appears in
      any DTO, message, log, fixture, or row.
- [ ] Offline suite green (baseline recorded at plan open: 903 passed, 2 skipped) including
      the AST import-boundary test and no-leak scans.
- [ ] Opt-in live probe recorded (real track list, or explicit bounded blocker), asserting
      only bounded facts: track count, languages, AI/CC, segment count, monotonic milliseconds.
- [ ] `git diff --check` clean.

## Prepare → Execute Handoff

Execute Task 1 → Task 2 → Task 3 (serial). After all tasks: SDD branch review package,
mandatory QC tri-review (N=3), mandatory QA gate, then merge into the iteration branch.

## Review Gate Summary

- Decision: pending
- Review range / Diff basis: pending
- Review bundle: `.mstar/sdd/20260911-subtitle-gateway/review/`
- QC inputs: `qc1.md`, `qc2.md`, `qc3.md`
- Blocking result: pending
- Residual findings: pending

## QA Gate Summary

- QA gate: mandatory
- QA mode: acceptance
- Evidence: pending

## Sign-off

- Product intent: reviewed (product-manager, 2026-09-11)
- Architecture: reviewed (architect, 2026-09-11)
- Writing/corpus hygiene: reviewed (writing-specialist, 2026-09-11)
- PM lock: pending
- Implementation owner: fullstack-dev
- QA owner: qa-engineer
- Review cleanup: zero-residual

## Plan self-review

1. Every spec requirement maps to a task and an offline assertion.
2. No task depends on raw response dictionaries.
3. The signed-URL/credential boundary is explicit and testable, and the no-track signalling is
   decided per method (empty tuple / `not_found`).
4. The live probe is bounded and has an honest blocker path, including for a refused call shape.
5. Nothing in this plan touches storage, the CLI, or playback/audio APIs.
6. The plan claims a typed contract and bounded evidence only — it claims no caption
   coverage, and its operator-facing facts (language, label, AI vs CC) are the ones the CLI
   later prints.

## Evidence Index

- Primary spec: `.mstar/iterations/iter-2026-09-subtitle-transcript-sqlite/specs/subtitle-gateway.md`
- Tests: `tests/test_bilibili_api_gateway.py`, `tests/test_live_metadata_smoke.py`
- SDD runtime: `.mstar/sdd/20260911-subtitle-gateway/`

## Status Transition

Starts `Todo`; `InProgress` after the Phase 2 lease; `InReview` after implementation;
`Done` only after QC + the mandatory QA gate and the integration merge.

## End

Subtitle acquisition is a transport concern; the DTO and transcript contracts downstream
are what later iterations build on.
