# Implementer report — Task 2: Adapter subtitle acquisition in the locked call shape

- Plan: `20260911-subtitle-gateway` (iteration `iter-2026-09-subtitle-transcript-sqlite`)
- Task: 2 of 3 (SDD, leaf, `Delegation: forbidden` — no subagent dispatched)
- Working branch: `feature/20260911-subtitle-gateway` (feature worktree
  `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-gateway`)
- Base commit: `73fdef0093bfdb0b9f51e9d44e7b4c2fd1e7583e`
- Commit: `7f7156acd7ce7b6c421576d209024f3c20f87d9f`
  `feat(subtitles): implement the adapter subtitle calls in the locked shape`
- Status: **DONE_WITH_CONCERNS**

## Status rationale

Every brief item, including all seven PM-authorized test/contract updates, is
implemented, tested and committed on the working branch; the focused file and
the full offline suite are green with no regression, and the new guards are
mutation-verified (18/18). **DONE_WITH_CONCERNS** is for one contract edit that
the lock *requires* but the authorized checklist does not enumerate — the
adapter's package import surface (`ALLOWED_PACKAGE_IMPORTS`) had to gain the
`video` module (C1) — plus the interpretation notes in C2 that the L2 reviewer
should confirm against the spec's wording. No gate is blocked, no STOP
condition fired, and nothing was weakened to make room.

## Implemented (brief items)

1. **`get_subtitle_tracks(bvid, cid)`** — validates `bvid` with `_BVID_PATTERN`
   and `cid` with `_require_positive_argument` before any call, then issues one
   player call through `_fetch_subtitle_inventory`: `Api` built from
   `_PLAYER_INFO_ENDPOINT = video.API["info"]["get_player_info"]`'s
   `url`/`method`/`wbi`, with the adapter-owned overrides `dm=False`,
   `verify=False`, the caller's credential, and `.update_params(bvid=…, cid=…,
   isGaiaAvoided=False, web_location=1315873)`. No `need_login_subtitle`, no
   `w_webid`. Entries normalize into trimmed `SubtitleTrack` DTOs; an empty or
   missing inventory returns an **empty tuple**.
2. **`fetch_subtitle_segments(track, bvid, cid)`** — re-lists the part
   (`_list_subtitle_entries`, one call), resolves the requested track by
   `language` + `is_ai` (`track_id` breaks a tie; still-ambiguous is
   `shape_error`; no candidate is `not_found`), normalizes a protocol-relative
   `subtitle_url` to `https:` internally, fetches it with
   `Api(url=…, method="GET", wbi=False, dm=False, verify=False,
   credential=Credential())` called as `.request(raw=True)`, and converts rows
   with `floor(seconds * 1000)`.
3. **Bounded re-list** — `except GatewayTransportError:` unrolls exactly one
   extra listing + fetch pair (no loop, no third attempt); `rate_limited` and
   every other class propagate without re-listing. Nothing usable — empty
   `body` or every row dropped — raises `GatewayNotFound`; the return is never
   an empty tuple.
4. **`{-101}` taxonomy extension** — `_SUBTITLE_NOT_FOUND_API_CODES =
   _NOT_FOUND_API_CODES | {-101}` is passed by the two subtitle methods only;
   `_await_upstream` takes it as a keyword-only `not_found_api_codes:
   frozenset[int] = _NOT_FOUND_API_CODES`, so the metadata path's mapping is
   byte-identical.
5. **Taxonomy + parity preserved** — every failure path yields the shipped
   bounded scalar code; the seam's description still equals the installed pin's
   field for field, and the adapter's only overrides are `dm`/`verify`
   (asserted on the recorded call).
6. **Tests** — 127 new cases (focused file 180 → 307). See the coverage table
   below.

## Implemented (PM-authorized test/contract updates)

| # | Authorized item | Where | Done |
|---|---|---|---|
| 1 | `FORBIDDEN_SEAM_METHOD_TOKENS`: remove only `subtitle`/`player`/`download`; keep `playback`/`playurl`/`play_url`/`danmaku`/`audio`/`asr`/`export`; positively assert the authorized surface | `tests/test_bilibili_api_gateway.py` | yes — added `AUTHORIZED_SEAM_METHOD_TOKENS` + `AUTHORIZED_SUBTITLE_ATTRIBUTES` and a two-part positive control (names present **and** each carries a removed token, so re-forbidding them fails) |
| 2 | Extend `DOCUMENTED_METADATA_CALLS` with `player.track_list`, `subtitle.body`, keeping it an exact set | `tests/fixtures/fake_bilibili_gateway.py` | yes — exact five-route tuple; a new test pins the tuple verbatim, exercises the shipped guard on the real subtitle call list, and proves it still rejects an undocumented route |
| 3 | Add the protocol-relative subtitle-URL form to `NO_LEAK_MARKERS` | fixture | yes — `PROTOCOL_RELATIVE_SUBTITLE_URL` added; the scanner control test now asserts both forms are caught and both are members |
| 4 | Strengthen `test_gateway_protocol_surface_is_locked` to an exact method set; correct the over-claiming docstring | test file | yes — the declared map is now built from `vars(BilibiliGateway)` public members (a seventh method fails), docstring rewritten |
| 5 | Re-export `SubtitleTrack`/`SubtitleSegment` from `sources/__init__.py`, adapter still un-re-exported | `src/bili_asr/sources/__init__.py` | yes — import + `__all__`, plus a test asserting both re-exports and `not hasattr(sources, "BilibiliApiGateway")` |
| 6 | Pin the locked no-track signalling executably | test file | yes — empty inventory → `()`; empty/all-degenerate document → `GatewayNotFound` with `.code == "not_found"` and an assignment guard that can only stay `None` if no empty tuple was returned |
| 7 | Trim `language`/`label` and segment `text` in the adapter | adapter | yes — `.strip()` at normalization; pinned by the whitespace-wrapped normalization case and the `"  未明子  "` segment |

Additionally (not in the checklist, disclosed as C1): the adapter now imports
the `video` module from the package root — the same pattern the page path uses
for `user` — instead of `bilibili_api.video.Video`, because the locked
requirement is to read the transport fields from
`video.API["info"]["get_player_info"]`. `ALLOWED_PACKAGE_IMPORTS` was updated to
`{"bilibili_api": {"Credential", "request_settings", "user", "video"}}` with the
`bilibili_api.video` entry dropped; the comparison is still exact equality and
the five exception names plus `utils.network.Api` are unchanged.

## Tests

Focused (Task-2 gate command; the feature worktree has no `.venv`, so the
control interpreter is used):

```
cd .worktrees/20260911-subtitle-gateway/bilibili-asr-archive
/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python \
  -m pytest tests/test_bilibili_api_gateway.py -v
```

- Focused baseline (Task-1 handoff): `179 passed, 1 skipped`
- Red before the authorized updates (adapter implemented, pre-update contract):
  `2 failed, 177 passed, 1 skipped` —
  `test_gateway_imports_stay_on_metadata_surface` (the new `video` import) and
  `test_gateway_source_never_names_forbidden_seam_methods` (the subtitle
  attributes). Both are exactly the two contract updates the brief authorizes
  (the first as C1).
- Green after the adapter + tests: `306 passed, 1 skipped in 1.00s`
- Full offline suite before commit:

```
/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest -q
1073 passed, 2 skipped in 48.81s
```

Baseline for this task was `946 passed, 2 skipped`; the delta is exactly the 127
new cases (focused file 180 → 307 collected), no existing test changed outcome,
and the two skips are the unchanged opt-in live smokes.

Coverage (spec → new test):

| Requirement | Test(s) |
|---|---|
| Track normalization, AI vs CC, labels, trimming, order | `test_get_subtitle_tracks_normalizes_ai_and_cc_tracks`, `test_get_subtitle_tracks_reads_the_upstream_ai_markers` (9 cases) |
| Malformed AI marker / track id rejected, never coerced | `test_get_subtitle_tracks_rejects_a_malformed_ai_marker` (7), `…_rejects_a_malformed_track_identity` (5), `…_accepts_a_missing_track_identity`, `…_reads_the_optional_track_identity` |
| Primary-subtag rejection, empty `lan`/`lan_doc`, non-mapping entry | `test_get_subtitle_tracks_rejects_an_unreadable_inventory` (18 cases) |
| Empty/missing inventory → empty tuple (never `not_found`) | `test_get_subtitle_tracks_returns_an_empty_tuple_for_an_empty_inventory` (6) |
| Locked listing call shape (params set, `dm`, `verify`, `wbi`, `raw`, credential) + no invented parameters | `test_subtitle_listing_request_carries_the_locked_call_shape` |
| Description-driven transport + only-`dm`/`verify` overrides vs the pin | `test_subtitle_listing_follows_a_changed_package_endpoint`, `test_adapter_overrides_only_dm_and_verify_of_the_installed_pinned_player_endpoint` |
| Spec §5 taxonomy, subtitle listing | `test_subtitle_listing_failures_map_onto_bounded_taxonomy` (14) |
| `-101` divergence subtitle vs metadata | `test_not_logged_in_diverges_between_the_metadata_and_subtitle_paths` (+ the shipped metadata `-101` case) |
| Conversion, order, unknown keys, every drop trigger (zero-length/inverted/negative/empty-after-strip) with surviving rows asserted | `test_fetch_subtitle_segments_normalizes_the_document_and_drops_degenerate_rows` |
| Every `shape_error` trigger (non-numeric/non-finite/overflow `from`/`to`, absent-null-non-string `content`, `body` absent/`null`/not-an-array, entry not a segment) | `test_fetch_subtitle_segments_rejects_an_unreadable_document` (25) |
| Locked document call shape (`raw=True`, empty credential, `has_sessdata`) | `test_subtitle_document_request_carries_the_locked_transport_shape` |
| Protocol-relative URL normalized internally | `test_fetch_subtitle_segments_normalizes_a_protocol_relative_document_url` |
| Resolution by `language`+`is_ai`, tie-break by `track_id`, ambiguity, absence | `…_resolves_the_requested_track_by_identity`, `…_reports_an_ambiguous_listing` (2), `…_reports_a_track_that_is_not_visible`, `…_reads_not_logged_in_as_no_visible_track` |
| Empty tuple vs `not_found` (all-degenerate is `not_found`, never `shape_error`, never an empty success) | `test_fetch_subtitle_segments_signals_not_found_when_nothing_survives` |
| Single bounded re-list, its exact call list, no loop, never on `rate_limited` | `test_subtitle_document_failures_stay_bounded_and_never_loop` (9), `test_fetch_subtitle_segments_relists_for_a_fresh_signed_url` |
| Documented-call surface (exact set + guard non-vacuity) | `test_the_documented_call_allow_list_carries_exactly_the_authorized_routes`, `test_the_subtitle_routes_stay_on_the_documented_call_surface` |
| No-leak scans (DTOs, messages) + scanner controls | `test_subtitle_dtos_never_leak_the_signed_url_or_the_credential` (in the listing test), `test_subtitle_failure_messages_never_carry_the_upstream_text_or_the_url`, `test_the_subtitle_url_sentinel_is_scanned_like_every_other_secret` |
| Argument rejection before any call | `test_get_subtitle_tracks_rejects_invalid_arguments` (6), `test_fetch_subtitle_segments_rejects_invalid_arguments` (7) |
| Contract updates 4 and 5 | `test_gateway_protocol_surface_is_locked`, `test_sources_package_reexports_the_subtitle_dtos_only` |

### Non-vacuity evidence (mutation check, throwaway driver, not committed)

Each production rule was broken in isolation and the covering test re-run; the
driver restored every file and verified a sha256 match afterwards. 18/18
mutations were caught:

| Mutation | Caught by |
|---|---|
| player `verify` reverted to the pin's `True` | parity override test (1 failed) |
| player `dm` reverted to the pin's `True` | locked-call-shape test (1 failed) |
| invented `web_location=0` | locked-call-shape test (1 failed) |
| protocol-relative URL not normalized | protocol-relative test (1 failed) |
| body fetch carries the API credential | transport-shape test (1 failed) |
| re-list class changed to `GatewayRateLimited` | bound test (6 failed) |
| `{-101}` removed from the subtitle set | divergence + taxonomy (2 failed) |
| metadata path given the extended set | metadata taxonomy + divergence (2 failed) |
| empty result returned instead of `not_found` | nothing-survives test (1 failed) |
| `language`/`label` no longer trimmed | normalization test (1 failed) |
| `track_id` tie-break removed | identity resolution test (1 failed) |
| AI marker narrowed to `ai_status == 1` | marker parametrization (3 failed) |
| non-finite/overflow millisecond guard removed | unreadable-document cases (3 failed) |
| drop rules removed | drops test (1 failed) |
| seventh protocol method added | protocol-surface test (1 failed) |
| `subtitle.body` removed from the allow-list | allow-list + documented-surface (2 failed) |
| protocol-relative sentinel removed from `NO_LEAK_MARKERS` | sentinel control (1 failed) |
| `subtitle` re-forbidden | forbidden-token test (1 failed) |

Red-before-green for the tests themselves: the implementation was written first
in this task, so the red evidence is (a) the two contract failures above (the
adapter was red against the pre-update test file) and (b) the mutation table,
which shows each guard fails when its rule is broken. No test was observed
passing for the wrong reason.

## Files changed (4; commit `7f7156a`)

- `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py` (+386/−7):
  module docstring (signed-URL boundary), `video` root import,
  `_SUBTITLE_NOT_FOUND_API_CODES`, `_PLAYER_INFO_ENDPOINT`, ten pure normalizer
  helpers, the two public methods, `_fetch_subtitle_inventory`,
  `_list_subtitle_entries`, `_fetch_subtitle_document`, and the
  `not_found_api_codes` parameter on `_await_upstream`.
- `bilibili-asr-archive/src/bili_asr/sources/__init__.py` (+4): re-export the two
  DTOs; the adapter stays an explicit import.
- `bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py` (+20/−6):
  `DOCUMENTED_METADATA_CALLS` + `player.track_list`/`subtitle.body`,
  `PROTOCOL_RELATIVE_SUBTITLE_URL` in `NO_LEAK_MARKERS`, two docstring updates.
- `bilibili-asr-archive/tests/test_bilibili_api_gateway.py` (+983/−18): the 127
  new cases, the four contract updates, and the new test helpers
  (`_load_subtitle_gateway`, `_seam_track`, `_listing_call`, `_subtitle_row`,
  `SECOND_SUBTITLE_URL`).

## Self-review notes

- `git diff --check` clean; working tree clean after the commit; committed only
  on `feature/20260911-subtitle-gateway`; no push; the only harness file written
  is this report.
- **Assertion disclosure** (every changed/added/removed assertion):
  - *Changed (4).* (1) `ALLOWED_PACKAGE_IMPORTS`: `video` added to the package
    root, `bilibili_api.video: {"Video"}` dropped; still exact equality (C1).
    (2) `FORBIDDEN_SEAM_METHOD_TOKENS`: exactly `subtitle`/`player`/`download`
    removed, the other seven kept, offset by the new positive control.
    (3) `test_gateway_protocol_surface_is_locked`: the declared map now comes
    from `vars(BilibiliGateway)` instead of the expected-name loop — strictly
    stronger (an extra method now fails); docstring corrected.
    (4) `test_the_subtitle_url_sentinel_is_scanned_like_every_other_secret`:
    extended with the protocol-relative sentinel and both membership checks.
  - *Removed*: none. No existing assertion was deleted or loosened; the
    `-101`/`dm`/`verify`/call-list/parity guarantees are all still asserted at
    least as strictly as before (the metadata `-101 → response_error` case is
    still in the shipped taxonomy parametrization).
  - *Added*: 127 cases, listed in the coverage table.
- **No-leak boundary.** DTOs, mapped error `str`/`repr`, and the gateway `repr`
  are scanned with the shipped scanner (both subtitle URL forms now sentinels)
  plus the SESSDATA sentinel; the persisted-row scan (`persisted_row_text` +
  `assert_leaks_no_markers`) is unchanged and green, and now also covers the
  relative-form sentinel. Subtitles have no persisted rows *yet* — the gateway
  writes none, and `20260911-transcript-storage` owns that surface — so a
  subtitle-row no-leak assertion is deliberately out of this task's scope and
  belongs to Plan 2 (recorded here as a boundary note, not a deferred finding).
- **Task-1 finding F3 disposition.** `FakeGateway` (the protocol double used by
  ingestor tests) still carries only the four metadata methods. This task tests
  the real adapter against the package seam, so extending the double here would
  be speculative; the authorized checklist names only the call allow-list. The
  consuming task that scripts subtitle calls through the protocol double
  (service/CLI plans) extends it then.
- **Drift check.** `subtitles.pick_subtitle`/`_LAN_PREFERENCE` are not reused or
  duplicated (the fetch resolves an identity the caller already chose, it never
  ranks languages); the new path touches no `bili_client` code.
- **Naming.** `naming-analyzer` was loaded before the new names were introduced;
  every new name is a verb-plus-noun mirroring the shipped style
  (`_extract_subtitle_entries` beside `_extract_page_items`,
  `_normalize_subtitle_track(s)`/`_normalize_subtitle_document` beside
  `_normalize_video_part_item`/`_normalize_video_parts`,
  `_fetch_subtitle_inventory` beside `_fetch_user_video_page`,
  `_PLAYER_INFO_ENDPOINT` beside `_USER_VIDEO_PAGE_ENDPOINT`,
  `_SUBTITLE_NOT_FOUND_API_CODES` beside `_NOT_FOUND_API_CODES`).
- **Cost model.** A happy `fetch_subtitle_segments` costs one listing + one body
  fetch; with the caller's own listing that is the spec §4 "two listing calls
  per part". Worst case per fetch is 2 listings + 2 body fetches, asserted by
  exact call lists.

## Concerns

- **C1 (needs PM confirmation; not a blocker).** The adapter's import surface
  had to change to satisfy the locked requirement "`url`/`method`/`wbi` are read
  from `video.API["info"]["get_player_info"]`": `video` is now imported from the
  package root (exactly as `user` already is) and `bilibili_api.video.Video` is
  no longer a separate import; `ALLOWED_PACKAGE_IMPORTS` was updated
  accordingly. This is a contract edit outside the enumerated authorized list,
  so it is disclosed rather than assumed: the allow-list is still compared by
  exact equality, no new module or name family became reachable, and the page
  path is unaffected. If the PM prefers a different import shape (e.g.
  `from bilibili_api.video import API as …`), it is a two-line change.
- **C2 (interpretations the reviewer should confirm against the spec text).**
  (a) The re-list trigger is `GatewayTransportError` only — "expiry/transport
  class" — so a CDN HTTP 404 (shipped mapping → `not_found`) and every
  non-transport class propagate without re-listing; rate control never re-lists.
  (b) `is_ai = ai_status > 0 or type == 1`, and the `lan` prefix is deliberately
  not consulted, so `ai-zh` with no marker reports CC (the spec's conservative
  reading); a present-but-non-integer marker is a `shape_error`, not a silent
  `False`. (c) `track_id` is read from the upstream integer `id` (`id_str` is
  not read, the spec names `id`); the tie-break only applies when the request
  carries a `track_id`, because a null identity cannot disambiguate. (d) A
  finite `from`/`to` whose millisecond product leaves the float range (e.g.
  `1e308`) is a `shape_error`, so `math.floor` can never escape as
  `OverflowError`/`ValueError` (a bounded strengthening of the spec's
  non-finite rule). (e) `subtitle`/`subtitles` absent or `null` is an empty
  inventory (empty tuple); a present container of another shape is a
  `shape_error`.
