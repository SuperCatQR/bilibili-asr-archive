---
module: bili-asr subtitle gateway
date: 2026-09-11
problem_type: architecture_pattern
category: architecture-patterns
severity: medium
plan_id: 20260911-subtitle-gateway
applies_when:
  - adding or changing a subtitle acquisition call against the pinned package
  - upgrading bilibili-api-python and re-checking the player endpoint's declared surface
  - selecting which caption track to keep for a part
  - mapping upstream caption failures onto bounded scalar codes
  - reviewing whether a credential or a signed URL can escape into a DTO or a row
tags:
  - subtitle-acquisition
  - gateway-boundary
  - bilibili-player-endpoint
  - bounded-taxonomy
  - track-preference
  - secret-boundary
---

# Subtitle acquisition contract (pin-verified gateway boundary)

## Context

AI/CC caption acquisition is a transport concern and lives behind the application-owned
gateway (`bilibili-asr-archive/src/bili_asr/sources/`), not in the CLI and not in raw HTTP
helpers. Every claim below was read out of the **installed pin** —
`bilibili-api-python==17.4.2` under the package's `.venv`, not from upstream documentation or
folklore — because the pinned package's endpoint descriptions, its `Api` semantics, and its
request parameters are what the adapter actually executes. Two widely repeated parameters are
absent from that pin and are therefore not sent; one of them is required by a *different*
endpoint, which is how the confusion started.

## Guidance

### The player endpoint, as the pin declares it

The adapter mirrors one description and adds no endpoint of its own:

| Field | Value in the installed pin |
|---|---|
| source | `bilibili_api.video.API["info"]["get_player_info"]` (declared in the pin's own endpoint-description data, not in this repository) |
| `url` | `https://api.bilibili.com/x/player/wbi/v2` |
| `method` / `wbi` | `GET` / `true` |
| `verify` | `true` |
| `dm` | `true` (default) |
| declared query fields | `aid` (either `aid` or `bvid`), `cid`, `ep_id`, `isGaiaAvoided`, `web_location` |
| response of interest | `data.subtitle.subtitles[]`, and `data.subtitle` carries the signed document link |

The library's own `Video.get_player_info(cid=...)` sends
`{aid, cid, isGaiaAvoided: False, web_location: 1315873}`; resolving `aid` costs an extra
detail call (`Video.__get_aid()`), which is why the adapter sends the declared alternative
`bvid` instead and keeps the listing at one request per part. The declared fields sit under the
JSON key `data` for this endpoint (the user-video page endpoint declares `params`); the pin
folds both dictionaries into the GET query, and `update_params(**kwargs)` is the call the
package's own player method uses, which is what the adapter mirrors.

**Pin-verified negatives — do not re-add these:**

- **`need_login_subtitle` does not exist in this pin.** A recursive search over the whole
  installed package returns no occurrence; the description does not declare it and the
  package's `video.py` (inside the installed distribution) never sends it. Login-gated tracks
  become visible through the credential in effect (the SESSDATA cookie), not through a request
  flag. The legacy `bili_client.probe_subs` docstring mentions the parameter — that docstring
  is not evidence about this endpoint.
- **`w_webid` is not declared for this endpoint.** It is declared *and live-required* for the
  user-video page endpoint (`user.API["info"]["video"]["params"]`), which is why the metadata
  adapter always sends it. The player endpoint's description has no such field and the
  package's own player call sends none. Sending it would be an invented parameter and would
  make the endpoint-mirror parity test meaningless.

### The locked call shape, and why each override exists

- `url` / `method` / `wbi` come from the description, so a pin bump that changes them shows up
  in the parity test instead of silently re-pointing the adapter.
- **`dm=False`** (adapter-owned override). The device-fingerprint family (`dm_img_list`,
  `dm_img_str`, `dm_cover_img_str`, `dm_img_inter`) is synthesized by the package as
  placeholder values the adapter cannot supply truthfully. The sibling WBI endpoint in the
  same risk-control family answered HTTP 412 with them and `code=0` without them.
- **`verify=False`** (adapter-owned override). In the pinned `Api`, `verify=True` performs no
  upstream check at all: it only calls `credential.raise_for_no_sessdata()` locally (plus csrf
  handling for non-GET). Cookies come from `credential.get_cookies()` regardless. Mirroring
  `verify=True` would turn an anonymous probe into a local `CredentialNoSessdataException`
  instead of an honest "nothing usable was visible". With `verify=False`, one call shape
  serves both credential tiers, and a configured SESSDATA is still sent as a cookie to the API
  host — the operator-visible distinction is credential presence, never an exception.
- **Query parameters are exactly the declared set** with `bvid` substituted for `aid`:
  `{bvid, cid, isGaiaAvoided: False, web_location: 1315873}`. No other parameter is added.
- **Retries are the package's, not the adapter's.** `Api.request()` re-signs and retries only
  a `-403` response, at most `wbi_retry_times` (default 3) times; the listing path adds no
  retry of its own.

### The subtitle body fetch

`subtitle_url` is a short-lived signed CDN document. It never crosses the boundary — it exists
only for the duration of one call:

```python
api = Api(url=<signed url>, method="GET", wbi=False, dm=False, verify=False,
          credential=Credential())          # deliberately empty
payload = await api.request(raw=True)
```

- **`raw` is a `request` parameter, not a constructor field.** The installed pin's
  constructor takes the URL, the method, and the `verify` / `wbi` / `dm` / `credential`
  fields, while `Api.request(raw=False, byte=False)` owns
  those two flags (`Api.result()` always calls `request()` bare). `raw=True` is required and
  sufficient: with `raw=False` the package would strip a `data`/`result` envelope that a
  subtitle document does not have and return `None`.
- **The empty `Credential()` keeps SESSDATA off the CDN host**, while the package's proxy, TLS,
  and impersonation settings still apply.
- **HTTP 404 on the signed URL is not a transport failure**: it maps to `not_found` with no
  re-list. Every other non-200 status is the transport/expiry class. A 200 response that is not
  a JSON object, or whose `body` is absent, `null`, or not an array, is a payload failure
  (`shape_error`).

### URL normalization

Exactly three forms are accepted, decided **before any request**:

- `//host/…` and `http://host/…` are rewritten to `https://` inside the adapter, for the
  duration of one call only;
- an `https://` value passes through;
- anything else — another scheme, a bare authority — is refused with a bounded `shape_error`.

So a non-`https` capability URL is never fetched, and an un-normalized value can never reach a
DTO, a row, or an error message.

### The normalization boundary: raise or drop, never coerce

One rule decides between two verbs, and it is the document's **shape**, never its content: an
entry that **cannot be read as a segment** fails the whole call, while an entry that reads as a
segment but **carries nothing usable** is dropped. There is no third behaviour.

| Condition | Result |
|---|---|
| entry is not a JSON object; `from`/`to` absent, `null`, string, list, or boolean; `from`/`to` non-finite (`NaN`/`Infinity` — Python's `json` accepts those tokens); `content` absent, `null`, or non-string | document-level `shape_error` |
| `body` absent, `null`, or not a JSON array | document-level `shape_error` |
| readable entry with `end_ms <= start_ms`, or `start_ms < 0`, or `content` empty/whitespace-only after stripping | **dropped** (per-row tolerance; the other rows survive) |
| `body` present but empty, or no entry survives the drop rules | `not_found` — never an empty success, never `shape_error` |

- Conversion is `floor(seconds * 1000)` for both ends — the same rule the metadata path pins
  for `duration_ms`, deliberately **not** `subtitles.json_to_srt`'s `round()`. The drop rules
  are evaluated on those millisecond values, so what survives is exactly
  `end_ms > start_ms >= 0` with non-empty stripped text, which the transcript store re-validates
  at the DB boundary.
- Unknown extra keys are tolerated, as on the metadata path.
- **Why the asymmetry is deliberate:** a metadata scalar identifies the unit of work and
  cannot be skipped (a negative part `duration` is a `shape_error` there), while a caption row
  is a content item whose siblings stay usable — one degenerate row must not turn a readable
  subtitle into a failure.
- Segment order follows upstream exactly: no re-ordering, no de-duplication, no text editing.
  Overlapping or non-monotonic rows are preserved verbatim.
- `language` / `label` are trimmed and must be non-empty; a `lan` whose primary subtag is empty
  (for example `-zh`) is a `shape_error`, because the selection rule derives the language
  family from that subtag and a vocabulary it cannot rank would otherwise fall through the
  preference rule silently. `is_ai` derives from the upstream AI marker, and a track carrying
  neither marker is reported as CC — the conservative reading. Track order is preserved;
  selection belongs to the service.
- Caption text keeps interior control characters (it is content, stored verbatim), while
  operator-facing labels must not carry them — a label is printed on a locked one-line-per-track
  shape, so a control character there is rejected as `shape_error` rather than allowed to split
  the output.

### No usable track: two signals, one meaning

| Method | No usable track | Never |
|---|---|---|
| track listing | returns an **empty tuple** | never raises `not_found` for an empty inventory; never returns a placeholder track |
| segment fetch | raises **`GatewayNotFound`** | never returns an empty tuple; never returns a success with empty content |

Both mean the same operator-facing fact — *no usable track was visible for this part with the
credentials in effect at that attempt* — and both reach the caller as the same outcome.
An empty inventory is a legitimate result, not a failure: recording it as `failed` would be a
lie about what is known. The anonymous-versus-authenticated distinction is carried by
credential presence (`sessdata: present|absent` at the operator surface, the run's stored
credential flag in the evidence), not by a different code.

### Signed-URL resolution and the bounded re-list

The fetch resolves the URL itself, because the URL never crosses the boundary. One
`fetch_subtitle_segments` call is bounded by construction:

1. re-list tracks for the part (one listing call) and resolve the requested track by
   `language` + `is_ai`; when several candidates match, an identical `track_id` breaks the tie,
   ambiguity is `shape_error`, and no candidate is `not_found`;
2. fetch the resolved URL once;
3. on a body-fetch failure **in the expiry/transport class only** (HTTP status != 200 on the
   signed URL, except HTTP 404, which is `not_found` without a re-list), attempt **at most one**
   additional listing + fetch pair — a signature that no longer works is worth re-signing;
4. if the second attempt also fails, raise the mapped bounded code. There is no third attempt
   and no loop.

**A rate-control answer never triggers a re-list**: re-listing into the same block only spends
the risk budget. Worst case per call is therefore 2 listings and 2 body fetches, and the fake
seam asserts the exact call list for both paths.

A visible side effect is worth stating plainly: the happy path costs **two listing calls per
part** — one in the service's track selection, one inside the fetch. That is the price of
keeping the signed URL out of every DTO, and it is bounded and asserted rather than incidental.

### Failure vocabulary, including one deliberate divergence

The five bounded codes are the shipped ones (`rate_limited`, `not_found`, `response_error`,
`transport_error`, `shape_error`); acquisition introduces no new code.

| Upstream condition | Bounded code |
|---|---|
| `-101` (not logged in) on the listing | `not_found` **on the subtitle methods only** (`{-101} ∪ {-404, -62002}`) |
| `-352` / `-412` / `-799` risk control; HTTP 412 / 429 | `rate_limited` |
| `-404` / `-62002` / HTTP 404 | `not_found` |
| listing `subtitles` present but not an array, or an entry not normalizable; 200 response that is not a JSON object or whose `body` is unusable | `shape_error` |
| signed-URL fetch HTTP status != 200 | `transport_error` after the single bounded re-list |
| signed-URL fetch HTTP 412 / 429 | `rate_limited` (no re-list) |
| any other upstream error envelope; network failure with no usable response | `response_error` / `transport_error` |

- **The `-101` divergence is intentional.** On the metadata path `-101` stays
  `response_error`; on the subtitle path it means "not visible with this credential", which is
  the same operator fact as "no usable track", so it becomes `not_found`. Both readings are
  pinned by tests so a future unification cannot silently flip one of them.
- `not_found` from either subtitle method reaches the caller as the no-caption outcome; every
  other code reaches it as a failure carrying that code. The caller, not the gateway, owns the
  wording shown to the operator.

### Track preference: family-based, CC before AI, family-blind by construction

Upstream `lan` codes differ between caption kinds for the same spoken language (uploader
Chinese is `zh-CN` / `zh-Hans` / `zh-Hant`; machine Chinese is `ai-zh`), so the default is
defined on a **language family** derived from the two facts the DTO already guarantees —
`language` and `is_ai` — not on a fixed list of exact codes and not on an AI↔CC translation
table:

```python
def language_family(language: str, is_ai: bool) -> str:
    code = language.strip().lower()
    if is_ai and code.startswith("ai-"):
        code = code[3:]
    return code.split("-", 1)[0]
```

- Default: rank families `("zh", "en")` first, then every remaining family in upstream order;
  inside a family prefer CC (`is_ai = False`) over AI; then keep upstream order. Implemented as
  a stable sort on `(family_rank, is_ai, upstream_index)` and taking the first track.
- An explicit language preference is matched **exactly** against the code a probe prints
  (first preference with a match wins; CC before AI inside one preference; then upstream
  order). A valid preference that matches no track yields the no-caption outcome for that
  part — nothing usable *for the requested language* was visible — never a failure.
- **Why it is family-blind:** the rule never enumerates codes and never maps AI codes onto CC
  codes, so for *any* Chinese CC code paired with *any* Chinese AI code, in either upstream
  order, the CC track is selected. A fixed list silently mis-ranks a code upstream adds; an
  equivalence table has to be maintained against upstream vocabulary and can flip without
  warning. The property is pinned by a test table rather than by example.
- The legacy AI-first order (`subtitles._LAN_PREFERENCE`, `("ai-zh", "zh-CN", "zh-Hans",
  "en")`) is deliberately not reused anywhere on the path, and an explicit preference keeps the
  machine track reachable.

### Secret boundary

- `SESSDATA` comes only from `BILI_SESSDATA` / `--sessdata`, is used solely to build the
  package credential, and appears in no DTO, message, log line, fixture, or row; display is
  presence-only.
- Signed subtitle URLs, raw subtitle JSON, cookies, and response bodies stay process-local:
  they may ride an exception chain in memory but never enter a DTO field, a persisted row, an
  exception message, or CLI output.
- The body fetch uses the empty credential precisely so the API credential never reaches the
  CDN host.

## Why this matters

- The negative pin facts are the most expensive part of this contract to re-learn: both
  `need_login_subtitle` and `w_webid` look plausible, one of them is live-required on a
  neighbouring endpoint, and neither belongs here. Without them recorded, the next caller
  "fixes" a working call by adding an invented parameter and invalidates the parity test that
  guards the endpoint mirror.
- `verify=True` reads like a safety check and is in fact a local credential assertion: keeping
  the override is what makes an anonymous probe honest instead of exceptional.
- The raise-versus-drop boundary is what keeps one malformed caption row from destroying a
  usable subtitle, while still refusing to coerce a malformed scalar into a segment.
- The bounded re-list is the difference between surviving signed-URL expiry and either losing
  a caption or spending the risk budget in a retry loop.

## When to apply

- Adding or changing a caption call: mirror the pin's description, keep the overrides
  documented, and extend the seam's recorded call list rather than loosening an existing
  assertion.
- Upgrading `bilibili-api-python`: re-check the endpoint description field for field; a pin
  bump that changes `url`/`method`/`wbi` must fail the parity test loudly.
- Selecting a track: keep the family rule in the service, never in the gateway; the gateway
  reports the inventory and preserves upstream order.
- Reviewing a new failure path: every new outcome must land on one of the five bounded codes,
  and the `-101` divergence must stay pinned in both directions (subtitle and metadata).

## Examples

- `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py` — the only module that
  imports the third-party package; the endpoint mirror, the two overrides, the bounded re-list,
  and the URL normalization live here.
- `bilibili-asr-archive/src/bili_asr/sources/models.py` — `SubtitleTrack` / `SubtitleSegment`
  with their post-init validation and the application-owned gateway protocol.
- `bilibili-asr-archive/src/bili_asr/services/subtitle_ingest.py` — the family preference rule,
  the outcome mapping, and the per-part transaction boundary.
- `bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py` — the endpoint-description
  mirror, scripted track lists and bodies, and the recorded call list (the parity and call-shape
  evidence).
- `bilibili-asr-archive/tests/test_bilibili_api_gateway.py` — normalization, every taxonomy
  row, the single re-list, the `-101` divergence, the import boundary, and the no-leak scans.
- `bilibili-asr-archive/tests/test_live_subtitle_smoke.py` — the opt-in bounded live probe.
- `bilibili-asr-archive/docs/metadata-storage.md` — the operator-facing reading of the same
  behaviour.

## Known limits (as shipped)

- **The legacy client keeps its subtitle methods** for the manifest path until that path is
  retired; the typed gateway is not yet the only subtitle caller in the package.
- **The adapter still binds the whole `user` module**, so a future `user.get_api` could reach
  endpoint descriptions without tripping the forbidden-token scan. Narrowing the import (and
  its allow-list entry) is recorded as deferred work for the next change that touches the
  adapter file.
- **The bounded live probe was recorded against a fixed public sample**, because the host that
  ran it had no archive part to probe; the archive-backed variant is covered offline only, and
  the sample result (`ai-zh`, 2913 segments, monotonic milliseconds) is evidence about that
  part and that credential, not about caption availability in general.
- **A caption inventory is not a promise.** Availability changes with login state, elapsed
  time, and upstream processing, so an empty listing describes this credential at this moment
  and nothing more.

## See also

- [normalized-metadata-stack.md](normalized-metadata-stack.md) — the gateway-boundary layering
  this contract extends: the single-import rule, the bounded exception taxonomy, the DTO
  conventions, and the shared `_await_upstream` mapping (including the metadata path's `-101`
  reading) all live there.
- [normalized-transcript-storage.md](normalized-transcript-storage.md) — where the segments this
  gateway returns are stored, versioned, and enumerated.
- [bilibili-asr-archive-cli.md](bilibili-asr-archive-cli.md) — the operator surface built on
  this contract, including the exit taxonomy and the run-output shapes.
