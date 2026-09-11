# Task 1 Review — Subtitle DTOs, protocol methods, and seam extension

- Plan: `20260911-subtitle-gateway` (iteration `iter-2026-09-subtitle-transcript-sqlite`)
- Task: 1 of 3 — SDD per-task review (L2)
- Review mode: Mode A, diff-first
- Review range: `2bd333f..73fdef0` (diff `review/task-1-diff.md`, 3 files, +854/−35)
- Worktree: `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-gateway`
  on `feature/20260911-subtitle-gateway` (read-only seat: no commit, no branch change,
  no worktree mutation; the only file written is this report)
- Authoritative spec: `.../iter-2026-09-subtitle-transcript-sqlite/specs/subtitle-gateway.md` §1–§3, §8
- Findings cleanup: zero-residual (PM owns disposition; this report only)

**Task quality: Approved** — 0 Critical, 0 Important, 4 Minor.

## Spec Compliance

✅ **Spec compliant.** The diff stays inside the task's three-file list and inside the brief's
four checkboxes; no constraint in the plan's Global Constraints is violated by the diff.

| Brief item / plan constraint | Verdict | Evidence (post-change line numbers) |
|---|---|---|
| `SubtitleTrack(language, label, is_ai, track_id)` frozen, validated, no `work_id`/URL | ✅ | `src/bili_asr/sources/models.py:95-122`; field set pinned exactly at `tests/test_bilibili_api_gateway.py:1503-1521` |
| language/label non-empty after trim; non-empty primary subtag; `track_id` non-empty str or `None` | ✅ | `models.py:113-122`; 14 rejection cases `test_...py:1521-1549`; probe evidence below |
| `SubtitleSegment(start_ms, end_ms, text)`: `start_ms >= 0`, `end_ms > start_ms`, text non-empty after trim | ✅ | `models.py:125-143`; 13 rejection cases `test_...py:1561-1586` |
| Two protocol methods added; four shipped signatures untouched | ✅ | `models.py:162-176`; exact param-tuple pin `test_...py:1600-1622`; the shipped `page_size=30` default re-pinned by the pre-existing `test_...py:357-372` |
| Seam: `FAKE_PLAYER_ENDPOINT` literal mirror (`dm: True`), scripted `subtitles[]`, scripted bodies (absolute + protocol-relative), recorded call list of flags + params | ✅ | `tests/fixtures/fake_bilibili_gateway.py:110-124` (mirror), `:704-740` (factories), `:256-257,294,300-302` (script fields), `:524-542` (`_record`) |
| Every existing exact call-list assertion preserved | ✅ | Removed-lines audit (below): the only existing assertion touched is `_public_names(video) == ["Video"]` → `["API","Video"]` |
| Only `sources/bilibili_api_gateway.py` imports `bilibili_api` | ✅ | `models.py` imports unchanged (no package import); AST test `test_only_the_gateway_module_imports_bilibili_api` **PASSED** in my run (`test_...py:1649-1658`) |
| Reuse the existing bounded taxonomy; no new vocabulary | ✅ | No new code strings; new failures are `TypeError`/`ValueError` DTO validation in the shipped `_text`/`_integer` style (`models.py:17-30`) |
| No signed URL / raw JSON / cookie / traceback in DTOs, messages, logs, fixtures, rows | ✅ (one Minor caveat) | DTO field sets pinned; `has_sessdata` is presence-only (`fixture:539`); `assert SESSDATA_BOUNDARY_VALUE not in repr(request)` (`test_...py:1883`); `SIGNED_SUBTITLE_URL_MARKER` joined `NO_LEAK_MARKERS` (`fixture:162-168`) with a positive control (`test_...py:2111-2139`). Caveat → Minor 2 |
| All tests offline | ✅ | Focused run: `179 passed, 1 skipped` (the skip is the live smoke); every new test drives the fake package directly |
| DTO/seam tests do not rely on the real package | ✅ | `build_fake_package` is driven directly (`_seam_transport`, `test_...py:1803-1807`); the pin is imported only by the two parity probes, which fail loudly rather than skip (`_require_installed` → `pytest.fail`, `test_...py:247-256`) |
| Non-vacuity (rules fail if reverted) | ✅ | Empirical probe below: every tested input is rejected by the named rule |

### PM context items — independent verdict

1. **F1 wording correction is faithful to the pin.** Read directly out of the installed
   distribution: `bilibili_api/utils/network.py:2099-2150` — the `Api` dataclass fields are
   `url, method, comment, wbi, dm, verify, no_csrf, json_body, ignore_code, sign, data, params,
   files, headers, credential`; **`raw` is not a constructor field**. `request(self, raw=False,
   byte=False)` is at `:2353-2356`; `result` is `await self.request()` with no arguments
   (`:2389-2393`); `_request(raw=..., byte=...)` at `:2324`. The spec's dated note
   (`specs/subtitle-gateway.md:104-111`) and the plan's note + Task-2 wording
   (`plans/20260911-subtitle-gateway.md:46-48,169`) are correct, and the implementer's seam
   **refuses `raw` at construction** (`fixture:448-469`) while mirroring the pin's `request`
   signature (`fixture:477`) — so the encoding does not mislead Task 2. The seam even pins the
   refusal against the installed pin (`test_...py:2051-2077`: `mirrored_fields <= pin fields`,
   `"raw"/"byte" not in mirrored_fields`, `mirrored_request == pinned["request"]`).
2. **Exactly one existing assertion changed, still exact equality.** `grep '^-[^-]'` over the
   diff returns 34 removed lines: 31 are docstring/comment rewrites in the fixture and the test
   module header, 3 are the page-route lines moved verbatim into `_user_video_page_result()`
   (`page_number`/`page_size`/the identical `space.arc.search(pn=…, ps=…)` token), and 1 is
   `assert _public_names(modules["bilibili_api.video"]) == ["Video"]` →
   `== ["API", "Video"]` (`test_...py:1729`) — still exact equality, not loosened. No other
   assertion deleted, weakened, or made vacuous. The seam's routing change (any URL → page
   payload, now: page/player routes at their description URLs, signed document only with
   `raw=True`, anything else raises) **strengthens** the seam; all pre-existing exact call-list
   assertions keep their tokens.
3. **Locked signalling encoded exactly, nothing broader.** `models.py:162-176` states
   per-method: empty tuple is an observation, never `not_found`; the body fetch raises
   `GatewayNotFound` and is never an empty tuple. No placeholder track, no empty-success
   path, no new error code. It is comment + signature only at this stage (see ⚠️ 1).
4. **Non-vacuity spot-checks all hold** (static + empirical probe):
   `end_ms > start_ms` (`models.py:141`), non-empty primary subtag (`:116-117`),
   `is_ai` boolean (`:119-120`), `track_id` non-empty (`:121-122`), and the seam's exact
   per-route tokens (`fixture:385,398,409` → `test_...py:1884,1975,2007`). Removing any one of
   them fails the corresponding assertion.

## Strengths

- **The pin is the oracle, not a copied comment.** `FAKE_PLAYER_ENDPOINT`
  (`fixture:110-124`) is verified field-for-field against the installed distribution
  (`test_...py:2079-2108`), and `_require_installed` **fails** (not skips) when the pin cannot
  be read — so the parity contract cannot pass vacuously. I reproduced the pin's own
  `data/api/video.json → info.get_player_info` and it matches the mirror exactly
  (`dm: true`, `verify: true`, `wbi: true`, query fields under `data`, same `comment`).
- **The seam is stricter than the pin, not looser.** Constructor fields are a subset of the
  pin's (`test_...py:2070-2077`), `request`'s signature is compared parameter-by-parameter with
  the pin's, `byte=True` fails loudly, and the "raw on the wrong route" cases raise instead of
  answering `None` — exactly the offline/live drift class this seam exists to prevent.
- **Anti-vacuity controls are shipped with the features.** The `dm` fingerprint positive
  control (`test_...py:1897-1929`), the unscripted-URL loud failure with the protocol-relative
  form (`:1986-2014`), the SESSDATA-presence assertion plus `repr` leak check (`:1880-1883`),
  and the no-leak sentinel control (`:2111-2139`) keep the downstream "asserted on the recorded
  call" claims honest.
- **Red-first evidence is real and the arithmetic reconciles.** Focused baseline 136 → 179 is
  exactly the 43 cases in the diff (1 + 14 + 1 + 1 + 13 + 1 + 1 + 11 = 43), and I reproduced
  `179 passed, 1 skipped in 0.87s` (skip = live smoke) with the sanctioned command.
- **Surgical scope.** Only the three files in the brief; `models.py` untouched elsewhere; the
  adapter is deliberately not touched (Task 2 owns it); taxonomy, guards, and `__all__` style
  reused rather than reinvented.

## Issues

### Critical

None.

### Important

None.

### Minor

1. **The protocol-surface test is one-directional — "exact whole-surface" overstates it.**
   `tests/test_bilibili_api_gateway.py:1600-1622` builds `declared` by iterating the `expected`
   keys only, so a *seventh* protocol method (or a new public protocol attribute) added later
   would not fail it; removal is still caught (`getattr` raises). The four shipped signatures
   and the two new ones are pinned exactly, so the plan's actual constraint ("the shipped four
   methods' signatures stay untouched") is enforced. The implementer report's wording ("a new
   exact whole-surface test", report line 40) should be read as "the locked six signatures".
   Cheap hardening if the PM wants it: compare against
   `{n for n in vars(BilibiliGateway) if not n.startswith('_')}`.
2. **The protocol-relative sentinel is not itself scannable.**
   `fixture:146-153` adds the *absolute* marker to `NO_LEAK_MARKERS`, but
   `PROTOCOL_RELATIVE_SUBTITLE_URL` does not contain the absolute marker as a substring
   (verified: `"https://…" in "//…"` → `False`), so a leak that carried the un-normalized
   upstream value would pass `assert_leaks_no_markers`. Mitigation already present:
   `make_subtitle_track()` scripts every track with the absolute form (`fixture:704-721`), so
   the common path is caught, and the no-leak scans are Task 2's assertions anyway. Optional
   hardening for Task 2: also scan the scheme-less prefix (host+path, or the
   `SIGNED-SUBTITLE-URL-THAT-MUST-NOT-LEAK` tail).
3. **`sources/__init__.py` was not extended (implementer F2) — compliant, but the package
   docstring is now inaccurate.** `src/bili_asr/sources/__init__.py:1-34` still says it
   "Re-exports the application-owned DTOs" while `SubtitleTrack`/`SubtitleSegment` are only on
   `bili_asr.sources.models` (`models.py:238-239`). This is *inside* the task's authority
   boundary (the plan's File list is exactly three files, and spec §2 names
   `bili_asr.sources.models`), and no test asserts package-root completeness — so no assertion
   is broken. PM call: either add the four-line re-export in Task 2/3 (the consuming tasks) or
   leave consumers on the module path.
4. **Commit-subject discrepancy between two harness artifacts (not verified — git not re-run
   per the read-only brief).** `implementer-task-1-report.md:9` records
   `feat(subtitles): add the subtitle DTOs, protocol methods, and the player seam`;
   `progress.md:5` records `feat(sources): add subtitle DTOs, protocol methods, and seam
   scripting` for the same `73fdef0`. Bookkeeping only; the PM owns the ledger.

## ⚠️ Cannot verify from diff (PM / Task 2 to check)

1. **The locked no-track signalling has no executable assertion yet.** Task 1 encodes it as
   protocol comments (`models.py:162-174`); "possibly empty tuple" and "never empty on the body
   fetch" are Task-2 runtime properties and cannot be asserted at DTO/protocol level here. Task
   2's tests must pin both (spec §2.1), including "an all-degenerate document is `not_found`,
   never `shape_error`".
2. **Spec §8's adapter-side obligations are still open by design**: "the adapter reads
   `url`/`method`/`wbi` from the description and its only overrides are `dm=False`/`verify=False`
   — asserted on the recorded call". Task 1 ships the *capability* (`FakeApiRequest.raw`/
   `has_sessdata`, ordered `api_requests`, exact `calls` tokens) and proves it with hand-driven
   seam tests; the adapter-facing assertion lands in Task 2.
3. **`DOCUMENTED_METADATA_CALLS` does not cover the two new tokens, and `FakeGateway` lacks the
   two methods (implementer F3).** `fixture:132` lists only `space.arc.search` /
   `video.get_info` / `video.get_pages`; `assert_only_documented_metadata_calls` (`fixture:762-773`)
   is applied to `script.calls` in `test_metadata_e2e.py:310,582` and
   `test_metadata_ingest.py:708,853`. Task 2 must extend the documented set with
   `player.track_list` / `subtitle.body` (or those tests will flag legitimate subtitle calls)
   and extend the protocol double where it scripts subtitle calls. Accepted scope discipline for
   Task 1; must not be forgotten.
4. **A pre-existing AST test constrains Task 2's helper naming.** 
   `test_gateway_source_never_names_forbidden_seam_methods`
   (`tests/test_bilibili_api_gateway.py:1693-1719`) flags any `ast.Attribute` in the adapter
   source whose name contains `subtitle|player|…`. The natural Task-2 implementation
   (`self.get_subtitle_tracks(...)` from inside `fetch_subtitle_segments`, or a
   `self._subtitle_document_result(...)` helper) **will fail** this untouched test. Task 2 must
   route the shared listing/document logic through neutrally named helpers (e.g.
   `self._list_tracks(...)`, `self._fetch_document(...)`) or the PM must explicitly authorize a
   deliberate, documented update — not a silent narrowing of that scan. Flagging now so it is a
   design decision, not a surprise mid-task.
5. **Field-level trimming is Task 2's job.** The DTO validates non-empty-after-strip but stores
   the value verbatim: `SubtitleTrack("  zh-CN  ", "  中文  ", False, None)` is **accepted**
   (probe below). Spec §2 labels `language`/`label` "trimmed" and §6 promises they are
   "printable as-is", and the shipped metadata adapter already normalizes this way
   (`bilibili_api_gateway.py:147,199` → `title=title.strip()`). Task 2 must strip `lan`/`lan_doc`
   before construction (and must **not** strip segment `text`, which §3 passes through verbatim).
6. **Full-suite numbers are implementer evidence.** `946 passed, 2 skipped` was not re-run
   (assignment: no full-suite re-run). I re-ran only the sanctioned focused command and got
   `179 passed, 1 skipped in 0.87s`, exactly as claimed; the +43 delta reconciles with the diff's
   parametrizations.

## Evidence collected (this review)

- Focused gate command (exactly as sanctioned):
  `cd .worktrees/20260911-subtitle-gateway/bilibili-asr-archive && …/.venv/bin/python -m pytest tests/test_bilibili_api_gateway.py -v`
  → `179 passed, 1 skipped in 0.87s`; all parity/seam/DTO tests `PASSED`; the only skip is
  `test_live_smoke_single_public_page_for_archive_owner`.
- Pin reads (read-only, no network): `Api` dataclass fields at `utils/network.py:2136-2150`
  (no `raw`); `request(self, raw=False, byte=False)` `:2353`; `result → await self.request()`
  `:2389-2393`; `update_params` sets `self.params = kwargs` `:2172-2180`;
  `video.py:38 API = get_api("video")`; `data/api/video.json → info.get_player_info` equals
  `FAKE_PLAYER_ENDPOINT` exactly.
- Removed-lines audit: 34 removed lines, all accounted for (31 docstring/comment, 3 relocated
  page-route lines, 1 exact-equality surface list).
- Non-vacuity probe (non-mutating, `PYTHONPATH=src`, DTOs imported directly):
  `-zh` → `ValueError: language must carry a non-empty primary subtag`;
  `  -zh` → same; `is_ai='ai'`/`1` → `TypeError: is_ai must be a boolean`;
  `label='   '` → `ValueError: label must not be empty`; `track_id='  '` → `ValueError:
  track_id must not be empty`; `end==start`/`end<start` → `ValueError: end_ms must be greater
  than start_ms`; `start=-1` → `ValueError: start_ms must be at least 0`; `text='   '` →
  `ValueError: text must not be empty`; `start=True` → `TypeError: start_ms must be an integer`;
  and `SubtitleTrack("  zh-CN  ", "  中文  ", …)` is accepted untrimmed (⚠️ 5).
- Every rule tested above is the *sole* rejector for its input, so reverting any of them makes
  the corresponding parametrized case fail — the new assertions are non-vacuous.

## Assessment

**Task quality: Approved.**

Task 1 delivers exactly the slice the plan scoped: two validated frozen DTOs with the locked
field sets, the two protocol methods with the shipped four signatures untouched, and a fake seam
that mirrors the pin's player endpoint, scripts tracks/documents (both URL forms), and records
every call with its flags, `raw` argument, and credential *presence* — with anti-vacuity controls
and pin-backed parity tests. No constraint is violated; the one existing assertion that changed
remains exact; nothing was weakened to make room. The four Minor items and the six ⚠️ items are
handoff quality — none of them blocks Task 2, but ⚠️ 3, 4 and 5 should be read by the Task-2
implementer *before* it starts, since they change how the adapter must be written.

No blocked item; no residual claimed by this reviewer (PM owns disposition under `zero-residual`).
