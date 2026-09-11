# Subtitle Gateway Contract (iteration spec)

> Iteration `iter-2026-09-subtitle-transcript-sqlite`, spec point 1.
> Status: architecture locked (2026-09-11); product intent reviewed (product-manager,
> 2026-09-11); writing/corpus hygiene reviewed (writing-specialist, 2026-09-11);
> PM lock: locked (project-manager, 2026-09-11).
> Scope guard: this spec covers **subtitle acquisition only**; audio/ASR are the next iteration.
> Every upstream shape below was read out of the installed pin
> (`bilibili-asr-archive/.venv/lib/python3.12/site-packages/bilibili_api`, distribution
> `bilibili-api-python==17.4.2`), not from documentation.

## Goal

Move AI/CC subtitle acquisition (track listing + subtitle-body download) off the raw
`bili_client` HTTP path and behind the application-owned typed gateway in
`bilibili-asr-archive/src/bili_asr/sources/`, so third-party response dictionaries never
reach application code and every failure is a bounded scalar code.

Product framing: this boundary is what makes the operator's probe honest. What it returns
describes exactly what the credential in effect could see for one part at one moment —
language, display label, AI versus CC, and the timeline in milliseconds; what it fails with
is always a stable code the operator can act on. It never downloads on its own initiative,
never picks a track for the operator, and never lets a signed URL or a credential out of
process memory.

## 1. Upstream interface (pin-verified)

### 1.1 Track listing

The pinned package describes the player endpoint once, in
`bilibili_api.video.API["info"]["get_player_info"]` (`data/api/video.json`):

| Field | Value in the installed pin |
|---|---|
| `url` | `https://api.bilibili.com/x/player/wbi/v2` |
| `method` | `GET` |
| `verify` | `true` |
| `wbi` | `true` |
| `dm` | `true` |
| `data` (declared query fields) | `aid` (`与 bvid 任选其一`), `cid`, `ep_id`, `isGaiaAvoided`, `web_location` |
| `comment` | play record, subtitle and region info for one part; the response carries the JSON subtitle link |

The library's own `Video.get_player_info(cid=...)` sends
`{aid, cid, isGaiaAvoided: False, web_location: 1315873}` through `Api(**endpoint, credential=...)`
and returns `subtitle` from the response data. Note the description's query fields sit under
the JSON key `data` (unlike the user-video page endpoint, which declares `params`); in the
pinned `Api` both dictionaries are folded into the GET query, and `update_params(**kwargs)` is
the call the package's own player method uses — which is what this adapter mirrors.

Two upstream folklore claims are **not** in the pin and are therefore **not** sent:

- **`need_login_subtitle` does not exist in this pin.** `grep -rn need_login_subtitle` over
  the whole installed package returns nothing; the endpoint description does not declare it
  and `video.py` never sends it. The legacy `bili_client.probe_subs` docstring mentions the
  parameter, but that method's own query is `{cid, bvid}` plus the WBI signature. Login-gated
  tracks become visible through the credential in effect (SESSDATA cookie), not through a
  request flag, and the spec's product semantics are written that way.
- **`w_webid` is not declared for this endpoint.** It is declared (and live-required) for the
  *user-video page* endpoint `user.API["info"]["video"]["params"]`, which is why the metadata
  adapter always sends it; the player endpoint's description has no such field, the package's
  own player call never sends it, and the legacy live probe of this exact endpoint answered
  `code=0` with `{bvid, cid}` only. Adding it would be an invented parameter and would make
  the endpoint-mirror parity test meaningless.

### 1.2 Call shape (locked)

The adapter builds exactly one listing call per listing:

- `url`, `method`, `wbi` are read from `video.API["info"]["get_player_info"]`, so a pin bump
  that changes them stays visible in the parity test.
- `dm=False` — an adapter-owned override. The device-fingerprint family (`dm_img_list`,
  `dm_img_str`, `dm_cover_img_str`, `dm_img_inter`) is synthesized by the package as
  placeholder values the adapter cannot supply truthfully, and the sibling WBI endpoint in the
  same risk-control family answered HTTP 412 with them and `code=0` without them (live run,
  `20260911-live-metadata-path-fix`).
- `verify=False` — an adapter-owned override. In the pinned `Api`, `verify=True` performs no
  upstream check at all: it only calls `credential.raise_for_no_sessdata()` locally (plus csrf
  handling for non-GET). Cookies come from `credential.get_cookies()` regardless. Mirroring
  `verify=True` would turn an anonymous probe into a local `CredentialNoSessdataException`
  instead of an honest "nothing usable was visible", which the product rule forbids. With
  `verify=False`, one call shape serves both credential tiers, and a configured SESSDATA is
  still sent as a cookie to the API host.
- Query parameters are exactly the description's declared set with `bvid` substituted for the
  declared alternative `aid` (`与 bvid 任选其一`): `bvid`, `cid`, `isGaiaAvoided=False`,
  `web_location=1315873`. Sending `bvid` is what keeps the call at one request per part: the
  package's own helper resolves `aid` first through an extra detail call
  (`Video.__get_aid()`), which this adapter must not pay. No other parameter is added.
- The package's `Api.request()` retry loop is inherited as-is: it re-signs and retries only a
  `-403` response, at most `wbi_retry_times` (default 3) times. The adapter adds no retry of
  its own on the listing path.

### 1.3 Subtitle body

The listing response's `data.subtitle.subtitles[]` entries carry `lan`, `lan_doc`,
`subtitle_url`, an AI marker (`ai_status` / `type`), and `id`. `subtitle_url` is a
short-lived signed CDN document, sometimes protocol-relative (`//...`) and sometimes absolute.

- A protocol-relative value is normalized to `https:` **inside the adapter**, for the duration
  of one call only.
- The body is fetched through the package's own transport with an explicitly **empty**
  `Credential()`: `Api(url=<signed url>, method="GET", wbi=False, dm=False, verify=False, raw=True)`.
  `raw=True` is required and sufficient — with `raw=False` the package would strip a
  `data`/`result` envelope that a subtitle document does not have and return `None`. The empty
  credential keeps SESSDATA off the CDN host (the legacy path's QC-F1 decision) while the
  package's proxy, TLS and impersonation settings still apply.
- `NetworkException` (HTTP status != 200) is the transport failure signal; a 200 response whose
  payload is not a JSON object, or is a JSON object whose `body` is absent, `null`, or not an
  array, is a payload failure (section 5).

## 2. Typed interface (application-owned)

DTOs added to `bili_asr.sources.models` (frozen dataclasses with `__post_init__` validation,
matching the shipped DTO style; `work_id` never appears here):

```python
@dataclass(frozen=True, slots=True)
class SubtitleTrack:
    language: str          # upstream `lan`, trimmed, non-empty, with a non-empty primary subtag
    label: str             # `lan_doc` display label, trimmed, non-empty
    is_ai: bool            # True for AI-generated tracks, False for CC/uploader
    track_id: str | None   # upstream `id` when present; the track's identity, never a URL

@dataclass(frozen=True, slots=True)
class SubtitleSegment:
    start_ms: int          # floor(seconds * 1000), >= 0
    end_ms: int            # floor(seconds * 1000), > start_ms
    text: str              # non-empty after strip
```

Protocol additions (extend `BilibiliGateway`; the existing four methods keep their signatures):

```python
async def get_subtitle_tracks(self, bvid: str, cid: int) -> tuple[SubtitleTrack, ...]: ...
async def fetch_subtitle_segments(
    self, track: SubtitleTrack, bvid: str, cid: int
) -> tuple[SubtitleSegment, ...]: ...
```

`bvid` is validated with the shipped `_BVID_PATTERN` guard and `cid` with
`_require_positive_argument` before any call. `bvid`/`cid` are primitives, never storage
records: the caller reads them from `video_parts` and the gateway never looks a part up itself.

### 2.1 No-usable-track signalling (locked, per method)

| Method | No usable track | Never |
|---|---|---|
| `get_subtitle_tracks` | returns an **empty tuple** | never raises `not_found` for an empty inventory; never returns a placeholder track |
| `fetch_subtitle_segments` | raises **`GatewayNotFound`** | never returns an empty tuple; never returns a success with empty content |

Both signals mean the same operator-facing fact — *no usable track was visible for this part
with the credentials in effect at that attempt* — and the caller maps both onto the
`no-subtitle` outcome. The distinction the product intent requires (an anonymous probe saw
nothing vs an authenticated probe saw nothing) is carried at the operator surface by credential
presence (`sessdata: present|absent`, the shipped `redact_sessdata` convention) and, in the
stored evidence, by `acquisition_runs.credential_present` plus the reported language inventory.
An empty inventory is a legitimate result, not a failure: a caller that recorded it as `failed`
would be lying about what it knows.

`fetch_subtitle_segments` raising `not_found` also covers a track that has disappeared between
the caller's listing and the fetch, because a second listing happens inside the fetch (below).

## 3. Normalization rules

Two verbs apply to a subtitle document, and one boundary decides between them — the document's
**shape**, never its content: an entry that **cannot be read as a segment** fails the whole call
with `GatewayShapeError` (section 5), while an entry that **reads as a segment but carries
nothing usable** is **dropped** from the normalized result. There is no third behaviour and no
coercion in either direction.

- An entry reads as a segment when it is a JSON object carrying a finite real `from`, a finite
  real `to` (JSON numbers; `bool` excluded the way the metadata path excludes it) and a string
  `content`. Everything else is unreadable and raises: absent, `null`, string, list, or boolean
  `from`/`to`; non-finite `from`/`to` (Python's `json` accepts the bare `NaN`/`Infinity` tokens,
  so without this rule `floor()` would escape as an unexpected `ValueError`/`OverflowError`);
  absent, `null`, or non-string `content`. This is the metadata path's `_normalize_*` rule — a
  malformed scalar shape is rejected, never coerced — and unknown extra keys are tolerated there
  and here alike.
- A readable entry is dropped when, and only when, it carries nothing usable: `end_ms <=
  start_ms` (zero-length or inverted interval), `start_ms < 0`, or `content` empty or
  whitespace-only after stripping. Dropping removes that row and keeps every other row of the
  document: a per-row tolerance, never a document-level failure. The convention is deliberately
  the opposite of the metadata path's out-of-domain scalars — a negative part `duration` is a
  `shape_error` there — because a part scalar identifies the unit of work and cannot be skipped,
  while a caption row is a content item whose siblings stay usable, and one degenerate row must
  not turn a readable subtitle into a failure.
- `start_ms = floor(start_seconds * 1000)` and `end_ms = floor(end_seconds * 1000)` — the same
  conversion the metadata path pins for `duration_ms`, not `subtitles.json_to_srt`'s `round()`.
  The drop rules are evaluated on these millisecond values, so what survives is exactly
  `end_ms > start_ms >= 0` with non-empty stripped text — the invariant
  `specs/transcript-storage.md` section 5 re-validates at the DB boundary. Drops happen before
  the DTO is constructed: `SubtitleSegment`'s own `__post_init__` validation is the invariant on
  what the call returns, not a filter.
- `body` must be a JSON array: absent, `null`, or any non-array value is unreadable and raises
  `GatewayShapeError` (section 5); a present, empty array is readable and yields no segments.
- A document in which no entry survives the drop rules — an empty `body` array included — yields
  `GatewayNotFound` from `fetch_subtitle_segments` (nothing usable), never an empty success. That
  `not_found`-vs-`shape_error` distinction is the only thing that separates "nothing usable" from
  "unusable response".
- Segment order follows upstream exactly; no re-ordering, no de-duplication, no text editing.
  Overlapping or non-monotonic upstream rows are preserved verbatim.
- A track with an empty `lan` or `lan_doc` after trimming is rejected as `GatewayShapeError`.
- A `lan` whose primary subtag (text before the first `-`) is empty — e.g. `-zh` — is rejected
  as `GatewayShapeError`: the service derives the language family from that subtag, and a
  vocabulary the service cannot rank would otherwise silently fall through the preference rule.
- `is_ai` derives from the upstream AI marker: `ai_status`/`type` marking the track as
  machine-generated ⇒ `True`; a track carrying neither marker is `False` (CC) — the
  conservative reading the product semantics state.
- Track order is preserved as returned by upstream; selection belongs to the service, not here.

## 4. Signed-URL resolution and the bounded re-list (locked)

`fetch_subtitle_segments` resolves the signed URL itself, because the URL never crosses the
boundary:

1. Re-list tracks for `(bvid, cid)` (one listing call) and resolve the requested track there.
   A `SubtitleTrack` is matched by `language` + `is_ai`; when several candidates match:
   - exactly one candidate carrying the same `track_id` as the requested track wins;
   - otherwise the listing is ambiguous and the call fails with `GatewayShapeError`.
   No candidate ⇒ `GatewayNotFound`.
2. Fetch the resolved URL once; on success return the normalized segments.
3. On a body-fetch failure **at most one** additional listing + fetch pair is attempted, and
   only for the expiry/transport class (HTTP status != 200 on the signed URL, i.e. a signature
   that no longer works). A rate-control answer (`rate_limited`) never triggers a re-list —
   re-listing into the same block only spends the risk budget.
4. If the second attempt also fails, the mapped bounded code is raised. There is no third
   attempt and no loop: worst case per `fetch_subtitle_segments` call is 2 listings and 2 body
   fetches, and the seam asserts the exact call list for both paths.

The happy path therefore costs two listing calls per part (one in the service's selection, one
inside the fetch). That is the price of keeping the URL out of every DTO, and it is bounded
and asserted.

## 5. Error taxonomy (bounded scalar codes only)

The taxonomy is the shipped one — `rate_limited`, `not_found`, `response_error`,
`transport_error`, `shape_error` — and no new code is introduced. The shared mapper
(`_await_upstream`) keeps its metadata-path sets; the two subtitle methods pass an extended
not-found set so that the login signal is classified as "not visible" instead of a generic
response error.

| Upstream condition | Bounded code | Where |
|---|---|---|
| `-101` (not logged in) on the listing | `not_found` | subtitle calls only: `{-101} ∪ {-404, -62002}` |
| Listing answers an empty/missing `subtitles` list | *(no error)* | empty tuple from `get_subtitle_tracks` |
| Listing `subtitles` present but not an array, or an entry not normalizable | `shape_error` | both methods |
| `-352`, `-412`, `-799` risk control | `rate_limited` | shipped shared mapping |
| HTTP `412`, `429` | `rate_limited` | shipped shared mapping |
| `-404`, `-62002`, HTTP `404` | `not_found` | shipped shared mapping |
| Track absent from the fresh listing | `not_found` | `fetch_subtitle_segments` |
| `body` present and empty, or no entry survives the section 3 drop rules | `not_found` | `fetch_subtitle_segments` |
| Signed-URL fetch HTTP status != 200 | `transport_error` | after the single bounded re-list |
| Signed-URL fetch HTTP `412`/`429` | `rate_limited` | no re-list |
| 200 response that is not a JSON object, or whose `body` is absent, `null`, or not an array | `shape_error` | `fetch_subtitle_segments` |
| An entry in `body` that is not readable as a segment (section 3) | `shape_error` | `fetch_subtitle_segments` |
| Any other upstream error envelope (`ApiException`, `ResponseCodeException`, `ResponseException`) | `response_error` | shipped shared mapping |
| Network/transport failure with no usable response | `transport_error` | shipped shared mapping |

The metadata path's mapping is unchanged: `-101` stays `response_error` there, pinned by a
test. `not_found` from either subtitle method reaches the caller as the `no-subtitle` outcome;
every other code reaches it as `failed` with that code.

## 6. Product semantics (what the caller and the operator can rely on)

- **A track is an inventory entry, not a promise.** The gateway reports the tracks the
  credential in effect could see at this moment. An empty result means "nothing usable was
  visible now" — never "this video has no captions", because availability changes with login
  state, time, and upstream processing. The caller owns the wording shown to the operator.
- **AI vs CC is a preserved, operator-facing fact.** `is_ai` separates machine-generated
  captions from uploader/human captions; a track carrying neither upstream marker is reported
  as CC, and that conservative reading is stated wherever the field is surfaced.
- **Language and label are printable as-is.** `language` is the upstream `lan` code and
  `label` is the human-readable `lan_doc`; both are non-empty after trimming, so a CLI can
  print them without inventing names or falling back to "unknown".
- **A part with no usable track is not a failure.** The adapter surfaces it as an empty tuple
  from the listing and as `not_found` from the body fetch (section 2.1); the caller classifies
  both as `no-subtitle`, never as a success carrying empty content and never as an unexpected
  failure.
- **Failure codes are the operator's vocabulary.** `rate_limited`, `transport_error`,
  `response_error`, and `shape_error` tell the operator whether retrying later is sensible;
  the caller maps them to a `failed` outcome with that code. `not_found` is reserved for "no
  usable track was visible".
- **Segments are ordered and honest.** Segment order follows upstream; text is passed through
  verbatim (no correction, punctuation, or quality claim), and every segment satisfies
  `end_ms > start_ms >= 0` with millisecond conversion identical to the metadata path.
- **No secret crosses the boundary** — not to the caller, not into an exception message, not
  into a fixture, not into a row. `subtitle_url` exists only for the duration of one call.

## 7. Credential and payload boundary

- `SESSDATA` still comes only from `BILI_SESSDATA` / `--sessdata`, is used solely to build the
  package `Credential`, and appears in no DTO, message, log, fixture, or row.
- Signed subtitle URLs, raw subtitle JSON, and response bodies never enter a DTO field, a
  persisted row, an exception message, or CLI output.
- `subtitle_url` values are process-local for the duration of one call; the empty credential
  on the body fetch keeps the API credential itself off the CDN host.

## 8. Test seam

- Extend the shared fake seam (`tests/fixtures/fake_bilibili_gateway.py`) with the player
  endpoint description mirror (`FAKE_PLAYER_ENDPOINT`, copied literally from
  `video.API["info"]["get_player_info"]`), scripted `subtitles[]` payloads, scripted subtitle
  bodies, and a recorded call list for both, keeping every existing exact call-list assertion
  intact. The seam stays a seam: it exposes no playback, audio, or download API.
- Parity tests mirror the shipped endpoint checks: the fake's description equals the installed
  pin's description field for field, the adapter reads `url`/`method`/`wbi` from it, and the
  adapter's only overrides are `dm=False` and `verify=False` — asserted on the recorded call,
  not on the source text.
- Offline tests must cover: track normalization (AI vs CC, labels, primary-subtag rejection),
  segment conversion and every rejection rule, protocol-relative URL normalization, each
  taxonomy row above, the empty-tuple/no-subtitle outcome staying distinguishable from a
  failure, the exact recorded call shape (params set, `dm`, `verify`, `wbi`), the single
  bounded re-list and its call list, the `-101` divergence between the subtitle and metadata
  paths, the import boundary (only `sources/bilibili_api_gateway.py` imports `bilibili_api`),
  and the no-leak scans (URL/credential sentinels absent from DTOs, messages, and rows).

## 9. Acceptance

- Offline suite green with the new tests; no network in tests.
- A probe result distinguishes language, display label, and AI versus CC for every returned
  track; a part with no usable track comes back as an empty tuple and/or `not_found` — never as
  an empty success and never as an unexpected failure.
- A bounded live probe (one `(bvid, cid)` from the operator's own archive) returns the track
  list; when a usable track exists, the body normalizes into segments with milliseconds
  matching `floor(seconds*1000)`; when no track is visible, the recorded outcome says so and
  names whether a credential was in effect.
- No signed URL, credential, or raw response body is reachable from a DTO, an exception
  message, a log line, a fixture, or a persisted row.
- The live probe records which call shape answered. If the player endpoint refuses the locked
  shape (`dm=False`, `verify=False`, no invented parameters) with a risk-control code, that is
  a recorded bounded blocker and an escalation — never a reason to enable fabricated
  fingerprint parameters or to add undeclared parameters.

## 10. Out of scope / handoff

- Retiring `bili_client`'s subtitle methods, and the legacy manifest path itself, belong to the
  CLI cutover plan and later.
- Audio/playback APIs (playurl, audio streams) are the next iteration; this gateway grows no
  method for them.
- This spec is the plans' primary spec
  (`{PLAN_DIR}/20260911-subtitle-gateway.md`). The durable cross-iteration part of this
  iteration's contract is the transcript/process-record shape in
  `specs/transcript-storage.md`; promotion of that contract to `{SPECS_DIR}` or
  `{KNOWLEDGE_DIR}` is decided at iteration-close (owner `project-manager`, trigger "this
  iteration delivered"), not in this Prepare pass.
