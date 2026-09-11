---
report_kind: qc
reviewer: qc-specialist-2
reviewer_index: 2
plan_id: "20260911-subtitle-gateway"
verdict: "Approve"
generated_at: "2026-09-11"
---

# Code Review Report

## Reviewer Metadata

- Reviewer: @qc-specialist-2
- Runtime Agent ID: qc-specialist-2
- Runtime Model: dsh host session — the concrete model route is not exposed to this seat
- Review Perspective: correctness of the upstream interaction (pin call shape + transport), error
  handling / taxonomy, and test non-vacuity across the whole branch
- Report Timestamp: 2026-09-11T14:20:00+08:00

## Scope

- plan_id: 20260911-subtitle-gateway
- Review range / Diff basis: `2bd333f..6002f99` (base = the iteration integration branch at feature
  cut; 4 commits)
- Working branch (verified): `feature/20260911-subtitle-gateway`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-gateway`
- Files reviewed: 6 (`src/bili_asr/sources/__init__.py`, `src/bili_asr/sources/models.py`,
  `src/bili_asr/sources/bilibili_api_gateway.py`, `tests/fixtures/fake_bilibili_gateway.py`,
  `tests/test_bilibili_api_gateway.py`, `tests/test_live_subtitle_smoke.py`) — +3172/−59, exactly the
  plan's declared scope (no file outside `sources/` and `tests/`; no harness artifact rides along)
- Commit range (identical to Review range): `2bd333f..6002f99` — `73fdef0`, `7f7156a`, `c3d362c`,
  `6002f99`; `git diff --name-status` = 5 × M + 1 × A (the new probe module)
- Analysis methods: `git diff` / `git show` / `git diff --check` / `rev-list` (read-only plumbing),
  `read`, `grep`, and read-only inspection of the installed pin
  (`bilibili_api/data/api/video.json`, `utils/network.py` — `Api` fields, `_prepare_request`,
  `_process_response`, `Credential.__init__`/`get_cookies`) — **no test, build, lint or typecheck run,
  no live network, no git mutation**
- Deep review: triggered (S1 — +3172 changed lines; S6 — `sources/` + `tests/` + `tests/fixtures/`
  boundaries). Lenses applied: Correctness Lens, Security Lens, Bounds Lens, Real-Entry-Path Lens,
  plus a Testing-Lens non-vacuity pass
- Discipline: `BILI_LIVE_SMOKE` and `BILI_LIVE_ARCHIVE_DB` observed `<unset>`; no credential file
  sourced, no credential value read or echoed; `git status --porcelain` empty before and after

## Findings

### 🔴 Critical

None.

### 🟡 Warning

None.

### 🟢 Suggestion

- **[QC2-001] `specs/subtitle-gateway.md` §4.3 still reads as if *every* non-200 signed-URL status
  arms the bounded re-list, while §5 (and the shipped code) route HTTP 404 to `not_found` with no
  re-list — add the one-line clarification §5 already carries implicitly.**
  - Source Type: deep-lens: Correctness Lens (documentation/contract drift, not a code defect)
  - Verification: diff/read anchor — spec §4.3 (`…/specs/subtitle-gateway.md:227-230`: "only for the
    expiry/transport class (HTTP status != 200 on the signed URL, i.e. a signature that no longer
    works)") vs §5's two rows (`:257` "Signed-URL fetch HTTP status != 200 → `transport_error` after
    the single bounded re-list" and `:254` "`-404`, `-62002`, HTTP `404` → `not_found` | shipped
    shared mapping"); code `bilibili_api_gateway.py:615-625` catches `GatewayTransportError` only, and
    the shared mapper (`:797-808`) sends HTTP 404 to `GatewayNotFound` first; test
    `tests/test_bilibili_api_gateway.py:2939` pins it (`FakeNetworkException(404) → GatewayNotFound`,
    `attempts=1`, with the comment "A document that is not there is not an expiry").
  - Expected vs observed: expected — a downstream reader of §4.3 alone would assume a 404 body fetch
    re-lists; observed — it does not (and cannot, because the shared mapper claims the status first).
    Consequence is bounded and already PM-settled: the task-2 L2 review raised this as C2a and the PM
    disposition is "§5's explicit table governs §4.3's loose parenthetical" (progress.md:101-102), so
    the shipped behaviour is **confirmed compliant**; only the §4.3 prose lags. Recorded at Suggestion
    level because Plans 2–3 derive the caller's `failed`-vs-`no-subtitle` mapping from this table and
    a §4.3-only reading would mis-derive the retry class. Precedent for such a fix exists in this
    branch (the dated M5 trim clarification, spec `:289-292`).
  - Confidence: High (divergence), impact Low
- **[QC2-002] No offline assertion pins the cancellation contract of `_await_upstream`'s
  `except Exception` catch-all — one `CancelledError` case would make the "no unexpected failure"
  guarantee non-vacuous.**
  - Source Type: deep-lens: Correctness Lens / Testing Lens (coverage gap)
  - Verification: grep anchor — `tests/test_bilibili_api_gateway.py` contains no
    `CancelledError`/`BaseException` assertion (grep for both returns nothing); the seam already
    accepts one (`fake_bilibili_gateway.py:301-307`, `player_error: BaseException | None`, and
    `subtitle_bodies` "a `BaseException` to raise"), so the rehearsal is a two-line test. Behaviour
    today is **correct**: `_await_upstream` (`bilibili_api_gateway.py:815-816`) catches `Exception`,
    and `asyncio.CancelledError` derives from `BaseException` (Py 3.12), so cancellation propagates
    unmapped — and nothing in the branch catches `BaseException`.
  - Expected vs observed: expected — the property "a cancelled call is never rewritten into a
    `transport_error`" is asserted; observed — it holds by language semantics but would not fail any
    test if a future edit widened the catch-all. This function *is* in the branch's diff (the new
    `not_found_api_codes` keyword), so the gap is in scope; cheap to close.
  - Confidence: High (gap), Low (urgency)
- **[QC2-003] The plan body's `Status: Todo` is stale against the workflow snapshot's `InReview`, and
  the Review Gate Summary is still `pending` — PM bookkeeping to refresh when the tri-review
  consolidates.**
  - Source Type: read (plan vs snapshot)
  - Verification: `read` anchor — `.mstar/plans/20260911-subtitle-gateway.md:12` (`- Status: Todo`)
    and `:312-319` (Review Gate Summary all `pending`) vs
    `.mstar/workflows/iter-2026-09-subtitle-transcript-sqlite/snapshot.json:11-24`
    (`"status": "InReview"`, `progress: 100`, the four task commits), and `progress.md:158`
    ("plan QC tri next").
  - Expected vs observed: expected — the plan's mirrored Status matches the SSOT snapshot at gate
    time; observed — it still reads `Todo`. Documentation only; the Acceptance boxes (`:293-305`) are
    correctly still open for the PM/QA gate. No residual, no action owed by QC.
  - Confidence: High

### ⚪ Unconfirmed

None. Every finding above is anchored in the diff/worktree or the read-only pin source; the
runtime-only items the L1/L2 reports carry forward are listed under Summary as
`Needs L4/QA verification` (the Assignment-mandated QA gate owns them) and are **not** review
findings, because no review evidence channel failed.

## Focus-area assessments (Assignment items 1–4)

### 1. Upstream interaction

Verified against the installed pin itself, not against the seam's claim about it:

- **Endpoint mirror is literal.** `python -c json.load(data/api/video.json)` for
  `info.get_player_info` equals `FAKE_PLAYER_ENDPOINT` field for field (`url`
  `https://api.bilibili.com/x/player/wbi/v2`, `method GET`, `verify true`, `wbi true`, `dm true`,
  `data {aid, cid, ep_id, isGaiaAvoided, web_location}`, the Chinese `comment`) — read independently
  here, matching `test_fake_player_endpoint_mirror_matches_the_installed_pinned_description`
  (`tests/test_bilibili_api_gateway.py:2141-2170`), which `pytest.fail`s (never skips) if the pin is
  absent (`_require_installed`, `:263-272`).
- **Declared-parameter set.** `_fetch_subtitle_inventory`
  (`bilibili_api_gateway.py:695-711`) reads `url`/`method`/`wbi` from the description and sends
  exactly `{bvid, cid, isGaiaAvoided: False, web_location: 1315873}` — `bvid` substituted for the
  declared `aid` alternative (the pin's own helper pays an extra `__get_aid()` call), `ep_id`
  omitted as bangumi-only, and neither folklore parameter sent. Independently confirmed: `grep -rn
  need_login_subtitle` over the pin returns nothing, and `w_webid` occurs only in
  `data/api/user.json`/`user.py`, never in `video.json`. `verify=False` is the adapter's and is
  justified by the pin (`utils/network.py:2217-2218`: `verify` only calls
  `credential.raise_for_no_sessdata()` locally), while cookies still flow from
  `credential.get_cookies()` (`:2243`), so a configured SESSDATA still reaches the API host —
  exactly the spec's §1.2 claim.
- **Body fetch.** `_fetch_subtitle_document` (`:741-751`) builds
  `Api(url=…, method="GET", wbi=False, dm=False, verify=False, credential=Credential())` and calls
  `.request(raw=True)`. Independent pin checks: `raw`/`byte` are `Api.request` parameters, not
  constructor fields, and `Api.result()` calls `request()` bare (`:2352-2391`); `_process_response`
  returns the parsed document untouched when `raw=True` and would raise `ResponseCodeException(-1,
  "API 返回数据未含 code 字段")` otherwise (`:2295-2306`) — which is precisely how the seam mirrors it
  (`fake_bilibili_gateway.py:518-520`). **SESSDATA cannot reach the CDN host**: `Credential()` does
  *not* read the environment (`utils/network.py:1182-1189`: `sessdata=None` when the argument is
  None) and `get_cookies()` then emits `"SESSDATA": ""` — an empty value, no credential.
- **Protocol-relative normalization** (`:374-388`) matches the shipped legacy semantics
  (`bili_client.py:575-577`, `"https:" + url` for a `//` value) and the negative control
  (`test_fake_subtitle_document_call_rejects_an_unscripted_url`, `:2048-2075`) proves an
  un-normalized fetch lands on an unscripted URL and fails loudly.
- **Bounded re-list.** `fetch_subtitle_segments` (`:607-628`) keeps the fetch's own initial listing
  *outside* the `try`, and the single retry pair fires only on `GatewayTransportError` — so
  `rate_limited` (412/429/`-412`/`WbiRetryTimesExceedException`) and `not_found` (404) propagate
  without re-listing, and a shape error is never re-fetched. Worst case is 2 listings + 2 fetches,
  pinned by an exact call list (`:2945-2967`, `:2970-3009`).
- No retry of the adapter's own on the listing path: the pin's loop re-signs only `-403` up to
  `wbi_retry_times` (`:2352-2389`), which is the spec's §1.2 statement verbatim.

### 2. Error handling

- **Taxonomy rows.** Every §5 row is reachable and mapped (`_await_upstream`, `:795-816`): HTTP
  412/429 → `rate_limited`, HTTP 404 → `not_found`, other non-200 → `transport_error`;
  `-412/-352/-799` → `rate_limited`, `-404/-62002` (+`-101` for the subtitle calls only) →
  `not_found`, other envelopes → `response_error`; `WbiRetryTimesExceedException` → `rate_limited`;
  any other `Exception` → `transport_error`. The only row whose §4.3 prose and §5 row disagree is the
  signed-URL HTTP 404 (QC2-001).
- **`-101` divergence is real and two-directional.** `_SUBTITLE_NOT_FOUND_API_CODES` (`:65`) is used
  *only* by `_list_subtitle_entries` (`:727`); the metadata path keeps the shipped two-code default
  (`:783`). Removing the parameter would fail the metadata half of
  `test_not_logged_in_diverges_between_the_metadata_and_subtitle_paths` (`:2613-2635`); applying it
  globally would fail the subtitle half. The metadata mapping is otherwise byte-identical (the diff
  changes exactly one token on the `if exc.code in …` line).
- **Raise-vs-drop boundary is exact.** A readable-but-useless row drops (`:429-431` returns `None`);
  an unreadable entry raises (`:421-427`, `:434-449`); the document level distinguishes "empty /
  all-degenerate" (`not_found`, `:626-627`) from "unreadable" (`shape_error`, `:399-403`).
  `bool` is excluded from `from`/`to` and from the AI markers, `NaN`/`Infinity` and a finite value
  whose millisecond product overflows the float range are all `shape_error` before `math.floor` can
  escape as `OverflowError`/`ValueError` — the Bounds Lens check the spec calls out.
- **No empty success.** `if not segments: raise GatewayNotFound(...)` (`:626-627`) is the only exit
  besides a non-empty tuple; `return None` is unreachable on any success path.
- **`CancelledError` / `BaseException` preserved** — see QC2-002 (behaviour correct, coverage gap).

### 3. Test non-vacuity (independent, from the diff — no suite run)

An independently derived census of the whole branch's deltas first:

- **Exactly one removed line in the branch contains `assert`**: the fixture-surface line
  `assert _public_names(modules["bilibili_api.video"]) == ["Video"]`, replaced by
  `== ["API", "Video"]` (`tests/test_bilibili_api_gateway.py:1791`) — an *exact-set* assertion over
  the authorized superset, i.e. equal-or-stricter, not a loosening. Assert counts rise in every
  changed file: `test_bilibili_api_gateway.py` 156 → 299, `fake_bilibili_gateway.py` 13 → 14,
  `test_live_subtitle_smoke.py` 0 → 49.
- All 21 code-like removed lines in `tests/` are accounted for: 4 relocated/strengthened
  (`DOCUMENTED_METADATA_CALLS` extended to an exact 5-tuple; the seam's inline
  `script.calls.append(...)` replaced by `_record(...)`, which *also* captures the request flags and
  parameter set; `{"Video"}` → `{"API","Video"}`; the assertion above), 2 replaced by
  `self.params`-based equivalents (strictly more faithful), and the rest docstring/comment prose.
  **0 assertions deleted, 0 loosened.**
- The one guard-*configuration* change is the PM-authorized removal of `subtitle`/`player` from
  `FORBIDDEN_SEAM_METHOD_TOKENS` (`:295-304`), and it is compensated, not silent: `download` is back
  (M2), `AUTHORIZED_SUBTITLE_ATTRIBUTES` are positively asserted present *and* asserted to carry one
  of the removed tokens (`test_gateway_source_never_names_forbidden_seam_methods`, `:1738-1781`), so
  re-adding either token fails the test. The AST allow-list stays exact equality with `video`
  narrowed to `{API, Video}` (M1).

Revert-fails-a-test check for each high-value guard (test file A = `tests/test_bilibili_api_gateway.py`,
B = `tests/test_live_subtitle_smoke.py`):

| Guard | Pinned by | Revert → fails? |
|---|---|---|
| `dm=False` / `verify=False` overrides | A:2495-2528 (flags + `dm_*` absence), A:2545-2572 (against the pin's own `verify/dm = true`) | Yes — flip either and the recorded flag/param assertions fail; A:1959-1990 is the positive control proving the seam really injects `dm_*` |
| Locked parameter set | A:2518-2523 (exact dict equality) | Yes — any added parameter (`need_login_subtitle`, `w_webid`, `aid`) fails equality |
| Empty credential on the CDN fetch | A:2700-2705 (`[has_sessdata…] == [True, False]`, listing built with `SESSDATA_BOUNDARY_VALUE`) | Yes, both directions — reusing `self._credential` records `True`; dropping the credential from the listing records `False` |
| `request(raw=True)` | A:2699; seam rejection at fixture:518-520; A:2078-2110 | Yes — without `raw` the seam (like the pin) answers `ResponseCodeException(-1)` → `response_error` |
| Exactly one extra listing+fetch pair | A:2945-2967 (`calls == [...] * attempts`), A:2970-3009 (exact URL order incl. the fresh URL) | Yes — a third attempt, a re-list on `rate_limited`, or a stale-URL reuse each fail |
| Initial listing outside the re-list (M4) | A:2845-2867 | Yes — moving it inside the `try` yields 2 listing+fetch pairs |
| `-101` divergence | A:2613-2635 + the taxonomy row A:2589 | Yes, both directions (see §2) |
| Drop vs raise | A:2641-2675 (exact surviving tuple with every drop trigger interleaved), A:2903-2923 (26 unreadable documents → `shape_error`, no second fetch), A:3012-3045 (empty/all-degenerate → `not_found`, `returned is None`) | Yes — each direction has an exact expectation |
| Trimming | A:2280-2305 (`"  ai-zh  "` → `"ai-zh"`, trimmed label, `"  未明子  "` → `"未明子"`) | Yes |
| Never an empty success | A:3012-3045 (`returned is None`) + adapter `:626-627` | Yes |
| Fix wave: listing `not_found` → bounded evidence + skip | B:830-859 param `[listing-not-found]` (evidence substring, skip substring, `calls == ["get_subtitle_tracks"]`) | Yes — reverting to propagation makes `pytest.raises(pytest.skip.Exception)` fail (**this also answers focus item 4**; the implementer's mutation table records exactly 1 failing case) |
| `gone` filter on the archive query | B:556-600 | Yes — `video_part_id` ordering alone returns the gone cid 3333 |
| `bvid` shape check on the selected row | B:603-634 | Yes — the foreign row would be returned and then hit the adapter's `ValueError` |
| No-leak scan | A:2173-2194 (positive controls raise), A:3072-3112, B:861-882 (sentinels planted in a track *label*, so printing labels would leak) | Yes |

### 4. The fix wave's authorized behaviour change (strictness)

Judged **correct and adequately strict**, independently of the L2 revalidation:

- The new `except GatewayNotFound` in `_probe_one_part` (B:351-370) catches exactly one class; the
  five taxonomy classes are siblings under `GatewayError` (`sources/models.py:200-227`, read here), so
  `transport_error`, `response_error` and `shape_error` still propagate out of the probe unreached by
  any handler — no attribute, no `except Exception`, no bare `except`. The change therefore *adds* a
  recorded outcome where the probe previously died with an uncaught traceback; it removes no loudness.
- It stays non-green: both new branches `pytest.skip`, and the printed evidence names the part source,
  the stage and the bounded code.
- Residual looseness (accepted, documented, not a finding): a listing `not_found` that is really "the
  credential stopped working" (`-101`) now reads as a skip rather than a loud failure; the printed
  `sessdata=present|absent` line and the skip text naming both causes are the mitigation, and this is
  the spec's own caller-side mapping. Also note the deliberate asymmetry — an obtained-but-empty
  listing (`track_count=0`) still passes with evidence (B:375-382), while a listing that *errored*
  (`not_found`) skips; the module docstring (B:31-62) states both, and "no listing evidence was
  obtained" is a defensible line between them. I concur with the L2 disposition, and flag for the QA
  gate that `-101`-under-a-stale-credential is not distinguishable in this record.

### 5. L2 findings re-judged, and residual R1

- Task 1/2/3 all `Approved` (0 Critical / 0 Important; Minors dispositioned). Re-judging the
  material L2 items from source rather than from the reports: C2b (a present-but-non-integer AI
  marker is `shape_error`, never a silent `False`) and C2e (`subtitle`/`subtitles` absent or `null`
  is an empty inventory; a container of another shape is `shape_error`) are consistent with the
  shipped metadata path's "reject, never coerce" rule and with §3/§5; C2a is PM-settled and I concur
  (my QC2-001 is editorial only); C1/M1 (narrow the `video` import) is visible and verified in the
  diff (`from bilibili_api.video import API as VIDEO_API, Video`, `ALLOWED_PACKAGE_IMPORTS` exact);
  M2/M4 are present (`download` re-forbidden; the initial-listing transport test). No L2 call is
  under-rated, and I found no plan-level blocker they missed.
- **Residual R1 — agree with `severity: low` + `decision: defer`.** `from bilibili_api import
  Credential, request_settings, user` (`:26`) binds the whole `user` module, so a future
  `user.get_api`/`user.API[...]` use could reach another endpoint description without a
  forbidden-token hit; the exact-set import test *blesses* the module by design, so it cannot catch
  that. It is guard strength, not a live defect: the adapter's only `user` uses today are
  `user.API["info"]["video"]` (`:75`) and `user.User(...).get_access_id()` (`:768-770`), both
  delivered and reviewed in the previous iteration, and tightening them is outside this plan's
  authorization (the plan's Drift Check/surgical rule). The register entry carries the required
  owner (`@project-manager`) and target (`20260911-subtitle-cli-cutover`), and the plan's Durable
  Roadmap carries the matching line (`plan:274-277`), so the deferral is traceable rather than
  dropped. One condition to preserve: if that CLI plan is descoped, R1 must be re-targeted rather
  than silently closed.

## Source Trace

- Finding ID: QC2-001
- Source Type: deep-lens: Correctness Lens (contract/documentation drift)
- Source Reference: `specs/subtitle-gateway.md:227-230` vs `:254` + `:257`; `bilibili_api_gateway.py:615-625`,
  `:797-808`; `tests/test_bilibili_api_gateway.py:2939`; `progress.md:101-102` (PM disposition C2a)
- Confidence: High (divergence) / Low (impact)

- Finding ID: QC2-002
- Source Type: deep-lens: Testing Lens (coverage gap)
- Source Reference: `bilibili_api_gateway.py:795-816` (the `except Exception` catch-all touched by this
  diff); no `CancelledError`/`BaseException` assertion anywhere in
  `tests/test_bilibili_api_gateway.py` (grep); seam support at `tests/fixtures/fake_bilibili_gateway.py:301-307`
- Confidence: High (gap) / Low (urgency)

- Finding ID: QC2-003
- Source Type: read (plan/snapshot drift)
- Source Reference: `.mstar/plans/20260911-subtitle-gateway.md:12`, `:312-319` vs
  `.mstar/workflows/iter-2026-09-subtitle-transcript-sqlite/snapshot.json:11-24`
- Confidence: High

## Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 0 |
| 🟢 Suggestion | 3 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Approve

Rationale: the branch does what the spec locks, and I verified the upstream-interaction claims
against the installed pin rather than against the seam's own description of it. The raise-vs-drop
boundary is exact in both directions, no path returns an empty success, the `-101` divergence is
two-directionally pinned, the bounded re-list is one pair and only in the transport class, and the
credential/URL boundary holds with an empty credential on the CDN fetch. No assertion was deleted or
loosened anywhere in the branch (independently censused); every high-value guard fails a test on
revert; the fix wave's one behaviour change is scoped to a single exception class and keeps
`transport_error`/`response_error`/`shape_error` loud. The three Suggestions are editorial/coverage
items with no blocking effect, so the verdict is Approve under the report rules (Critical = 0,
Warning = 0, no Unconfirmed finding, no high-impact open trade-off).

Note on the one PM-settled tension: the HTTP-404 body-fetch class (QC2-001) is *not* re-litigated
here — §5's explicit table governs, as the PM recorded — only the §4.3 prose is asked to catch up so
Plans 2–3 read the retry class the same way the code implements it.

Non-findings / accepted readings (recorded so a later reader does not re-open them as defects):

1. A `None` player payload is `shape_error` while `{"subtitle": null}` is an empty inventory
   (`:249-261`) — deliberate: a null whole payload cannot honestly be read as "nothing was visible",
   and the loud reading is the safe one for a probe.
2. The probe fetches only `tracks[0]` (B:384) — the plan's bounded scope ("when a track exists, that
   segments normalize"), not a coverage claim about every listed track.
3. The seam records `update_params` *input*, so `isGaiaAvoided` is recorded as `False` rather than the
   pin's wire `0` (`_prepare_request` bool→int, `utils/network.py:2202-2212`) — the recorded shape is
   documented as "the parameters it handed over", and signing/cookies/encoding are explicitly outside
   the mirrored scope; the wire-level witness is the opt-in live run.
4. `subtitle_url` is followed without a scheme/host allow-list — identical to the shipped legacy path
   (`bili_client.py:575-577`, `download_subtitle`), the value is process-local, and it is never on a
   DTO or in a message.
5. The probe's `track_count=0`-passes vs listing-`not_found`-skips asymmetry — stated in the module
   docstring and defensible (a listing was obtained vs the endpoint errored).

`Needs L4/QA verification` (the plan's mandatory QA gate owns these; I re-ran nothing and did not set
`BILI_LIVE_SMOKE`): (a) the live PASS itself and the fixed-sample provenance
(`bvid=BV1S8hA6MEvy cid=41314223900`, `track_count=1`, `ai-zh:ai`, `segments=2913`,
`first_start_ms=460`, `last_end_ms=7896020`) — implementer-reported with three recorded runs incl. an
honest first-attempt `rate_limited` refusal; (b) `floor(seconds*1000)` verified against a live
document with known second-values (the live run proves the timeline, not the conversion constant);
(c) the archive-db branch's *I/O* never executed live (its control flow is now rehearsed offline);
(d) the full-suite totals (1091 passed / 3 skipped) and the focused counts — not reproduced here by
design.
