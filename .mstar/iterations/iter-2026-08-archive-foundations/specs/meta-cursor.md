# Data contract: `meta-cursor.json`

Iteration-scoped draft. Companion to `archive-foundations-architecture.md`. Plan `20260824-cursor-based-resume` only. Not `{SPECS_DIR}`.

## Ownership

- Module name locked: `bili_asr.meta_cursor.MetaCursorStore`
- Path locked: `{archive_root}/meta-cursor.json` (archive root, not under `manifest/`)
- Writers: `_cmd_fetch_meta` after a successful page merge into JSONL, and on risk exhaustion before exit 2
- `BiliClient` never imports this module

## Schema

JSON object, one cursor per archive root (personal single-mid tool). Keyed in document by `mid`.

| Field | Type | Meaning |
|-------|------|---------|
| `mid` | `int` | UP mid this crawl enumerates |
| `next_page` | `int` | next 1-based `pn` to request (`fetch_pages(..., start_page=next_page)`) |
| `total` | `int \| null` | last observed `page.total` |
| `state` | `str` | see enum |
| `last_api_error_code` | `int \| str \| null` | redacted risk/API code only |
| `updated_at` | `str` | UTC ISO-8601 |

### `state` enum (locked)

| Value | Resumable by `--resume` | Terminal summary |
|-------|-------------------------|------------------|
| `running` | no (crash mid-write should not persist; in-memory only) | n/a |
| `risk_interrupted` | **yes** | incomplete; continue at `next_page` |
| `limited` | **no** automatic | not full enumeration; retain `next_page` for a future intentionally broader run |
| `complete` | **no** | visible archive fully enumerated |

`--resume` loads the sidecar only when `state == risk_interrupted` and `mid` matches. Without `--resume`, a new run replaces a stale cursor (including leftover `risk_interrupted`) after writing the first successful page of the new run.

A deliberate `max_pages` cap sets `state=limited` and `next_page = last_fetched_pn + 1` (or the pn that was not requested). Summary text must not say complete.

Full exhaustion (`total` reached or empty-streak stop with no risk) sets `state=complete`. `next_page` may remain last+1 but is not consumed by `--resume`.

Risk budget exhaustion: persist `state=risk_interrupted`, `next_page` = the `pn` that failed or was not merged (`BiliClient.last_failed_page`), `last_api_error_code` set, process exit 2.

Advance rule: persist cursor **after** the corresponding `ManifestStore` merge for that archive list page succeeds. Never mark a failed page complete. Never duplicate bvid/`work_id` rows; `merge_pages` / upsert remain last-write-wins per key.

## Atomic replace

Same-directory temp file + `os.replace`, matching `ManifestStore.save`. No partial sidecar on disk.

Forbidden contents: cookies, SESSDATA, signed URLs, raw exception messages, request dumps.

## `fetch_pages` seam

```python
def fetch_pages(self, mid: int, max_pages: int | None = None, start_page: int = 1) -> list[list[dict]]:
```

CLI computes `start_page` from cursor; client only iterates `pn`.
