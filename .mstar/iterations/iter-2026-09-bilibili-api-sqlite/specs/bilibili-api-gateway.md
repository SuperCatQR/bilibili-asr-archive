# Bilibili API Gateway Specification

## Intent

Use the documented `bilibili-api-python` package as the only external metadata
client, while preventing its return dictionaries from leaking into storage or
service code.

## Dependency contract

- Pin `bilibili-api-python==17.4.2`.
- Maintain a reproducible `uv.lock`.
- The only module importing `bilibili_api` is
  `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py`.
- Gateway construction accepts an optional credential value from configuration;
  it never writes or logs the value.
- Network access is not used by repository/unit tests; tests inject a fake
  gateway implementing the same protocol.

## Typed gateway interface

```python
@dataclass(frozen=True)
class UserVideoPage:
    mid: int
    page_number: int  # One-based, as requested from API
    videos: tuple[VideoSummary, ...]
    observed_total: int | None  # Total count from API when present

@dataclass(frozen=True)
class VideoSummary:
    bvid: str  # Required, non-empty
    aid: int | None  # Optional; may be missing from list response
    title: str  # Required, non-empty after trim
    pubdate: int  # Published timestamp
    mid: int  # Owner MID; must match requested user

@dataclass(frozen=True)
class VideoPart:
    bvid: str  # Parent video BVID
    page_index: int  # Zero-based; converted from one-based API page
    cid: int  # Required, positive
    title: str  # Required, non-empty after trim
    duration_ms: int  # Required, positive; floor(api_seconds * 1000)

class BilibiliGateway(Protocol):
    async def get_user_video_page(self, mid: int, page_number: int,
                                  page_size: int = 30) -> UserVideoPage: ...
    async def get_video_parts(self, bvid: str) -> tuple[VideoPart, ...]: ...
    
    async def get_completed_video_summary(self, summary: VideoSummary) -> VideoSummary: ...

    def get_package_version(self) -> str: ...
```

The protocol is application-owned. The adapter maps third-party fields into
these DTOs and validates required values before returning. `get_package_version()`
returns the pinned `bilibili-api-python` version for run metadata.

## Required upstream calls

> **Transport amendment (2026-09-11, plan `20260911-live-metadata-path-fix`).** The
> one-page user-video call is issued through the pinned package's WBI-signed `Api`
> (`GET x/space/wbi/arc/search`, `wbi=True`, `dm=False`) with the same parameter set the
> library uses, and `w_webid` always present — a non-empty `access_id` when the package
> can supply one, otherwise the empty string. The `User.get_videos(...)` delegate is no
> longer used: its API config carries `dm: True` and its `w_webid` arrives as `None` when
> the dynamic-page scrape yields nothing, and that combination is rejected by upstream
> risk control with HTTP 412 in this environment (order-swapped reproduction in the
> plan's §Problem D3). DTOs, normalization rules, ownership checks, and the bounded error
> taxonomy below are unchanged.
>
> **Page-size bound (2026-09-11, same plan).** The one bounded page uses
> `ps=30` — the pinned library's own documented `const int: 30` and its `get_videos`
> default (the pre-existing `bili_client.py` also fetches with 30, and the legacy client is
> unaffected). Live probes with the corrected call shape: `ps=30` and `ps=50` return
> `code=0`, while `ps=100` is rejected (HTTP 412, and JSON `-400` on three production
> runs). Cursor semantics stay page-based, so the bound only changes how many videos a
> page carries.


1. One bounded page of the user's videos, `ps=30` (see the page-size bound note below), issued through the WBI-signed `Api` shape described in the transport amendment.
   This returns video summaries including `bvid`, `aid`, `title`, `pubdate`, and owner `mid`.
2. `video.Video(bvid=bvid).get_info()` only when the summary from `get_videos` lacks
   `aid` (nullable field). Do not call `get_info` speculatively; use it only to fill
   required gaps in the summary. The ingestion service decides when to call this method.
3. `video.Video(bvid=bvid).get_pages()` for page-aware part records. This returns an
   array where each element has `page` (one-based), `cid`, `part` (title), and
   `duration` (seconds).

The gateway must not call subtitle or playback APIs in this iteration.

## Normalization rules

- Reject an item without a non-empty `bvid`.
- Convert Bilibili one-based `page` to zero-based `page_index` using `page_index = page - 1`.
- Convert `duration` seconds to integer `duration_ms` using `duration_ms = floor(duration_seconds * 1000)`.
  This ensures consistent millisecond precision without rounding up partial milliseconds.
- Preserve Bilibili `aid` when present; `None` is allowed when the API response omits it.
- Use the owner `mid` from the requested user as the ownership check; a detail
  response with a different owner is reported as a bounded gateway error. For `VideoPart`
  DTOs, ownership is validated transitively through the parent video's `mid` before
  returning parts.
- Strip no user-visible title content except surrounding whitespace; reject an
  empty result after trimming.
- Do not retain the original response dictionary.

## Pagination and retry boundary

The ingestion service owns cursor advancement and run/page persistence. The
adapter exposes one page per call so a failed page cannot advance the cursor.
The adapter may use the library's own request behavior but must translate errors
into a small exception taxonomy:

- `GatewayRateLimited(code)`
- `GatewayNotFound(code)`
- `GatewayResponseError(code)`
- `GatewayTransportError(code)`
- `GatewayShapeError(code)`

Only bounded scalar `code` values can be persisted. Raw exception text remains
process-local.

## Credential boundary

`SESSDATA` may be passed to the library's `Credential` object when supplied by
`BILI_SESSDATA` or a CLI option. It is never included in DTOs, database rows,
logs, error messages, fixtures, or URLs. The live smoke test uses public metadata
and does not require a credential.

## Test seam

A fake gateway must be able to return scripted pages and parts, including:

- duplicate video summaries across repeated pages;
- a multipart video;
- an empty page;
- a bounded rate-limit error;
- malformed item data.

The fake gateway must not import `bilibili_api` or make network calls.

## Acceptance evidence

- Signature/behavior smoke against the pinned package is recorded in a test or
  report without storing returned raw payloads.
- Fake gateway tests prove DTO validation and repository integration.
- A live one-page run for UID 23191782 is bounded to one page and a temporary
  database; no playback/subtitle endpoints are called.

## References

- User-supplied docs: https://nemo2011.github.io/bilibili-api/#/modules/user
- Package: https://pypi.org/project/bilibili-api-python/
- Primary plan: `.mstar/plans/20260909-bilibili-api-ingestion.md`

## Status

Iteration-scoped draft; becomes locked after Phase 1 review chain and PM lock.
