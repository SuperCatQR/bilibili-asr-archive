# Task 2 L2 Review — Adapter subtitle acquisition in the locked call shape

- Plan: `20260911-subtitle-gateway` · Task 2 of 3 · iteration `iter-2026-09-subtitle-transcript-sqlite`
- Review mode: Mode A, L2, diff-first · seat `code-reviewer` (read-only; no dispatch, no worktree mutation)
- Review range: `73fdef0..7f7156a` (`review/task-2-diff.md`, 4 files, +1393/−31)
- Worktree: `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-gateway` @ `7f7156a`
- Inputs read: brief, spec (full), plan, implementer report, task diff (full), the five touched/related worktree files, the installed pin
- Writes: this file only. `git status --porcelain` on the worktree is empty after the review.

## Verdict

| Field | Value |
|---|---|
| Spec compliance | ✅ Compliant (no Critical, no Important) |
| Task quality | **Approved** |
| Findings | 0 Critical · 0 Important · 6 Minor |
| ⚠️ Cannot verify from diff | 4 (listed below; none blocks) |

Independently reproduced evidence (this review):

- Sanctioned focused gate command re-run → **`306 passed, 1 skipped in 1.37s`** — exactly the claimed result; the only skip is the unchanged opt-in live smoke.
- Coverage-table spot check against the collected test IDs: `…rejects_an_unreadable_inventory` 18, `…rejects_an_unreadable_document` 25, `…listing_failures_map_onto_bounded_taxonomy` 14, `…document_failures_stay_bounded_and_never_loop` 9, `…reads_the_upstream_ai_markers` 9, `…empty_inventory` 6, `…malformed_ai_marker` 7, `…ambiguous_listing` 2 — **every count matches the report's table 1:1**; 307 collected vs the claimed baseline 180 = the claimed +127.
- Removed-line audit of the diff: 31 `-` lines — 17 docstrings/comments and 14 real lines (2 production imports, 2 `Video(...)` call sites, the `_await_upstream` signature, the `_NOT_FOUND_API_CODES` → parameter substitution, the `DOCUMENTED_METADATA_CALLS` literal, 2 allow-list lines, 3 authorized token removals, the 2-line `declared` comprehension) — every one replaced by an equal-or-stricter form, and **0 deleted assertions**. Full audit in §5.
- Pin source reads (offline, read-only): `Api.update_params` **replaces** `self.params` (`self.params = kwargs`); `Api.request(raw=False, byte=False)`; `Api.result` → `await self.request()`; `Api` is a dataclass whose constructor has no `raw`; `Video.get_player_info` calls `Api(**api, credential=…).update_params(aid=…, cid=…, isGaiaAvoided=False, web_location=1315873).result` — the adapter's shape is the same call with `bvid` for `aid` and the two documented overrides.
- AST probe on `src/bili_asr/sources/bilibili_api_gateway.py`: 43 distinct `ast.Attribute` names; exactly three carry a removed token (`_fetch_subtitle_document`, `_fetch_subtitle_inventory`, `_list_subtitle_entries`); none carries a retained token.

---

## 1. Spec compliance of the adapter (target 1)

| Locked clause | Verdict | Evidence |
|---|---|---|
| Transport fields read from `video.API["info"]["get_player_info"]` | ✅ | `bilibili_api_gateway.py:81` (`_PLAYER_INFO_ENDPOINT`), consumed at `:692-695`; `test_subtitle_listing_follows_a_changed_package_endpoint` rewrites the description and the issued URL/wbi follow |
| Only `dm`/`verify` overridden | ✅ | `:692-696` (`verify=False`, `dm=False` hard-coded, `url`/`method`/`wbi` from the description); `test_adapter_overrides_only_dm_and_verify_of_the_installed_pinned_player_endpoint:2534` scripts the pin's **own** `verify=True`/`dm=True` and asserts `request.verify is False`/`request.dm is False` — non-vacuous |
| Params exactly `{bvid, cid, isGaiaAvoided: False, web_location: 1315873}` | ✅ | `:699-704` via `update_params`; `test_subtitle_listing_request_carries_the_locked_call_shape` asserts the exact dict equality **and** that no `dm_*` key exists (pin semantics verified: `update_params` replaces rather than merges) |
| No `need_login_subtitle` / no `w_webid` | ✅ | exact-dict equality above makes any extra parameter fail; grep of the adapter shows neither name; the page path's `w_webid` resolution is untouched |
| Body fetch `Api(url=…, method="GET", wbi=False, dm=False, verify=False, credential=Credential())` as `.request(raw=True)` | ✅ | `_fetch_subtitle_document:726-745`; `test_subtitle_document_request_carries_the_locked_transport_shape` asserts url/method/`wbi is False`/`dm is False`/`verify is False`/`params == {}`/`raw is True` |
| Empty credential — SESSDATA must not reach the CDN host | ✅ | same test asserts `[request.has_sessdata for …] == [True, False]`, and the seam derives `has_sessdata` from the credential the call carried (`fixture:553`) |
| Internal `https:` normalization, one call only | ✅ | `_read_subtitle_document_url:369-384` normalizes `//…` → `https:…`; `test_fetch_subtitle_segments_normalizes_a_protocol_relative_document_url` scripts only the absolute form, so an un-normalized fetch fails loudly |
| `floor(seconds*1000)` | ✅ | `_read_caption_milliseconds:429-444` → `math.floor(seconds * 1000)`, the metadata path's conversion (`:220`) |
| `bvid`/`cid` validated before any call | ✅ | `:576-581` / `:596-600`; the two argument-rejection parametrizations assert `calls == []` |

## 2. Normalization boundary (target 2)

- **Raise vs drop is exactly the spec's** (`:406-427`): unreadable entry (non-mapping, absent/`null`/string/list/bool/non-finite `from`/`to`, absent/`null`/non-string `content`) → `GatewayShapeError` at document level; readable-but-unusable row (`end_ms <= start_ms`, `start_ms < 0`, empty/whitespace `content`) → dropped, siblings survive, asserted with the surviving sequence in `test_fetch_subtitle_segments_normalizes_the_document_and_drops_degenerate_rows`.
- **`body` array rule** ✅ (`:386-404`): absent/`null`/non-array → `shape_error`; present-and-empty → readable, no segments.
- **`body: []` / all-degenerate → `not_found`, never empty success** ✅ (`:621-622`, outside the retry `try`); `test_fetch_subtitle_segments_signals_not_found_when_nothing_survives` covers both documents and adds an assignment guard (`returned is None`) that can only hold if no empty tuple was ever returned.
- **Signal 1 — empty inventory → empty tuple** ✅ (`:571-581`); pinned for six payload shapes (`{}`, `{"subtitle": None}`, `{"subtitle": {}}`, `{"subtitle": {"allow_submit": False}}`, `{"subtitle": {"subtitles": None}}`, `{"subtitle": {"subtitles": []}}`) with `isinstance(tracks, tuple)` and the exact single-call list.
- **Signal 2 — never an empty success / never `shape_error` for nothing-usable** ✅ as above; the `not_found`-vs-`shape_error` distinction is additionally separated by the 25-case unreadable-document parametrization, whose documents are all *unreadable* rather than *empty*.
- Track-level rules: trimmed `language`/`label` with adapter-side checks (`:277-285`), non-empty primary subtag enforced through the DTO and re-wrapped as `shape_error` (`:286-291`, `-zh` case asserted), unknown keys tolerated, upstream order preserved.

## 3. Bounded re-list (target 3)

- Exactly one extra listing + fetch pair, structurally un-looped (`:605-620`): the second pair is outside any handler, so a second failure propagates.
- Trigger class is transport only; `rate_limited` and every other class propagate. Pinned by `test_subtitle_document_failures_stay_bounded_and_never_loop` (9 classes) with an exact call list `[listing, body] * attempts`, `attempts ∈ {1, 2}` — this is the "no third attempt, no loop" evidence.
- The happy/re-list pair is asserted end-to-end with a *fresh* URL on the second attempt (`test_fetch_subtitle_segments_relists_for_a_fresh_signed_url`: request URLs `[player, stale-url, player, fresh-url]`).
- The initial listing sits **outside** the `try`, so a listing failure never provokes the extra pair — correct, but only pinned for a non-transport class (see Minor M4).

## 4. Taxonomy (target 4)

- `_SUBTITLE_NOT_FOUND_API_CODES = _NOT_FOUND_API_CODES | {-101}` (`:64`) is passed **only** from `_list_subtitle_entries:718-721`, i.e. the two subtitle methods; `_await_upstream:773-779` takes it as a keyword-only parameter **defaulting to the shipped `_NOT_FOUND_API_CODES`**, so every metadata call site is byte-identical.
- Both directions are pinned: subtitle `-101 → GatewayNotFound` (`:2578`) and the shipped metadata `-101 → GatewayResponseError` (`:960`, retained unchanged) plus the explicit divergence test (`:2602-2628`) which asserts both in one test. The document fetch deliberately does **not** take the extended set (spec §5 scopes `-101` to the listing) — consistent.
- Remaining rows verified: `-412/-352/-799` and HTTP 412/429 → `rate_limited`; `-404/-62002`/HTTP 404 → `not_found`; `WbiRetryTimesExceedException` → `rate_limited`; `ResponseException`/`ApiException`/other codes → `response_error`; catch-all → `transport_error`. `GatewayError` siblings are unrelated subclasses (no accidental catch by `except GatewayTransportError`).

## 5. The seven authorized updates + the assertion audit (target 5)

| # | Authorized | Implemented | Kept exact/strict? |
|---|---|---|---|
| 1 | Remove only `subtitle`/`player`/`download` from `FORBIDDEN_SEAM_METHOD_TOKENS`; keep the other seven; positively assert the authorized surface | ✅ `test:289-311`, control at `:1763-1770` | Kept seven present; removal offset by a two-part positive control (names present **and** each carries a removed token). Caveat: only `subtitle` is load-bearing → M2 |
| 2 | Extend `DOCUMENTED_METADATA_CALLS` with `player.track_list`/`subtitle.body`, still an exact set | ✅ `fixture:136-142` | Exact 5-tuple, additionally pinned verbatim and guarded against an undocumented route (`test:2204-2213`). Caveat: the guard matches by prefix → M3 |
| 3 | Add the protocol-relative URL to `NO_LEAK_MARKERS` | ✅ `fixture:163,175-181` | `PROTOCOL_RELATIVE_SUBTITLE_URL` is defined before the marker tuple; the sentinel test now asserts both positive controls and both memberships (`test:2162-2181`) |
| 4 | `test_gateway_protocol_surface_is_locked` → exact method set + corrected docstring | ✅ `test:1629-1662` | **Strictly stronger**: `declared` is built from `vars(BilibiliGateway)` public members, so a seventh method now fails; a non-callable public member would error rather than silently pass |
| 5 | Re-export the two DTOs from `sources/__init__.py`, adapter still un-re-exported | ✅ `__init__.py:18-19,33-34` + `test:2186-2202` | Package docstring's "Re-exports the application-owned DTOs" claim is now true again (Task-1 ⚠️3); `not hasattr(sources, "BilibiliApiGateway")` keeps the adapter an explicit import |
| 6 | Pin the locked no-track signalling executably | ✅ `test:2403` (empty tuple, six payloads) and `test:2967` (`not_found`, empty + all-degenerate, `returned is None`) | Executable, and the second test cannot pass by returning `()` |
| 7 | Trim `language`/`label` and segment `text` | ✅ `:277-291`, `:406-427` | Pinned by the whitespace-wrapped normalization case and `"  未明子  "` → `"未明子"`. Caveat: spec-worded "verbatim" tension → M5 |

**Assertion audit — every changed/removed existing assertion, with strictness verdict.**

| Diff site | Change | Verdict |
|---|---|---|
| `ALLOWED_PACKAGE_IMPORTS` (`test:112-127`) | `video` moved to the package root; `bilibili_api.video: {Video}` dropped | Authorized (C1). The comparison stays exact equality (`test:1726`). Source-reachable surface widens → M1 |
| `FORBIDDEN_SEAM_METHOD_TOKENS` (`test:289-297`) | exactly `subtitle`/`player`/`download` removed, other seven kept | Authorized; offset by the new positive control. Two removals inert → M2 |
| `test_gateway_protocol_surface_is_locked` | `getattr`-over-`expected` loop → `vars(BilibiliGateway)` comprehension; docstring corrected | **Stronger**, nothing loosened |
| `test_the_subtitle_url_sentinel_is_scanned_like_every_other_secret` | extended with the relative sentinel + two membership asserts | **Stronger**; the original absolute-sentinel control is retained verbatim |
| `fixture:DOCUMENTED_METADATA_CALLS` | 3-tuple → 5-tuple | Authorized extension; no route removed |
| `fixture:NO_LEAK_MARKERS` | + relative-URL sentinel | **Stronger**; no sentinel removed |
| `test_gateway_imports_stay_on_metadata_surface` | docstring only | Assertion untouched (exact dict equality) |
| `test_gateway_source_never_names_forbidden_seam_methods` | docstring + two new positive controls | **Stronger** (the original `forbidden_hits == []` and metadata-attribute control are retained) |
| Production `Video(...)` → `video.Video(...)`, `_await_upstream` signature, `_NOT_FOUND_API_CODES` → parameter | behavior-preserving | Metadata path's mapping and call shapes unchanged; default parameter equals the shipped constant |
| Docstrings/comments in adapter, fixture, tests | text only | No assertion touched |

**Result: 0 assertions removed, 0 loosened; 2 strengthened (items 4 and the sentinel test); 2 surface changes exactly as authorized (items 1 and C1).**

## 6. C1 — the import-boundary change (target 6)

- **Boundary test still an exact equality** ✅ — `test_gateway_imports_stay_on_metadata_surface:1726` (`assert imports == ALLOWED_PACKAGE_IMPORTS`), plus `test_only_the_gateway_module_imports_bilibili_api:1682` unchanged.
- **Minimality — partially true, not literally true.** The *names* bound are `{Credential, request_settings, user, video, Api, 5 exceptions}`; no playback/audio/ASR *name* was added. But binding the module object instead of one class makes every public member of the pin's `video` module nameable without touching the import set. I enumerated the installed pin's 50 public names: the whole download/danmaku/audio family (`VideoDownloadURLDataDetecter`, `AudioStreamDownloadURL`, `Danmaku`, `FLVStreamDownloadURL`, …) *is* flagged by a retained token, but `Episode`, `VideoOnlineMonitor`, `get_api`, `get_cid_info`, `get_client` are **not**. Runtime capability is unchanged (importing `bilibili_api.video` already executed the module); what changed is source-level reachability and therefore what the two AST guards can see. See M1 for the two-line narrower alternative; the shipped `user` module precedent makes acceptance defensible.
- **Verdict: acceptable as disclosed.** The change is required by the locked requirement to read `video.API[...]`, is disclosed rather than assumed, and the recorded-call surface remains bounded by `assert_only_documented_metadata_calls` and by the seam (which exposes no playback/audio/download API at all).

## 7. C2a–e — verdicts (target 7)

| Item | Verdict | Reasoning |
|---|---|---|
| **(a)** re-list trigger = transport/expiry class only; CDN 404 → `not_found`, no re-list | **Spec-consistent** (one spec-text ambiguity recorded) | §5's table is explicit and wins over §4.3's looser parenthetical: 412/429 → `rate_limited` no re-list, HTTP 404 → `not_found` via the shipped mapper. §4.3's "expiry/transport class (HTTP status != 200 …)" could be read to include 404. Implementation matches §4.4's bounded guarantee and never spends risk budget on a block. Behavioural note for the PM: a *stale* signed URL that answers 404 is reported as `not_found`/`no-subtitle`; 403 (the common expiry status) does re-list. Recommend the PM confirm the §5 reading and, if the live probe shows 404s on stale URLs, tighten §4.3's wording in the iteration package (Task 3 owns the observation) — ⚠️ item 4. |
| **(b)** `is_ai = ai_status > 0 or type == 1`, `lan` prefix not consulted; non-integer marker → `shape_error` | **Spec-consistent** (marker reading) · **spec-silent-but-reasonable** (malformed marker) | §3: a marker marking machine generation ⇒ `True`, neither marker ⇒ `False`; `>0` and `type == 1` are upstream's documented AI values, and the language prefix is deliberately excluded (pinned by the `{"lan": "ai-zh"}` → CC case). Raising on a present-but-non-integer marker follows the spec's "rejected, never coerced" scalar discipline rather than silently defaulting to CC; the spec does not name this case. `type` values other than 0/1 are folded into the conservative CC reading — acceptable, PM may wish the spec to say so. |
| **(c)** `track_id` from integer `id` only; tie-break only when the request carries an id | **Spec-consistent** | §4.1: exactly one candidate carrying the same `track_id` wins, otherwise ambiguous → `shape_error`. A request with `track_id=None` cannot match any candidate, so ambiguity is the correct outcome (pinned for `None` and for an unmatched `"9"`); `id_str` is not read, and §3 names `id`. |
| **(d)** finite `from`/`to` whose ms product overflows → `shape_error` | **Spec-consistent (required, not a strengthening)** | §3's stated rationale for the non-finite rule is "without this rule `floor()` would escape as an unexpected `ValueError`/`OverflowError`". `1e308 * 1000` → `inf` → `math.floor` raises `OverflowError`, so the guard is what actually delivers the spec's invariant; it is one predicate (`math.isfinite` on the product) covering both the non-finite input and the overflowed product. |
| **(e)** absent/`null` `subtitle`/`subtitles` → empty inventory; present container of another shape → `shape_error` | **Spec-consistent** (§5's "empty/**missing** `subtitles` list → no error") · **spec-silent-but-reasonable** for a wrong-typed container | The null-vs-wrong-shape line is applied consistently across the new helpers (`subtitles`, `id`, `ai_status`, `type`): `null`/absent means "no value", a present value of the wrong type means "unusable response". This is also the reading that cannot silently convert a malformed response into "nothing was visible" — the spec's honesty rule (§2.1, §6). |

## 8. Non-vacuity of the guards (target 8)

Read, not re-run (mutation driver not re-executed; worktree read-only). Each high-value guard fails on revert:

- `dm`/`verify` overrides — `test:2534` (against the pin's own `verify=True`/`dm=True`) and the locked-shape test's `request.verify is False` / `request.dm is False` / `dm_*` absence.
- Locked params — exact dict equality; any added parameter (including the two folklore ones) fails, plus the `w_webid`/`need_login_subtitle` grep.
- Empty credential — `[has_sessdata] == [True, False]`, derived from the credential object the seam received, not from a flag the test sets.
- Single re-list — exact call list with `attempts`, plus the fresh-URL request-URL list; a loop or a third attempt changes the list.
- `-101` divergence — both directions asserted in one test; removing `-101` from the subtitle set or handing the metadata path the extended set each flips an assertion.
- Drop-vs-raise boundary — surviving-tuple equality (drops) against the 25-case raise parametrization; neither can absorb the other's rows.
- Trimming — DTO field equality on whitespace-wrapped inputs plus `text` equality from `"  未明子  "`.
- Authorized-surface non-vacuity — `AUTHORIZED_SUBTITLE_ATTRIBUTES <= attribute_names` (so the token scan cannot pass by having no subtitle code).

The implementer's 18/18 mutation table is consistent with what I read; the two guards I would want *stronger* are the initial-listing transport case (M4) and the inert token removals (M2).

---

## Strengths

1. **The locked call shape is asserted, not narrated.** Every clause of §1.2/§1.3 has an assertion on the *recorded* call (params dict, flags, `raw`, credential presence per request), and the pin-parity test drives the adapter against the distribution's own description — the strongest form this contract can take offline.
2. **The two signalling rules are pinned asymmetrically on purpose**, and the empty-inventory test additionally asserts `isinstance(tracks, tuple)` while the body-fetch test guards against an empty success with an assignment that can only stay `None`. That is the exact pair the spec calls locked.
3. **`not_found_api_codes` is a keyword-only parameter defaulting to the shipped constant** — the metadata mapping is provably untouched by construction, and the divergence is pinned in both directions in a single test.
4. **Discipline of the null-vs-wrong-shape boundary** is uniform across five new readers; the `not_found` / `shape_error` split stays the only distinction the spec asks for.
5. **No secret surface was widened**: the URL exists as a returned local, `has_sessdata` is derived from the credential, and every mapped message is class + code + static detail.
6. **Disclosure quality**: C1 and all five interpretation calls were disclosed with reasoning instead of being buried; the report's coverage table reconciled exactly with the collected test IDs.
7. Docstrings state *why* (412 evidence for `dm`, offline `verify` semantics for `verify`, `-101` divergence, explicit non-loop comment) — the next reader does not have to re-derive the risk-control history.

---

## Issues

### Critical

None.

### Important

None.

### Minor

**M1 — `ALLOWED_PACKAGE_IMPORTS` now binds the whole `video` module; C1's "no new name family reachable" is broader than stated.**
`test:112-127` / adapter `:23`. The exact-equality test holds, but `video.Episode`, `video.VideoOnlineMonitor`, `video.get_api`, `video.get_cid_info`, `video.get_client` are nameable with no import-set change and carry no retained `FORBIDDEN_SEAM_METHOD_TOKENS` token (AST probe + enumeration of the pin's 50 public module names). Not a defect and consistent with the shipped `user` precedent. PM options: (i) accept as-is and record it; (ii) re-narrow to `from bilibili_api.video import API, Video` (two-line change; keeps an exact `bilibili_api.video` entry) so the source-reachable surface stays a named pair.

**M2 — two of the three authorized token removals are inert, and the new control does not cover them.**
AST probe: `subtitle` → exactly the three `AUTHORIZED_SUBTITLE_ATTRIBUTES`; `player` → 0 hits; `download` → 0 hits. The control at `test:1766` is satisfied by `subtitle` alone, and re-forbidding `player`/`download` today would break no assertion. More materially, `download`'s removal means a future `Video.get_download_url()` call — previously flagged, and part of the next iteration's boundary — now passes the token scan through the already-allowed `video` module. Nothing in the adapter uses either token. PM may re-tighten `download` (one line, green today) or explicitly accept it.

**M3 — `assert_only_documented_metadata_calls` matches by prefix, not exact membership.**
`fixture:776-787`: `call.startswith(DOCUMENTED_METADATA_CALLS)`. The declared surface is an exact tuple and is now pinned verbatim, but a recorded token that merely *starts with* an allowed route (`player.track_list_x`, `video.get_info_extra`) still passes. Pre-existing shipped behaviour, not introduced by this task; flagged because brief item 2 says "keep it an exact set".

**M4 — test gap: a transport-class failure on the fetch's own initial listing is not pinned.**
`bilibili_api_gateway.py:602-604` (initial listing outside the `try`) is correct, but only the `not_found` class is asserted for it (`test:2807-2818`, `calls == [_listing_call()]`). A structural mutation that moved the initial listing inside the `try` would add an unasserted re-list for 503/`RuntimeError`. Closing test (~4 lines): `player_error = FakeNetworkException(503, …)` → expect `GatewayTransportError` and `calls == [_listing_call()]`.

**M5 — segment `text` is trimmed although the spec says "verbatim".**
`:406-427`, pinned by `"  未明子  "` → `"未明子"`. This is exactly brief item 7, so the implementer is compliant with the authorization; but Task-1's L2 review advisory ⚠️5 read the opposite way ("must **not** strip segment text"), and spec §3 ("no text editing") / §6 ("passed through verbatim") can be read that way. Spec §2's `text # non-empty after strip` only makes stripping a validator. PM disposition: accept the brief as authoritative (my recommendation — the behaviour is harmless, and it is pinned) and, if desired, amend the spec sentence at iteration-close so contract and code agree.

**M6 — mapped exceptions keep `from exc` chaining, so a traceback can still render the pin's own exception text.**
`_await_upstream:773-810`. `str`/`repr` are bounded (class + code + static detail, `models.py:179-199`) and asserted leak-free; `traceback.format_exception` additionally renders `__cause__` (for a CDN failure the pin's `NetworkException` carries the response text). Shipped metadata-path pattern, unchanged here, and no persisted surface takes a traceback — raised because Task 2 adds the first subtitle-path exceptions and the CLI plan owns logging. No action for this task.

---

## ⚠️ Cannot verify from diff (PM to check)

1. **Full offline suite `1073 passed, 2 skipped`** — not re-run (assignment forbids a full-suite re-run). It is arithmetically consistent (baseline 946 + the 127 new cases), and the focused file is independently confirmed at `306 passed, 1 skipped`.
2. **Live acceptance of the locked call shape** — whether the player endpoint answers under `dm=False`/`verify=False` with no invented parameters, and whether the CDN accepts the no-body `GET` (`data={}`) that the adapter issues while the pin's own helper forwards the description's declared `data` mapping. Spec §1.1 calls that declaration "field documentation" and `test:2149` says the same, so the adapter's shape is compliant — but only Task 3's live probe can record the outcome, and the plan's STOP condition covers a risk-control refusal.
3. **Task-1 F3's second half** — `FakeGateway` (the protocol double in `fixture`) still implements only the four metadata methods. Out of this brief's authorized list and nothing consumes the subtitle methods through the double yet, but Task-1's review recorded it as "must not be forgotten" and the plan's Durable Roadmap section does not name it. PM: confirm the owning plan/task or register it.
4. **Three PM-owned dispositions** — C1's import shape (M1), the `download` token (M2), and the spec's "verbatim" wording versus brief item 7 (M5). None blocks the code; all are recorded so `zero-residual` closes them deliberately rather than by silence. (The §4.3/§5 HTTP-404 reading in C2a is a fourth, of the same kind.)

---

## Assessment

**Task quality: Approved.**

All six brief items and all seven PM-authorized test/contract updates are implemented exactly as written; the normalization boundary, both locked signalling rules, the taxonomy extension (subtitle-only, metadata byte-identical by default), the bounded re-list and the no-leak boundary are each pinned by assertions I read and, in the focused run, reproduced. The diff removes no assertion and loosens nothing beyond the two authorized surfaces. The six Minor findings are advisory or narrow test-strengthening items; M1/M2/M5 and the C2a spec-text reading are PM dispositions, and M4 is a one-test gap in an otherwise complete re-list guard. Nothing here requires a fix round; the PM owns disposition under `zero-residual`.
