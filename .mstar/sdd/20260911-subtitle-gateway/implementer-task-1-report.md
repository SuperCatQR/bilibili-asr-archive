# Implementer report — Task 1: Subtitle DTOs, protocol methods, and seam extension

- Plan: `20260911-subtitle-gateway` (iteration `iter-2026-09-subtitle-transcript-sqlite`)
- Task: 1 of 3 (SDD, leaf, `Delegation: forbidden` — no subagent dispatched)
- Working branch: `feature/20260911-subtitle-gateway` (feature worktree
  `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-gateway`)
- Base commit: `2bd333f0da7edbdb40c0b331a6f456c13f3d1167`
- Commit: `73fdef0093bfdb0b9f51e9d44e7b4c2fd1e7583e`
  `feat(subtitles): add the subtitle DTOs, protocol methods, and the player seam`
- Status: **DONE_WITH_CONCERNS**

## Status rationale

The task's deliverables are implemented, tested and committed; the full offline
suite is green with no regression. **DONE_WITH_CONCERNS** is for one
spec/plan-text conflict that Task 2 would otherwise copy verbatim (F1 below),
plus two disclosed boundary decisions (F2, F3). None of them blocks Task 2, and
none of them was reachable by editing files inside this task's authority (the
specs/plans are harness artifacts I must not write).

## Implemented

1. **`SubtitleTrack` / `SubtitleSegment` DTOs** (`src/bili_asr/sources/models.py`),
   frozen + slots, `__post_init__` validation in the shipped DTO style
   (`_text` / `_integer` helpers, no new helper names):
   - `SubtitleTrack(language, label, is_ai, track_id)`: `language`/`label`
     non-empty; `language` must carry a non-empty primary subtag
     (`split("-", 1)[0].strip()`, so `-zh` is rejected); `is_ai` boolean;
     `track_id` a non-empty string or `None`. No `work_id` and no URL field —
     the field set is pinned exactly by a test.
   - `SubtitleSegment(start_ms, end_ms, text)`: `start_ms >= 0`,
     `end_ms >= 1` and `end_ms > start_ms`, `text` non-empty after stripping.
   - Locked field order matches the spec §2 code block exactly.

2. **Protocol methods** on `BilibiliGateway` (verbatim spec §2 signatures):
   `get_subtitle_tracks(bvid, cid) -> tuple[SubtitleTrack, ...]` and
   `fetch_subtitle_segments(track, bvid, cid) -> tuple[SubtitleSegment, ...]`,
   each carrying the locked signalling contract as an in-place comment (empty
   tuple = observation, never `not_found`; body fetch = `GatewayNotFound`,
   never an empty success). The shipped four signatures are untouched, pinned
   by a new exact whole-surface test. `__all__` extended.

3. **Fake seam extension** (`tests/fixtures/fake_bilibili_gateway.py`):
   - `FAKE_PLAYER_ENDPOINT`: literal mirror of
     `video.API["info"]["get_player_info"]` (`dm: True` included; query fields
     under `data`), exposed by the fake package at the same path and readable
     as `script.player_endpoint` so a test can rewrite it.
   - Scripted player payload: `script.player_response` / `script.player_error`
     (plain value or callable receiving the requested `bvid`/`cid`), plus
     `make_player_response(*tracks)` / `make_subtitle_track(**overrides)`.
   - Scripted signed documents: `script.subtitle_bodies` keyed by URL (plain
     document, `BaseException` to raise, or callable receiving the URL), with
     an unscripted URL failing loudly; `make_subtitle_document(*rows)` /
     `make_subtitle_entry(**overrides)`. Both URL forms ship:
     `SIGNED_SUBTITLE_URL_MARKER` (absolute) and
     `PROTOCOL_RELATIVE_SUBTITLE_URL` (protocol-relative).
   - Recorded call list: `script.api_requests` now records **every** issued
     `Api` request in issue order — `url`/`method`/`verify`/`wbi`/`dm`,
     the exact parameter set (with the package's `dm_*` injection mirrored when
     `dm` is on), the `raw` request argument, and `has_sessdata` (presence
     only, never the credential value). `script.calls` gains one exact token
     per route: `player.track_list(bvid=…, cid=…)` and `subtitle.body`.
   - Seam `Api` fidelity: `request(raw=False, byte=False)` with `result` as
     `request()` (the pin's shape). `raw` is **not** a constructor argument —
     a parity test compares the double's constructor fields and `request`
     signature against the installed pin, so the seam cannot accept a call the
     pin would reject. `byte=True` fails loudly (no download surface).
   - `SIGNED_SUBTITLE_URL_MARKER` joined `NO_LEAK_MARKERS`, so a leaked
     `subtitle_url` is caught by the shipped scanner; all seam tracks are
     scripted with it.

4. **Tests** (`tests/test_bilibili_api_gateway.py`, 43 new test cases):
   DTO field-set pin, 14 `SubtitleTrack` rejections, nullable `track_id`,
   region/script subtag acceptance, 13 `SubtitleSegment` rejections,
   frozenness, the locked six-method protocol surface, and 11 seam tests
   (player description exposure + identity, player call recording with SESSDATA
   presence, changed-description routing, `dm` fingerprint-injection positive
   control, scripted body answer, scripted transport failure, unscripted URL
   loud failure with the protocol-relative form, `raw` mirroring both ways,
   the `Api` no-more-permissive-than-the-pin parity, the player mirror parity
   against the installed distribution, and the no-leak scanner control).
   The DTO and seam-scripting tests import neither the real package nor the
   adapter (`build_fake_package` is driven directly).

## Tests

Focused (Task 1 gate command, control interpreter because the worktree has no
`.venv`):

```
cd .worktrees/20260911-subtitle-gateway/bilibili-asr-archive
/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python \
  -m pytest tests/test_bilibili_api_gateway.py -q
```

- Baseline before the change: `136 passed, 1 skipped in 0.99s`
- Red (tests first, before any implementation):
  `ImportError: cannot import name 'SubtitleSegment' from 'bili_asr.sources.models'`
  — collection error, 1 error in 0.30s
- Green after implementation: `179 passed, 1 skipped in 1.30s`
- New-case selection: `-k "subtitle or player or seam or protocol"` →
  `43 passed, 137 deselected`; every new test id was confirmed PASSED in a
  `-v` run (e.g. `test_fake_api_double_is_no_more_permissive_than_the_pin`,
  `test_fake_player_endpoint_mirror_matches_the_installed_pinned_description`).

Full offline suite (before commit, same interpreter):

```
/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest -q
946 passed, 2 skipped in 54.14s
```

Baseline recorded at plan open was `903 passed, 2 skipped`; the delta is
exactly the 43 new cases, with no existing test changed in outcome.

Additional (throwaway, **not committed**) seam-sufficiency probe: scripted
`player_response` as a per-call sequence plus a scripted failing document,
driven through the seam's `Api` by hand. Result — the exact four-call sequence
`["player.track_list(bvid=…, cid=2222)", "subtitle.body", "player.track_list(…)",
"subtitle.body"]` with `raw == [False, True, False, True]`, i.e. the bounded
re-list of spec §4 is scriptable and exactly assertable with this seam.

## Files changed (only the three files in the task's file list)

- `bilibili-asr-archive/src/bili_asr/sources/models.py` (+67)
- `bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py` (+232/−35)
- `bilibili-asr-archive/tests/test_bilibili_api_gateway.py` (+555)

## Self-review notes

- `git diff --check` clean (both against the worktree and `HEAD~1..HEAD`);
  working tree clean after the commit; nothing committed outside the working
  branch; no push; no harness artifact written other than this report.
- **No assertion weakened.** The only change to an existing assertion is
  `_public_names(modules["bilibili_api.video"]) == ["Video"]` →
  `== ["API", "Video"]` (the seam's documented surface genuinely grows by the
  endpoint description; the assertion stays exact equality) — required by the
  brief's "seam gets a literal mirror of `video.API["info"]["get_player_info"]`"
  and by spec §10's STOP rule read as "do not loosen". Every exact call-list
  assertion (`script.calls == [...]`) is untouched; the deleted lines in the
  fixture are the rewrites of two docstrings and the page-route body that moved
  into `_user_video_page_result()` with identical recorded values and token.
- Routing is now explicit instead of "any URL is the page call": the page and
  player routes answer at the scripted description URL or the literal mirror,
  a signed-document fetch requires `raw=True`, and anything else fails loudly.
  This replaces silent wrong answers with loud seam errors; the whole suite
  (including `test_metadata_ingest.py`, `test_metadata_e2e.py`,
  `test_metadata_cli.py`, `test_live_metadata_smoke.py`, which all use this
  fixture) stays green.
- Import boundary untouched: only `sources/bilibili_api_gateway.py` imports
  `bilibili_api`; `models.py` and the seam stay import-safe (the AST test is
  green and unmodified).
- No credentials, signed URLs, or raw bodies in the new DTOs, messages, or
  factories: the DTO field sets are pinned to exclude any URL; the fixture's
  signed URL is a fake sentinel that is now itself a no-leak marker.
- Drift check (plan §Drift Check): `subtitles.pick_subtitle` selection is not
  duplicated (selection stays in the service) and `subtitles._LAN_PREFERENCE`
  is not referenced on the new path; the new DTOs carry no `work_id`.
- Naming: new names were checked with the `naming-analyzer` skill (locked spec
  names kept verbatim; new seam names are full words, route-paired, and
  unambiguous: `FAKE_PLAYER_ENDPOINT`/`player_endpoint`, `player_response`,
  `subtitle_bodies`, `player.track_list`, `subtitle.body`, `has_sessdata`).

## Findings for the next tasks (zero-residual)

- **F1 (spec/plan text vs installed pin — Task 2 must not copy verbatim).**
  Spec §1.3 and plan Task 2 write the document fetch as
  `Api(url=…, method="GET", wbi=False, dm=False, verify=False, raw=True)`. In
  the installed pin `Api` is a dataclass whose fields are
  `url, method, comment, wbi, dm, verify, no_csrf, json_body, ignore_code,
  sign, data, params, files, headers, credential` — **`raw` is not a
  constructor field**; it is `Api.request(raw: bool = False, byte: bool = False)`
  (`Api.result` calls `request()` with no arguments, so it cannot carry
  `raw=True`). The realizable locked shape is
  `await Api(url=<signed url>, method="GET", wbi=False, dm=False,
  verify=False, credential=Credential()).request(raw=True)`.
  Consequence: the spec's *intent* (raw subdocument fetch, empty credential) is
  unchanged; only the call expression differs. The seam does **not** paper over
  this — it mirrors the pin, and a new parity test fails if the double ever
  accepts `raw`/`byte` at construction. Recommend the PM record this wording
  correction before Task 2 is dispatched (Task 1 has no authority to edit
  specs/plans). *Not* a STOP condition: the targeted endpoint, the parameter
  set, and the taxonomy are unaffected.
- **F2 (deliberate scope boundary).** `src/bili_asr/sources/__init__.py`
  re-exports "the application-owned DTOs", but the new DTOs are **not** added
  there: the task's file list is exactly three files, and spec §2 names
  `bili_asr.sources.models`. Consumers can import
  `from bili_asr.sources.models import SubtitleTrack` (the shipped service
  already imports from the module, not the package root). If Plans 2–3 want the
  package-root re-export, it is a four-line additive change owned by that task.
- **F3 (deliberate, for Task 2 to decide).** `DOCUMENTED_METADATA_CALLS` still
  lists only `space.arc.search` / `video.get_info` / `video.get_pages`, and
  `FakeGateway` (the protocol double used by ingestor tests) was **not**
  extended with the two subtitle methods. Neither breaks: the protocol is not
  `runtime_checkable`, no test asserts the double satisfies it, and no existing
  test needs a subtitle double. Task 1 therefore added no speculative stub; the
  consuming task extends the double and the documented-call set where it
  actually scripts subtitle calls (tokens are `player.track_list(...)` and
  `subtitle.body`).
- **F4 (handoff note).** Seam capabilities Task 2 can rely on, all covered by
  Task-1 tests: `script.player_response` may be a callable `(bvid, cid)` for a
  per-call listing sequence; `script.subtitle_bodies` values may be exceptions
  or callables for a fail-then-succeed document; `script.calls` gives one exact
  token per issued request and `script.api_requests` the full shape
  (`raw`, `has_sessdata`) — the bounded re-list assertion of spec §4 is
  `== ["player.track_list(bvid=…, cid=…)", "subtitle.body",
  "player.track_list(bvid=…, cid=…)", "subtitle.body"]`.
