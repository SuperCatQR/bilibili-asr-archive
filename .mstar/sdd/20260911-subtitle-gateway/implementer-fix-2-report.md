# Plan QC fix wave — implementer report (W1, S1, S4, S5, S8, S9)

- Plan: `20260911-subtitle-gateway` · iteration `iter-2026-09-subtitle-transcript-sqlite`
- Round: fix 2 — the batched actionable items of `review/qc-consolidated.md` (W1 + S1/S4/S5/S8/S9)
- Working branch: `feature/20260911-subtitle-gateway` (worktree `.worktrees/20260911-subtitle-gateway`)
- Base: `6002f99` · Commit: **`9322239`** (working branch only, 4 files, +202/−12; no push; `main` and
  `iteration/iter-2026-09-subtitle-transcript-sqlite` both still at `2bd333f`)
- Live discipline: `BILI_LIVE_SMOKE is: '<unset>'`, no credential file sourced, `BILI_SESSDATA` unset,
  no network call; every run below is offline and the three gated live tests skip (evidenced in §Tests).
- Harness artifacts touched: **only this report file**. Plan / snapshot / status / compass / specs /
  iterations untouched; no residual register entry created or closed.

## Status

**DONE**

## Implemented — per-finding disposition

### W1 (qc3 QC3-001) — one discriminating `floor` vs `round` row — **fixed**

`bilibili-asr-archive/tests/test_bilibili_api_gateway.py:2686-2717`
(new test `test_caption_seconds_are_floored_rather_than_rounded_to_milliseconds`), driven through the
seam exactly like its siblings (`_load_subtitle_gateway` + scripted `subtitle_bodies` →
`fetch_subtitle_segments`).

One row, both endpoints discriminating:

| row (seconds) | `floor` (locked) | `round` (legacy `json_to_srt`) |
|---|---|---|
| `from=3.14159`, `to=3.24159` | `3141`, `3241` | `3142`, `3242` |

The docstring states the discrimination explicitly and names the trap it closes: every other conversion
literal in the module (`0.0/1.0/1.5/2.0/2.5/2.75/3.0`, the drop matrix included) multiplies out exactly,
so a floor→round regression left the suite green. No existing row or assertion was touched.

### S1 (qc1 F-001) — absolute non-`https` signed URLs — **fixed: upgrade chosen, and the normalization made total**

`bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py:76-77` (the two scheme constants) and
`:383-408` (`_read_subtitle_document_url`). The function now has a **total** postcondition — every value it
returns is an absolute `https:` URL:

| `subtitle_url` shape | behaviour |
|---|---|
| `//host/path…` (protocol-relative) | rewritten to `https://host/path…` (unchanged rule) |
| `http://host/path…` | rewritten to `https://host/path…` (**new**) |
| `https://host/path…` | returned unchanged (unchanged rule) |
| absent / non-string / blank | `GatewayShapeError("subtitle track has no document URL")` (unchanged) |
| anything else (`ftp://…`, a bare host, …) | `GatewayShapeError("subtitle track has an unreadable document URL")` (**new**) |

**Why upgrade rather than refuse the `http:` value** (both options were offered by the finding):

1. It is what the spec already says. §1.3 locks "a protocol-relative value is normalized to `https:`
   **inside the adapter**"; the same normalization verb, applied to the absolute non-TLS form, keeps the
   sentence literally true instead of contradicting §1.3's own "sometimes absolute" description (which a
   refusal would have done — and this wave may not amend the spec).
2. It costs the operator nothing defensible. The document fetch carries an explicitly empty `Credential()`,
   so the only thing a cleartext request exposes is the signed URL itself — the document's capability
   token; rewriting the scheme removes that exposure while still returning the operator's caption document,
   where a refusal would turn a legitimate upstream answer into `shape_error`.
3. The upgrade is the *narrower* behaviour: the third-party transport is handed exactly the URL the
   upstream CDN serves under TLS anyway (same host, same path, same query), so no new call shape is
   introduced.

The extra refusal branch is the completion of the same hardening, not a new concern: with it, "every URL the
adapter puts on the wire is TLS" (the finding's expected statement) holds for *every* input rather than for
the `http:` form alone, and the refusal uses the bounded `shape_error` code the spec already assigns to a
listing entry that cannot be normalized (§5 row "an entry not normalizable → `shape_error`"). Disclosed as
the one behaviour change of this wave, in the same function the item names.

Test rows: `:2776-2805` (`test_fetch_subtitle_segments_upgrades_a_plain_http_document_url_to_https` — the
absolute `http:` form is asserted to reach the transport as the scripted `https:` URL) and `:2808-2838`
(`test_fetch_subtitle_segments_rejects_a_document_url_it_cannot_normalize[ftp://…]` and `[…/scheme-less]` —
`shape_error`, static detail, the value absent from the message, and the exact call list proves no document
fetch was issued).

### S4 (qc1 F-004) — stale test docstring — **fixed (docstring only)**

`bilibili-asr-archive/tests/test_bilibili_api_gateway.py:1712-1722` (inside
`test_gateway_imports_stay_on_metadata_surface`). The false sentence ("`User` is deliberately not among
them … never a `user.User` delegate") is replaced by the truthful reading: `User` is not an allow-listed
name of its own because the `user` **module** is bound whole, and the adapter does reach the class through
it (`user.User(uid=mid, credential=self._credential)`, `get_access_id()` serving the optional `w_webid`
route — the attribute the *next* test's positive control requires the scanned source to carry,
`:1778-1780`). The module-wide binding is named as **residual R1**, deferred to the next plan that touches
the module; the page call's own path (endpoint description + package `Api`, not the delegate) is kept,
because that half was true. The delegate was **not** removed — R1 stays a registered defer.

### S5 (qc2 QC2-002) — cancellation contract pinned offline — **fixed**

`bilibili-asr-archive/tests/test_bilibili_api_gateway.py:3033-3058`
(`test_a_cancelled_document_fetch_propagates_instead_of_being_mapped`). The seam's documented
"`BaseException` to raise" form is scripted on the document fetch
(`subtitle_bodies = {SIGNED_SUBTITLE_URL_MARKER: asyncio.CancelledError()}`), then:

- `pytest.raises(asyncio.CancelledError)` — the cancellation reaches the caller instead of becoming the
  bounded `transport_error` the sibling matrix pins for every `Exception` subclass;
- `assert bilibili_api_seam.calls == [_listing_call(), "subtitle.body"]` — the fetch *was* issued (so the
  test cannot pass by never reaching the mapper) and **no re-list followed** it (a rewrite into
  `transport_error` would have armed the adapter's one bounded re-list and spent a second pair).

This is one focused rehearsal; the mapper it pins (`_await_upstream`) is the single catch-all that serves
every adapter call site. No production code changed.

### S8 (qc3 QC3-005) — probe docstring's live-surface bound — **fixed (docstring only)**

`bilibili-asr-archive/tests/test_live_subtitle_smoke.py:33-52`. The understated claim ("the only live
surfaces the probe touches are the player endpoint and the signed document it lists") is gone; the module
docstring now states the real bound, checked against the installed pin before writing it:

- one listing, **WBI-signed**, which the pin's own request loop re-signs and retries on `-403` up to
  `wbi_retry_times` (3 attempts by default — pin `utils/network.py:252, 2365-2386`);
- the document fetch is issued with `wbi=False`, so the pin neither re-signs nor retries it: **one attempt
  per fetch call** (this is *more* precise than QC3-005's suggested "up to 3 attempts via the same loop" —
  the retry branch requires `e.code == -403 and self.wbi`, pin `:2367-2381`);
- the first adapter call in a process bootstraps the pin's process-global `buvid` fingerprint whenever the
  credential carries none — which the document fetch's empty `Credential()` always does — costing up to
  **two further requests** (SPI fingerprint endpoint + its activation POST, pin `:1584-1589, 1884`), once
  per process (module-global cache, pin `:2033-2051`);
- the delivered adapter adds at most one re-list + fetch pair per `fetch_subtitle_segments` call, and only
  on the expiry/transport class.

No behaviour change; the following bullet list ("Default pytest runs skip the probe…") already said the
probe adds no retry of its own, which stays true and is now consistent with the stated bound.

### S9 (qc3 QC3-006) — README documents all three gated tests — **fixed**

`bilibili-asr-archive/README.md:564-582`, immediately under `#### Opt-in bounded live smoke`: a three-item
list naming every test that shares the `BILI_LIVE_SMOKE` switch, verified from the suite (grep for the
switch + the skip run below), not from memory:

1. `tests/test_live_metadata_smoke.py` (real CLI, one public metadata page — the section's existing detail
   follows unchanged);
2. `tests/test_live_subtitle_smoke.py` (**new pointer**) — real subtitle adapter, part resolved from the
   archive with the fixed-sample fallback, bounded facts only, with its run command;
3. `tests/test_bilibili_api_gateway.py::test_live_smoke_single_public_page_for_archive_owner`
   (**new pointer**, the third gated one — pre-existing at base `2bd333f`, adapter-level metadata smoke).

No other README text was modified; the existing metadata-smoke paragraphs (command, credential signal,
expectations) are byte-identical.

## Tests

Interpreter: `/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python` (control checkout;
no `.venv` in the worktree, so `tests/conftest.py`'s `sys.path` insert uses the worktree package).

### Focused run (assignment command, from the worktree package dir)

```
$ cd /root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-gateway/bilibili-asr-archive
$ /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest \
      tests/test_bilibili_api_gateway.py tests/test_live_subtitle_smoke.py -v
329 passed, 2 skipped in 1.22s
```

Baseline before this wave on the same command: `324 passed, 2 skipped` (the 5 new tests are the delta).
New rows, all `PASSED`:

```
tests/test_bilibili_api_gateway.py::test_caption_seconds_are_floored_rather_than_rounded_to_milliseconds PASSED
tests/test_bilibili_api_gateway.py::test_fetch_subtitle_segments_upgrades_a_plain_http_document_url_to_https PASSED
tests/test_bilibili_api_gateway.py::test_fetch_subtitle_segments_rejects_a_document_url_it_cannot_normalize[ftp://aisubtitle.hdslb.com/subtitle.json?sig=1] PASSED
tests/test_bilibili_api_gateway.py::test_fetch_subtitle_segments_rejects_a_document_url_it_cannot_normalize[aisubtitle.hdslb.com/subtitle.json?sig=1] PASSED
tests/test_bilibili_api_gateway.py::test_a_cancelled_document_fetch_propagates_instead_of_being_mapped PASSED
```

### Full offline suite (same interpreter, `-q`, at the committed revision)

```
$ env | grep -i BILI_LIVE_SMOKE ; echo "BILI_LIVE_SMOKE is: '${BILI_LIVE_SMOKE:-<unset>}'"
BILI_LIVE_SMOKE is: '<unset>'
$ /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest -q
1096 passed, 3 skipped in 42.57s
```

Baseline was `1091 passed, 3 skipped`; the delta is exactly the 5 added tests. The 3 skips are the three
gated live tests (no live surface was touched):

```
$ ... -m pytest tests/test_live_metadata_smoke.py tests/test_live_subtitle_smoke.py tests/test_bilibili_api_gateway.py -q -rs
SKIPPED [1] tests/test_live_metadata_smoke.py:329: live smoke is opt-in: set BILI_LIVE_SMOKE=1 to request it
SKIPPED [1] tests/test_live_subtitle_smoke.py:437: live subtitle probe is opt-in: set BILI_LIVE_SMOKE=1 to request it
SKIPPED [1] tests/test_bilibili_api_gateway.py:3300: live smoke is opt-in: set BILI_LIVE_SMOKE=1 to request it
336 passed, 3 skipped in 1.42s
```

### Non-vacuity (revert → fails exactly the new rows; restore → green)

Each mutation was applied to the working tree, run, then reverted; `git diff --check` clean and the
focused suite green again afterwards, and the committed revision is the restored one.

**W1 — `math.floor(milliseconds)` → `round(milliseconds)` in `_read_caption_milliseconds`:**

```
FAILED tests/test_bilibili_api_gateway.py::test_caption_seconds_are_floored_rather_than_rounded_to_milliseconds
E  At index 0 diff: SubtitleSegment(start_ms=3142, end_ms=3242, text='向下取整')
   != SubtitleSegment(start_ms=3141, end_ms=3241, text='向下取整')
1 failed, 328 passed, 2 skipped
```

One failure, and it is the new row — which is also the independent confirmation of QC3-001's premise: the
other 328 tests stay green under `round`.

**S1 — pre-fix `_read_subtitle_document_url` restored (only the `//` rewrite):**

```
FAILED tests/test_bilibili_api_gateway.py::test_fetch_subtitle_segments_upgrades_a_plain_http_document_url_to_https
FAILED tests/test_bilibili_api_gateway.py::test_fetch_subtitle_segments_rejects_a_document_url_it_cannot_normalize[ftp://aisubtitle.hdslb.com/subtitle.json?sig=1]
FAILED tests/test_bilibili_api_gateway.py::test_fetch_subtitle_segments_rejects_a_document_url_it_cannot_normalize[aisubtitle.hdslb.com/subtitle.json?sig=1]
3 failed, 326 passed, 2 skipped
```

The upgrade row fails on `GatewayTransportError` — the pre-fix adapter hand
`http://…` to the transport verbatim, which is the clear-channel behaviour the finding described. The
pre-existing protocol-relative test stays green under this mutation, so the new rows are the ones carrying
the new rule.

**S5 — `except Exception` → `except BaseException` in `_await_upstream`:**

```
FAILED tests/test_bilibili_api_gateway.py::test_a_cancelled_document_fetch_propagates_instead_of_being_mapped
E  bili_asr.sources.models.GatewayTransportError: GatewayTransportError(transport_error): fetch_subtitle_segments
1 failed, 328 passed, 2 skipped
```

The traceback shows the widened catch-all rewriting the cancellation into `transport_error` — exactly the
regression the new rehearsal exists to catch.

## Files changed

| File | Change |
|---|---|
| `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py` | S1: two scheme constants (`:76-77`), total URL normalization + one new bounded shape error (`:383-408`) |
| `bilibili-asr-archive/tests/test_bilibili_api_gateway.py` | W1 test (`:2686-2717`), S1 tests (`:2776-2805`, `:2808-2838`), S5 test (`:3033-3058`), S4 docstring re-word (`:1712-1722`) |
| `bilibili-asr-archive/tests/test_live_subtitle_smoke.py` | S8: module docstring states the real live-surface bound (`:33-52`) |
| `bilibili-asr-archive/README.md` | S9: all three `BILI_LIVE_SMOKE`-gated tests listed (`:564-582`) |

`git diff --check` clean. No files outside `bilibili-asr-archive/` changed; nothing in `.mstar/` changed
except this report.

### Assertion disclosure (added / changed / removed)

- **Added assertion statements: 10**, executing 14 times (the refusal test's 4 statements run twice) — W1 (2: the exact
  segment tuple with `3141/3241`, the exact call list);
  S1 upgrade (3: segment text, the transport URL equals the scripted `https:` URL, the exact call list);
  S1 refusal ×2 rows (4 each run: `code == "shape_error"`, the exact new `detail`, the value absent from
  `str(exc)`, the exact single-listing call list); S5 (1 assertion plus the `pytest.raises` type pin).
- **Changed assertions: 0.** `git diff -U0` over `tests/` shows every removed line is docstring prose
  (S4's three lines, S8's five lines). No assertion was weakened, deleted, or relaxed anywhere.
- **Production behaviour changed: 1 site** — the URL normalization above (S1, the item that authorizes it).
  Everything else in the adapter is docstring/comment only.

## Self-review notes

1. **S1's refusal branch is the one judgement call.** I chose "upgrade `http:` **and** refuse what cannot be
   normalized", rather than "upgrade only". Rationale in §S1; the refused shapes (`ftp://…`, bare host,
   malformed `https:/…`) are not forms the spec or the pin can produce, so the branch is unreachable in
   practice and exists to make the TLS postcondition total and testable. If the re-review prefers the
   minimal reading, dropping `:407-408` (the final `raise`) and the two refusal rows reverts to
   upgrade-only without touching any other assertion — the upgrade row is what the item literally asked for.
2. **W1 is one row, not a matrix.** The row's two endpoints discriminate independently; adding more rows
   would duplicate the same property (and `0.0015`-style rows are hazardous to *assert*: Python's `round`
   is banker's rounding, so `2.5 → 2`, which can turn a discriminating row into a dropped one and blur the
   failure message).
3. **W1 was not extended to the metadata path's `duration_ms`** (`:225-234`, the same `floor` rule). That
   literal is not this finding's anchor (QC3-001 enumerates subtitle conversion sites only) and it is not
   part of this branch's diff; flagging it here rather than changing it keeps the wave surgical.
4. **S4** now describes the code as it is, including R1's module-wide binding, without reopening R1
   (`defer`, target unchanged, register untouched). The docstring names the residual so the next plan that
   touches the adapter reads the same record the register carries.
5. **S5 asserts no re-list**, which is the property with real cost: a swallowed cancellation would spend two
   more live requests inside a cancelled task. The test uses the seam's existing `BaseException` scripting,
   so no fixture change was needed (no modification to `tests/fixtures/fake_bilibili_gateway.py`).
6. **S8 corrects the finding's own suggested wording** where the pin disagrees with it (the document fetch
   is not retried: `wbi=False` short-circuits the pin's `-403` retry branch). Stated in §S8 with the pin
   anchors; the docstring is the accurate version.
7. **S9's third test was verified from the suite**, not from the finding's line hint: the skip run lists
   `tests/test_bilibili_api_gateway.py:3300` (the adapter-level metadata smoke) alongside the two modules,
   and the README names it by node id so the list cannot drift silently.
8. **No live surface was exercised**: `BILI_LIVE_SMOKE` unset in every run, no `.env` sourced, no
   credential value read or printed; the probe module's only change is its docstring.
