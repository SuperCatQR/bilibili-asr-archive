---
report_kind: qc
reviewer: qc-specialist
reviewer_index: 1
plan_id: "20260911-subtitle-gateway"
verdict: "Approve"
generated_at: "2026-09-11"
---

# Code Review Report

## Reviewer Metadata

- Reviewer: @qc-specialist
- Runtime Agent ID: qc-specialist
- Runtime Model: standard tier (leaf seat; the concrete provider/model id is not exposed in-session)
- Review Perspective: contract fidelity and module boundaries on the whole branch (QC1: Modularity Lens + Contract Lens), seat 1 of 3
- Report Timestamp: 2026-09-11T14:12+08:00

## Scope

- plan_id: `20260911-subtitle-gateway`
- Review range / Diff basis: `2bd333f..6002f99` (base = the iteration integration branch at feature cut; 4 commits)
- Working branch (verified): `feature/20260911-subtitle-gateway` (`git branch --show-current`)
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-gateway` (`git rev-parse --show-toplevel`)
- Files reviewed: **6** changed files (every file in the range), plus the plan with its recorded PM authorizations, the three locked iteration specs (`subtitle-gateway` primary, `transcript-storage`, `subtitle-cli-contract`), the three task reviews + the Task-3 `## Revalidation`, the four implementer reports, `progress.md`, `projects/_default/residuals.json`, the pinned distribution's own data and source in the control `.venv`, and the previous plan's QC-1 report for style calibration
- Commit range: identical to the Review range — `git rev-list --count 2bd333f..6002f99` = 4, `HEAD = 6002f99bc0aa4f1abfde6bb111a8e5ebef7d8adc`, `git status --porcelain` empty, `git diff --check 2bd333f..6002f99` clean (exit 0, run read-only by this seat), and `2bd333f` is contained in `iteration/iter-2026-09-subtitle-transcript-sqlite` (`git branch --contains`), so the base really is the integration branch at cut
- Diff-basis integrity: the fenced body of `review/branch-diff.md` is **byte-identical** to `git diff 2bd333f..6002f99` (6/6 `diff --git` headers; compared via process substitution) — the evidence channel is intact
- Deep review: **triggered** (S1: 3172 insertions / 6 files ≥ 200 lines; S6: the diff spans `sources/` (3 modules) + `tests/fixtures/` + `tests/` package boundaries; S3 secondary: the gateway's subtitle-acquisition contract is not yet a `{KNOWLEDGE_DIR}` topic — the four tracked docs mention subtitles only for the legacy path)
- Lenses applied: **Contract Lens, Modularity Lens, Standards Lens, Testing Lens** (+ a Real-Entry-Path check on the live probe module)
- Analysis methods: `git diff` / `git show` / `git log` / `git rev-list` / `git merge-base` / `git branch --contains` / read / grep, plus comparison of every locked call-shape clause against the **installed pin's own** `data/api/video.json`, `utils/network.py`, and `video.py`. **No** test, build, lint, install, git mutation, or live-network run; `BILI_LIVE_SMOKE` never set; the credential file was never sourced; no credential value was read, printed, or inferred (the only value-shaped hit anywhere in the range is the probe's presence-only render, see §Verified clean 9).

## Findings

### 🔴 Critical

None.

### 🟡 Warning

None.

### 🟢 Suggestion

- **[F-001] `_read_subtitle_document_url` normalizes only the protocol-relative URL form, so an absolute non-`https` signed URL is forwarded verbatim to the transport (`src/bili_asr/sources/bilibili_api_gateway.py:374-388`)** → upgrade an absolute `http://` value to `https://` (or reject a non-`https` value as `GatewayShapeError`), plus one offline test row; or record the scheme rule explicitly in spec §1.3.
  - Source Type: deep-lens: Contract Lens (secret/payload boundary) + Security-adjacent read
  - Verification: read + grep anchors — the normalizer's only rewrite is `if normalized.startswith("//"): normalized = f"https:{normalized}"` (`bilibili_api_gateway.py:385-388`); the returned value is handed straight to the package transport by `_fetch_subtitle_document` (`:743-750`, `url=url` with `credential=Credential()`); the spec says the field is "sometimes protocol-relative (`//...`) and sometimes absolute" without constraining the absolute scheme (`specs/subtitle-gateway.md:97-98`), and locks only the `//` case (`:98-99`); the seam scripts only the `https` absolute form plus its `//` twin (`tests/fixtures/fake_bilibili_gateway.py:156-163`), so a non-`https` absolute value is untested on both paths
  - Expected vs observed: expected — every URL the adapter puts on the wire is TLS, or a non-TLS value is refused at the boundary; observed — an `http://…` value would be fetched in clear (the request carries no credential by design, but the signed bearer URL itself, i.e. the caption document's capability token, would ride an unencrypted request). One real document was fetched successfully live (`track_count=1`, `segments=2913`), so the `https` absolute form is exercised; the non-`https` form is not
  - Impact: low (no credential exposure — `Credential()` is empty by construction — and upstream is expected to answer `https`); it is a two-line hardening in the module that owns this boundary, and the boundary's whole purpose is "the signed URL exists for the duration of one call only"
  - Confidence: High

- **[F-002] Spec §1.3's pin-verified framing does not hold for the subtitle entry fields, and two resulting adapter strictness rules are outside §3's raise/drop enumeration (`specs/subtitle-gateway.md:8-10,94-96,207-213` vs `bilibili_api_gateway.py:300-311,329-339`)** → add a dated spec note recording the real provenance (live-observed fields), and either name the two rules in §3 or make an unreadable marker/`id` non-fatal; no code change is required for compliance.
  - Source Type: deep-lens: Contract Lens (docs-match-code / contract provenance)
  - Verification: `grep -rn "ai_status" <control-venv>/site-packages/bilibili_api` → **0 matches** over the whole installed pin; the pin never models the subtitle inventory — it JSON-decodes the response and, for `raw=True`, returns it untouched (`utils/network.py:2275,2295-2296`), and `data/api/video.json → info.get_player_info` declares no response fields (only the request `data` documentation); the pin's own subtitle accessor just forwards the dict (`video.py:1530-1546`). Adapter side: `_read_ai_marker` (`:329-339`) rejects any present non-`int`/negative/`bool` marker with `GatewayShapeError`, and `_read_optional_track_id` (`:300-311`) rejects any present non-`int` `id`; spec §3 enumerates the unreadable cases for `from`/`to`/`content`/`lan`/`lan_doc`/primary-subtag only (`:176-210`) and says unknown extra keys are tolerated (`:182-183`). The spec's preamble instead claims "Every upstream shape below was read out of the installed pin … not from documentation" (`:8-10`) and lists `ai_status` / `type` / `id` as if pin-modelled (`:94-96`). The Task-2 L2 review already rated the malformed-marker rejection "spec-silent-but-reasonable" and recommended the PM let the spec say so (`review/task-2-review.md` §7 item (b))
  - Expected vs observed: expected — the contract's provenance claim matches what the pin actually models, and every rule that can fail a whole listing appears in the contract's own raise/drop list; observed — the entry fields come from live observation, and a single track carrying e.g. a string `ai_status` or a string `id` turns the *entire* `get_subtitle_tracks` call into `shape_error` on a rule §3 does not name. The behaviour itself is defensible (it follows the spec's "a malformed scalar shape is rejected, never coerced" discipline and the null-vs-wrong-shape line, and the alternative — defaulting to CC — would silently mis-report an operator-facing fact), and the live probe's `ai-zh:ai` proves the positive marker direction on one real track; what is missing is the record, not the behaviour
  - Impact: low (spec-text accuracy; a false `shape_error` requires an upstream marker type change that no evidence suggests), but it is the one place where a reader of the primary spec would conclude "pin-verified" for something the pin does not carry
  - Confidence: High

- **[F-003] Spec §4.3's re-list trigger is written as "HTTP status != 200", while the shipped (and §5-sanctioned) reading puts a signed-URL 404 in `not_found` with no re-list (`specs/subtitle-gateway.md:227-230` vs `bilibili_api_gateway.py:610-625`)** → one clarifying clause in §4.3 at iteration close ("expiry/transport class = the mapped `transport_error`; `rate_limited` and `not_found` never re-list"), so the next reader does not re-litigate it.
  - Source Type: deep-lens: Contract Lens (spec internal consistency)
  - Verification: read + grep anchors — §4.3 says the second attempt applies "only for the expiry/transport class (HTTP status != 200 on the signed URL, i.e. a signature that no longer works)" (`spec:227-230`), while §5's table lists HTTP `404` → `not_found` under the shipped shared mapping (`spec:254`) and reserves `transport_error` for "Signed-URL fetch HTTP status != 200 … after the single bounded re-list" (`spec:257`); the adapter arms the re-list only on `GatewayTransportError` (`:615-625`) with the shipped mapper in front of it (`:797-802` maps 412/429 → `rate_limited`, 404 → `not_found`); the pin's own transport raises `NetworkException(status, …)` for any non-200 (`utils/network.py:2279-2281`). The behaviour is pinned in both directions: `FakeNetworkException(404)` → `GatewayNotFound` with **1** listing+fetch pair (`tests/test_bilibili_api_gateway.py:2939,2967`, commented "A document that is not there is not an expiry"), 412/429 → `GatewayRateLimited` with 1 pair, 503/`RuntimeError` → `GatewayTransportError` with 2 pairs. The PM already dispositioned this (Task-2 C2a: §5's explicit table governs §4.3's loose parenthetical) and the Task-2 L2 review concurred, recommending the wording be tightened once the live probe stops showing 404s on stale URLs
  - Expected vs observed: expected — §4.3's trigger description and §5's table describe the same class; observed — §4.3's parenthetical literally covers the 404 row that §5 assigns to `not_found`, so a *stale* signature answered 404 is surfaced to the operator as `no-subtitle` (a false "nothing usable was visible") instead of being retried once. The shipped reading is the one that never spends risk budget on a block and is defensible; I concur with the recorded disposition and record the wording gap only
  - Impact: low (documentation; the operator-facing consequence is recoverable by re-probing, and Plan 3 owns the `no-subtitle` wording)
  - Confidence: High

- **[F-004] A test docstring re-worded by this branch still denies a delegate the adapter calls (`tests/test_bilibili_api_gateway.py:1712-1714` vs `bilibili_api_gateway.py:766-776`)** → one-line reword ("the *page call* never goes through a `user` delegate"), or fold into R1's wave when the `user` import is narrowed; not a reason to reopen R1's deferral.
  - Source Type: Standards Lens + deep-lens: Contract Lens (docs-match-code)
  - Verification: read + git anchors — `test_gateway_imports_stay_on_metadata_surface`'s docstring reads "``User`` is deliberately not among them: the page call goes through the ``user`` module's endpoint description and the package ``Api``, **never a ``user.User`` delegate**" (`:1712-1714`, text re-worded from base `:1448` by this range), while the adapter calls `await user.User(uid=mid, credential=self._credential).get_access_id()` (`:766-776`) and the same test's own positive control requires `get_access_id` to be present in the scanned attribute names (`:1770-1773`)
  - Expected vs observed: expected — a test's docstring describes the import surface its assertion pins; observed — the sentence is contradicted by the code in the same branch and by the assertion two lines below it. Pre-existing text the range re-touched without correcting (the Task-3 L2 review recorded it as Minor 5; the PM folded it into R1) — the assertion itself is the reason the claim is checkable, so the item is a docstring accuracy fix, not a boundary defect
  - Impact: none on shipped behaviour; it matters because this is the same "the import surface says what it is" reading that R1 is about, so leaving a false sentence in place weakens the record the next plan will read
  - Confidence: High

### ⚪ Unconfirmed

None. Every evidence channel this seat needs was available and intact: the review cwd/branch/range reproduce exactly, the review package is byte-identical to the real diff, all six changed files are readable, the primary and sibling specs are readable, and the pinned distribution's own source and endpoint data (the oracles for every locked call-shape clause) are readable in the control `.venv`. Runtime-only proofs are listed under **Needs L4/QA verification** — they are gate-owned, not evidence-channel failures.

## Source Trace

| Finding | Source Type | Source Reference | Confidence |
|---|---|---|---|
| F-001 | deep-lens: Contract Lens + read / grep | `src/bili_asr/sources/bilibili_api_gateway.py:374-388,743-750`; `specs/subtitle-gateway.md:97-99`; `tests/fixtures/fake_bilibili_gateway.py:156-163` | High |
| F-002 | deep-lens: Contract Lens + grep over the installed pin | `specs/subtitle-gateway.md:8-10,94-96,176-210`; `src/bili_asr/sources/bilibili_api_gateway.py:300-311,329-339`; pin `utils/network.py:2275,2295-2296`; pin `video.py:1530-1546`; `grep -rn ai_status` over the pin → 0 | High |
| F-003 | deep-lens: Contract Lens + read | `specs/subtitle-gateway.md:227-230` vs `:254,257`; `src/bili_asr/sources/bilibili_api_gateway.py:610-625,797-802`; `tests/test_bilibili_api_gateway.py:2939,2967`; pin `utils/network.py:2279-2281` | High |
| F-004 | Standards Lens + deep-lens: Contract Lens | `tests/test_bilibili_api_gateway.py:1712-1714,1770-1773`; `src/bili_asr/sources/bilibili_api_gateway.py:766-776`; base text `git show 2bd333f:…test_bilibili_api_gateway.py` line 1448 | High |

## Verified clean (evidence, not findings)

1. **The locked listing call shape is verified against the pin itself, not against the seam.** `bilibili_api/data/api/video.json → info["get_player_info"]` is `url=https://api.bilibili.com/x/player/wbi/v2, method=GET, verify=true, wbi=true, dm=true`, `data={aid, cid, ep_id, isGaiaAvoided, web_location}` — identical field-for-field to `FAKE_PLAYER_ENDPOINT` (`tests/fixtures/fake_bilibili_gateway.py:112-126`), which the parity test compares against the distribution (`tests/test_bilibili_api_gateway.py:2141-2170`) and which the adapter probe re-reads at import time before any seam can shadow it (`:186-205`). The adapter reads `url`/`method`/`wbi` from that description and overrides exactly `verify`/`dm` (`bilibili_api_gateway.py:695-711`); parameters are exactly `{bvid, cid, isGaiaAvoided: False, web_location: 1315873}` (`:704-709`), matching the pin's own player call apart from `aid`→`bvid` — which is precisely the substitution that avoids the extra `Video.__get_aid()` detail call the pin pays (`pin video.py:1568-1580`). The recorded call is asserted (`test:2495-2528`) and the adapter is additionally run against the pin's own description values so only the two overrides differ (`test:2545-2572`).
2. **The corrected body-fetch shape is realizable in the pin, exactly as the spec's dated correction states.** `raw`/`byte` are `request` arguments, not constructor fields (`pin utils/network.py:2352-2354`), `Api.result` awaits `self.request()` bare (`:2388-2393`), and `Api` is a dataclass whose constructor accepts `url/method/comment/wbi/dm/verify/no_csrf/json_body/ignore_code/sign/data/params/files/headers/credential` (`:2136-2150`) — so `Api(url=…, method="GET", wbi=False, dm=False, verify=False, credential=Credential()).request(raw=True)` (`bilibili_api_gateway.py:743-750`) is the shape the pin accepts, and `raw=True` is required because a subtitle document carries no `code`/`data` envelope for the default unwrapping to strip (`pin:2295-2302`). The seam mirrors the same split and rejects a construction-time `raw` (`fixture:491-520`, `test:2078-2138`).
3. **No invented parameters, and the two folklore ones are absent by construction.** The recorded parameter set is asserted by exact dict equality, including the absence of any `dm_*` key (`test:2517-2523`), and the pin declares neither `need_login_subtitle` nor `w_webid` for this endpoint (`data/api/video.json`; `pin video.py:1568-1580` sends neither). `w_webid` remains a metadata-path-only parameter (`bilibili_api_gateway.py:653,672`) — the subtitle path never calls `_resolve_w_webid`.
4. **The taxonomy is unchanged and the metadata mapping is provably untouched.** No new code vocabulary: `_SUBTITLE_NOT_FOUND_API_CODES = _NOT_FOUND_API_CODES | {-101}` is the only set change (`:61-65`), and `_await_upstream` gains a keyword-only parameter defaulting to the shipped constant (`:778-783,803-808`) so every existing call site maps exactly as before; `_RATE_LIMITED_*`/`_NOT_FOUND_*` and the exception ladder are otherwise byte-identical (the `except` clause order is untouched). The only other edit inside the metadata path is a whitespace-only reflow of one lambda (`:561-566`), i.e. no token change. The `-101` divergence is pinned in both directions in a single test (`test:2613-2635`).
5. **The normalization boundary matches spec §3 row for row.** Unreadable-vs-droppable is decided on shape, never content, and before DTO construction: non-mapping entry, non-numeric/boolean/non-finite `from`/`to`, an overflowed millisecond product, and non-string `content` raise `GatewayShapeError` (`:411-449`); `end_ms <= start_ms`, `start_ms < 0`, and empty-after-strip text drop the row only (`:429-431`). `body` absent/`null`/non-array raises; an empty array is readable (`:399-403`); a document in which nothing survives — empty `body` included — is `GatewayNotFound`, never an empty success (`:626-627`, `test:3012-3045`); an empty inventory is an empty tuple, never `not_found` (`:583-586`, `test:2414-2431`). Both directions are pinned with the surviving tuple on one side (`test:2641-2675`) and a 25-case raise parametrization on the other (`test:2870-2902`).
6. **The re-list is exactly one, never a loop, and never armed by the wrong class.** The fetch's own initial listing stands outside the `try` (`:607-609`), so a dead listing is never re-listed (`test:2845-2867`); only `GatewayTransportError` arms the second pair (`:615-625`); `rate_limited` and `not_found` propagate un-retried (`test:2926-2967`, with per-class `attempts` asserted against the exact call list); the second attempt uses the *fresh* URL (`test:2970-3009`); and there is no third attempt.
7. **`floor(seconds * 1000)` and the segment invariant.** Conversion is `math.floor(seconds * 1000)` (`:446-449`), identical to the metadata path's `duration_ms` conversion (`:225`) and not the legacy `round()`; `SubtitleSegment`'s own validation enforces `end_ms > start_ms >= 0` with non-empty stripped text (`sources/models.py:138-143`) and the adapter drops before constructing (`:429-431`), so the DTO invariant is the invariant on what a call returns.
8. **Boundary integrity holds exactly as the plan constrains.** `grep -rn bilibili_api src/` returns only the adapter's own imports plus docstrings; the AST boundary test is unchanged and still asserts `offenders == ["bilibili_api_gateway.py"]` (`test:1690-1699`); `test_gateway_imports_stay_on_metadata_surface` compares the adapter's parsed imports to `ALLOWED_PACKAGE_IMPORTS` by **exact equality** (`test:1702-1735`) and the constant matches the adapter's real imports line for line (`bilibili_api_gateway.py:26-35`); the forbidden-token family is exactly `(playback, playurl, play_url, download, danmaku, audio, asr, export)` with `subtitle`/`player` authorized and *positively* controlled (`test:295-319,1738-1781`); the documented-call allow-list is the exact five-route tuple (`fixture:136-142`, `test:2215-2232`). `storage`, `services`, and `cli` are untouched — the range is six files, all under `sources/` and `tests/` — and `sources/__init__.py` re-exports the two DTOs while staying importable without the pin (the CLI imports the adapter lazily inside `_cmd_fetch_meta`, `src/bili_asr/cli.py:534`).
9. **No-leak and credential boundary hold across the range.** The DTO field sets exactly exclude `work_id` and any URL (`test:1540-1558`); every mapped message is `Type`+`code`+static `detail` (`sources/models.py:189-197`) and the tests scan `str`/`repr` of DTOs and mapped failures for all six sentinels (`test:3072-3112`); the sentinel set now carries both the absolute and the protocol-relative subtitle-URL forms with a positive control proving the scanner sees them (`fixture:156-182`, `test:2173-2194`). Diff-wide scan: 0 value-shaped `SESSDATA`/cookie assignments; the 50 `sessdata`/`SESSDATA` occurrences are identifiers, sentinels, and the presence-only seam field; the four `.env` substrings are all `os.environ` in the probe module; and the single value-shaped hit in the four commit bodies is the probe's presence-only evidence token (`value_length = 7`, i.e. the `redact_sessdata` "present"/"absent" vocabulary), not a credential. The control-flow print sites carry counts, language codes, `ai|cc`, and milliseconds only, and the track *label* is deliberately never rendered (`tests/test_live_subtitle_smoke.py:262-279`).
10. **The live probe is bounded, opt-in, and its whole control flow is rehearsed offline.** It skips unless `BILI_LIVE_SMOKE=1` (`test_live_subtitle_smoke.py:159-162,421-424`), makes no network call in a default run, fails loudly when opted in without the pin (`:165-197`), reads the operator's archive through a `mode=ro` URI with a `gone` filter and a BV-shape guard so a part the archive has written off cannot spend the probe's call (`:200-240`, `test:480-633`), and its two boundary calls are driven through a scripted gateway so part selection, both loud-fail guards, all four record-and-skip branches, the empty-listing early return, and both evidence renderers are entered by a default offline run (`test:722-882`). The recorded live evidence in the plan (`plans/…:349-363`) is stated in bounded facts only and matches the probe's own renderers; the plan does not over-claim it (no caption-coverage claim).
11. **Every recorded PM authorization was implemented exactly, and nothing beyond it changed.** Task-2 block: the forbidden-token family lost only `subtitle`/`player` with a positive control added; the documented-call allow-list gained exactly `player.track_list`/`subtitle.body`; the protocol-relative sentinel was added; the protocol-surface test became an exact whole-surface set assertion (`test:1637-1666`); `sources/__init__.py` re-exports the DTOs; the no-track signalling is pinned executably both ways; and `language`/`label`/`text` are trimmed at the boundary. Task-3 block: **M1** the `video` import is narrowed to `API`/`Video` with `ALLOWED_PACKAGE_IMPORTS` still an exact equality; **M2** `download` is back in the forbidden tokens while `subtitle`/`player` stay allowed; **M4** the fetch's own initial-listing transport failure has its focused test. The only other changes in the range are docstrings/comments, the `sources/__init__.py` four-line re-export, and the whitespace reflow in item 4 — I found no relaxation outside the recorded set.
12. **No tracked knowledge SSOT is invalidated by this branch.** `{KNOWLEDGE_DIR}/architecture-patterns/normalized-metadata-stack.md` still holds: "exactly one module imports the third-party package — enforced durably by an AST import-boundary test" (`:36-40`), the five-class bounded taxonomy and "raw upstream text, URLs, cookies, and response bodies stay process-local — they may ride the exception chain in memory but never enter a DTO, message, log line, or row" (`:41-47`), and "Reviewing new gateway methods: they must appear on the application-owned protocol (services never import the adapter module path except at the composition root)" (`:109-110`). The new methods are on the protocol and only the composition root imports the adapter. Notably, that SSOT already sanctions the `raise … from exc` chaining the Task-2 L2 review raised as Minor 6 ("may ride the exception chain in memory"), and it bounds the CLI plan's logging accordingly — so no finding is owed there.

## Needs L4/QA verification (gate-owned; not run by this seat)

- **Offline suite totals** — the plan's acceptance claims 903 passed / 2 skipped at open and the ledger records 1091 passed / 3 skipped at HEAD (per-task: 946+2, 1073+2, 1082+3, 1091+3). Not reproducible from a diff; the QA gate owns the full run and should read the criterion as "green with the documented per-task deltas", not as one exact number.
- **The live probe re-run** — the recorded PASS is implementer evidence carrying bounded facts only. QA owns any independent re-run; run it from the worktree package directory (so `tests/conftest.py:11`'s `sys.path` insert beats the control venv's editable install — there is no `.venv` in the worktree) and use `-s` on the first attempt so the evidence lines are visible.
- **`floor(seconds * 1000)` against real seconds** — the probe records milliseconds only, so the live run corroborates but does not prove the conversion; the offline seam remains the proof. Do not read the live timeline as conversion evidence.
- **The archive-database part-selection branch has never run live** — no archive database exists on this host; the branch's control flow is now rehearsed offline (item 10), so a live run landing on the fixed-sample fallback is expected and compliant with the brief ("or a fixed public sample when the archive is empty").
- **`git diff --check`** — verified clean by this seat read-only (`2bd333f..6002f99`, exit 0); no gate action owed.

## Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 0 |
| 🟢 Suggestion | 4 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Approve

**Blocking rationale.** The three scope items that decide this plan were verified against primary sources rather than against the branch's own claims: (1) the locked call shape — transport fields read from the pin's `video.API["info"]["get_player_info"]`, exactly `dm`/`verify` overridden, the parameter set exactly the description's declared set with `bvid` for `aid`, no `need_login_subtitle`/`w_webid`, and the body via `Api(…, credential=Credential()).request(raw=True)` with internal `https:` normalization — all match the installed distribution's own data and code, including the dated `raw` correction; (2) the normalization boundary — every raise trigger, every drop trigger, `body: []`/all-degenerate → `not_found`, the empty tuple vs `GatewayNotFound` signalling, `floor(seconds*1000)`, and trimming — matches spec §3 and §2.1 row for row, and each is pinned by an assertion I read; (3) boundary integrity — one importing module, the AST import-boundary and exact import-set assertions intact, the forbidden-token family exactly the authorized set with a positive control, the documented-call allow-list exact, the taxonomy unchanged, the metadata mapping byte-identical, and `storage`/`services`/`cli` untouched. Every recorded PM authorization is implemented exactly and I found no change beyond it. The four findings are documentation/spec-text and hardening items — none touches a shipped code path except F-001, whose fix is two lines and whose exposure is a bearer URL without any credential — so with Critical 0, Warning 0, and Unconfirmed 0 the template's rules give **Approve**.

**Residual discipline — R1 (scope item 4).** R1 (`user` bound whole, so `user.get_api` reaches every endpoint description with no forbidden-token hit) is registered in `.mstar/projects/_default/residuals.json` with all nine required fields plus provenance (`severity: low`, `decision: defer`, `owner: @project-manager`, `target: 20260911-subtitle-cli-cutover (the next plan touching the adapter)`, `tracking:` the Durable Roadmap line), and the plan carries that line (`plans/20260911-subtitle-gateway.md:274-277`). I judge the defer **legitimate and correctly registered**, and not a fixable item parked to dodge zero-residual: (a) the engine's own `zero-residual` rule accepts exactly this shape — `findingsCleanupGate` rejects `nit` severities, `risk-accepted`/`waived` decisions, and any decision other than `defer`, and requires a non-empty `target` for `defer` (engine `dist/index.js:2394-2404`); R1 satisfies it, so the mode's gate is green with this entry and no other disposition of a `low` residual would be; (b) the item is a *static* reachability looseness in the previously delivered metadata-path import surface, not a live bypass — nothing calls `user.get_api`, and the exact-set import test still guards the module list; (c) fixing it inside this plan would change the import surface that Task-2's recorded authorization pinned as an exact equality (`M1` scoped the narrowing to `video`), so it is genuinely outside this plan's authorization; and (d) the target is the next plan that touches the adapter, which is in the same iteration, so the item is visible to `mstar status tech-debt` rollup by both `target` and `owner` rather than left as an accepted-and-forgotten minor. One asymmetry worth recording, not a finding: Task-1's finding F3 (extending the `FakeGateway` protocol double) is named in the Durable Roadmap with its owning plan (`plans/…:271-273`) but is not in the register; that is defensible — F3 is an ownership statement about a seam extension, not a boundary defect — and both deferrals are disclosed with targets.

**Independent re-judgement of the L2 findings (context, not substitutes).** Task-1 Minors 1–3 are genuinely resolved at HEAD (the protocol-surface test now asserts the exact declared set including a seventh-method guard; the protocol-relative sentinel is in `NO_LEAK_MARKERS` with a positive control; `sources/__init__.py` re-exports both DTOs and the package docstring is accurate). Task-1 Minor 4 (the `73fdef0` commit-subject discrepancy between `implementer-task-1-report.md:9` and `progress.md:5`) is a bookkeeping inaccuracy in an untracked ledger with no shipped artifact — I concur with "no action", and the real subject is `feat(subtitles): add the subtitle DTOs, protocol methods, and the player seam`. Task-2 M1/M2/M4 are resolved exactly as the plan records; M5 is resolved by the dated spec clarification (the adapter trims and the spec now says so). Task-2 M3 (`assert_only_documented_metadata_calls` matches by prefix, `fixture:776-787`) I re-judge as **accepted**: the shipped guard is structurally justified — the page route's recorded label embeds its parameters (`space.arc.search(pn=1, ps=30)`), so exact membership is not available without redesigning the call labels, and the *set* itself is pinned exactly by equality in the new test — if the CLI plan extends the call list it should consider structured route names. Task-2 M6 (`raise … from exc` chaining can render the pin's raw upstream text in a traceback) I also re-judge as **accepted and already bounded durably**: the tracked knowledge SSOT pre-authorizes the chain in memory while forbidding it in DTOs, messages, log lines, and rows (`normalized-metadata-stack.md:44-47`), and the CLI plan owns the failure rendering — as a forward-looking note rather than a finding, that plan should print `code`/`detail` and not render tracebacks. Task-3 Minors 1–4 are fixed in the wave (plan Evidence Index updated, listing-`not_found` branch recorded with evidence, `gone` filter + BV-shape guard, rehearsals for every branch and guard); Task-3 Minor 6 (the probe's non-decreasing-timeline assertion is stricter than spec §3's own guarantee) I re-judge as **accepted** — it is disclosed in the assertion message, asks for a recorded decision rather than a silent pass, and the probe is evidence-only, but the CLI plan should not copy that assertion into a gate without the same wording.

**Non-blocking observations for the next plan (no disposition requested).** (a) The plan's recorded live-probe command (`plans/…:351-357`) hard-codes the control checkout's interpreter and a loopback proxy; the CLI plan reusing "this command shape" must run from its own worktree package directory so `tests/conftest.py`'s `sys.path` insert wins (verified: the worktree has no `.venv`, and the conftest insert is what makes the run exercise worktree code). (b) The probe's `_read_archive_part` filter/projection is SQL over the shipped schema; if the storage plan ever adds a part-level "subtitle-visible" flag, the probe's "newest non-gone part" heuristic is the natural place to consume it. (c) Plan bookkeeping at consolidation is PM-owned: `## Status` still reads `Status: Todo` and `## Review Gate Summary` still reads "pending" while the workflow snapshot shows `InReview` and all three task blocks are `[x]`; the `## Acceptance / Done Criteria` boxes are correctly unticked (L4 owns Done). None of the four findings above blocks this branch, and F-004 plus F-002/F-003 are one-line edits on PM-owned files if the PM prefers to clear them in this round rather than register them.

## Revalidation

**Kind**: targeted fix-wave revalidation (L3), seat 1 of N=2 (`qc-specialist-3`, `qc-specialist`); scope = this
report's four findings as dispositioned in `review/qc-consolidated.md` (S1/F-001, S2/F-002, S3/F-003, S4/F-004),
plus the PM harness edits in the control checkout. Read-only: no git command, no suite run, no live-network run,
`BILI_LIVE_SMOKE` never set, no credential file sourced, no credential value read, printed, or inferred.

### 0. Evidence channel (revision + diff-basis integrity, verified without running git)

- **The reviewed revision is exactly the fix head.** `.worktrees/20260911-subtitle-gateway/.git` (plain file read)
  points at `/root/workspace/bilibili-asr-archive/.git/worktrees/20260911-subtitle-gateway`, whose `HEAD` is
  `ref: refs/heads/feature/20260911-subtitle-gateway`; that branch ref reads
  `932223941318cc2a12b7d6a066eaacafdd814247` = `9322239`. The worktree reflog's last line is
  `6002f99 → 9322239  commit: fix(subtitles): close the plan QC fix wave (W1, S1, S4, S5, S8, S9)`, i.e. the
  fix range is **one** commit, and nothing follows it.
- **`review/qc-fix-diff.md` is complete, not truncated.** An independent parse of its fenced body counts **4 files,
  +202/−12**, with **all 9 hunks footing exactly** against their `@@` headers (my earlier hunk-count suspicion from
  the rendered tail was wrong — the counts foot to the line). That matches the assignment's stated totals, so no
  hunk is missing from the capture.
- **Worktree content = captured head.** The scheme constants (`:76-77`), the refusal line (`:408`), the four new
  tests (`:2686`, `:2776`, `:2815`, `:3033`), the reworded docstring (`:1709-1722`), the probe docstring bound
  (`tests/test_live_subtitle_smoke.py:33-51`) and the README list (`README.md:566-586`) are present in the worktree
  with the content the diff adds. All four touched files carry mtimes 14:19:19–14:21:57, i.e. **before** the fix
  commit's 14:22:59 — a proxy for "no post-commit edit" (not proof of a clean `git status`; I ran no git).

### 1. Per-finding verification

| Finding | Status on `9322239` | Evidence |
|---|---|---|
| **F-001** non-`https` absolute signed URL | **Fixed — accepted, including the refusal branch** | see below |
| **F-002** §1.3 pin-verified framing (`ai_status` 0 hits) | **Fixed (PM)** | see below |
| **F-003** §4 item 3 vs §5 404 wording | **Fixed in substance** (the quoted paragraph itself untouched) → **N-2** | see below |
| **F-004** test docstring denying the `user.User` delegate | **Fixed** | see below |

**F-001 — fixed.** `_read_subtitle_document_url` (`src/bili_asr/sources/bilibili_api_gateway.py:383-408`) now
decides the scheme instead of trusting the value: protocol-relative → `https:` (`:402-403`), `http://` → `https://`
(`:404-405`), `https://` → returned (`:406-407`), anything else → `GatewayShapeError(detail="subtitle track has an
unreadable document URL")` (`:408`), with the two schemes named as constants (`:76-77`). Rows: the upgrade row
(`tests/test_bilibili_api_gateway.py:2776-2805`) asserts the delivered URL is the scripted `https:` form
(`:2804`) plus the exact call list; the refusal row is a two-case parametrization (`:2808-2838`, `ftp://` and a
bare authority) asserting `code` (`:2835`), the exact static `detail` (`:2836`), that the value is **not** in
`str(exc)` (`:2837`), and `calls == [_listing_call()]` (`:2838`) — i.e. no document fetch happened.

**Judgement on the implementer's single call (the refusal branch): accept.** (a) The three accepted forms are
exactly the forms a transport can act on; a scheme-less or `ftp://` value has no TLS reading, so refusing is the
only bounded alternative to forwarding it — the "upgrade-only" minimal reading would leave precisely the
unbounded-forwarding path F-001 was about. (b) The pin does **not** coerce schemes (no `startswith("http")` /
urljoin normalization anywhere in the installed `utils/network.py`), so before the wave such a value was
guaranteed to fail inside the client and then be mapped to `transport_error` (`:835-836`) *after arming the one
re-list* — 2 listings + 2 fetches; the refusal converts that into an accurate `shape_error` before any request.
Strictly better on both diagnostics and network budget, and it introduces no new vocabulary (`shape_error` is
shipped). (c) The message cannot leak: `GatewayError.__init__` composes `Type(code)` + the static `detail`
(`src/bili_asr/sources/models.py:189-197`) and the base docstring already forbids URLs (`:182-184`); the raise site
has no active exception, so no `__cause__`/`__context__` chain carries the value either. Residual nit, not a
finding: an uppercase-scheme (`HTTPS://…`) or otherwise odd-but-harmless value is refused rather than coerced;
upstream has never been observed answering such a form, and the refusal is loud, bounded and recoverable.

**F-002 — fixed (PM).** `specs/subtitle-gateway.md:118-125` carries the dated note (2026-09-11, this seat's F-002):
the entry-field names are read out of the pin's `data/api/video.json` **only where the pin declares them**,
`grep -rn ai_status` over the installed pin returns 0 hits, the AI marker is an upstream-document field, and the
integer strictness rules are **spec-owned** (not pin-derived), corroborated by the live probe (`ai-zh:ai`). That
is the record I asked for; my finding explicitly required no code change, and the note is placed before §2 as
dispositioned. Verified verbatim; nothing over-claimed.

**F-003 — fixed in substance; the paragraph both seats quoted is byte-unchanged → recorded as N-2.** The governing
reading is now in the spec, dated and idiomatically attributed: `:112-114` — "`NetworkException` (HTTP status !=
200) is the transport failure signal — **except HTTP 404**, which section 5 routes to `not_found` with no re-list
(dated clarification 2026-09-11, plan QC seat 2 QC2-001: section 5's table governs this section's shorthand)".
Two precision notes for the record: (i) that sentence lives in **§1.3**, not in §4 as the disposition states, and
it scopes itself to "this section's shorthand"; (ii) §4 item 3 — the text F-003 quoted, and the identical text
qc2's QC2-001 quotes — is unchanged at `:239-240` ("only for the expiry/transport class (HTTP status != 200 on the
signed URL, i.e. a signature that no longer works)"). Because §1.3 is where the transport-failure class is
*defined* and §4 item 3 defines the trigger by reference to that class, the shipped reading (404 → `not_found`, no
re-list; `:265,268` table, code `:630-645` + `:820-821`) is now derivable from the spec as a whole, so the finding
is closed as fixed. The leftover is the gloss sentence itself → **N-2** (one line, non-blocking).

**F-004 — fixed.** The docstring at `tests/test_bilibili_api_gateway.py:1709-1722` now reads truthfully: `User` is
"not an allow-listed name of its own, because the `user` module is bound whole", the adapter reaches the class
through it (`user.User(uid=mid, credential=self._credential)`), `get_access_id()` serves the optional `w_webid`
route "the attribute the next test's positive control requires the scanned source to carry", the module-wide
binding is named as residual **R1** and the page call is correctly scoped ("never through that delegate"). Every
clause checks out against the code: the delegate call is `bilibili_api_gateway.py:788-790`, the positive control is
the `{"get_access_id", …} <= …` assertion at `:1779`, and R1's defer is untouched. Cosmetic only, not a finding:
the reword left one 79-col reflow artifact ("carry).  That" with a lone `That` on the next line) — docstring prose,
no formatter rewrites it, no gate impact.

### 2. Regression lens (from the diff, plus reads at HEAD)

1. **Zero changed or removed assertions.** All 12 removed lines are prose or the superseded two-line code pair: 2
   adapter docstring + 2 adapter code (`-        normalized = f"https:{normalized}"`, `-    return normalized`) + 3
   test docstring + 5 probe docstring. Independent grep over the fenced diff: `^-.*assert` → **0 hits**. The wave
   adds **10** assertion statements, all inside four new tests (`:2714-2717`, `:2803-2805`, `:2835-2838`,
   `:3055-3058`), and no existing test body is otherwise touched.
2. **Exactly one production behaviour change.** The adapter's only two hunks are (i) an inert insertion of a comment
   plus two module constants at `:70-77` (no existing token changed) and (ii) `_read_subtitle_document_url`. Every
   other adapter region is byte-identical to what I reviewed: `_await_upstream` (`:798-836`), `_fetch_subtitle_document`
   (`:751-771`), `_resolve_w_webid` (`:773-796`), the WBI/player call shapes (`:658-749`), `_SUBTITLE_NOT_FOUND_API_CODES`
   (`:64-65`) and the re-list block (`:630-645`) have no hunk and read unchanged.
3. **The refusal cannot leak the signed URL.** Static `detail`, type+code+detail message composition
   (`models.py:189-197`), no active exception at the raise site, and the row itself asserts
   `unreadable_url not in str(caught.value)` (`:2837`). Nothing else in the new code renders or stores the value.
4. **The metadata path is untouched.** The fix range is 4 files (README, the adapter, two test modules); no hunk
   lands in `storage/`, `services/`, `cli/`, and no metadata-path line changed — the only metadata-adjacent region
   the wave even reads is the constants block above the subtitle constants.
5. **The upgrade row is genuinely discriminating, not vacuous.** The row scripts the entry as
   `http://<marker tail>` (`:2791`) while the seam scripts bodies **only** under the `https:` key
   (`tests/fixtures/fake_bilibili_gateway.py:588-597`, where an unscripted URL raises the seam's
   "unexpected subtitle-document fetch" `AssertionError`), so an un-upgraded value cannot pass the success
   assertions; the row also pins the delivered URL (`:2804`) and the exact call list (`:2805`). The docstring's
   no-leak note is accurate: the `http:` form contains `PROTOCOL_RELATIVE_SUBTITLE_URL`
   (`fixture:163`) as a substring, so the sentinel family (`fixture:175-182`) covers this form.
6. **The cancellation row is real, not vacuous.** The seam raises a scripted `BaseException` as-is
   (`fixture:595-596`), and the mapper's broad clause is `except Exception` (`adapter:835`), which cannot capture
   `asyncio.CancelledError` (a `BaseException`) — so the row pins the shipped behaviour and would fail if that
   clause were widened; `calls == [_listing_call(), "subtitle.body"]` (`:3058`) proves the fetch happened and no
   re-list followed.
7. **Other seats' wave items — spot-checked, no objection (not my remit).** W1's row arithmetic discriminates at
   both endpoints (`floor(3.14159*1000)=3141` vs `round` 3142; `floor(3.24159*1000)=3241` vs 3242). S8's bound
   claims corroborate against the installed pin: `wbi_retry_times = 3` (`utils/network.py:252`), the retry loop
   re-signs only on `ResponseCodeException` with `code == -403 and self.wbi` (`:2365-2385`) so the `wbi=False`
   document fetch is one attempt, and `get_buvid()` (`:2033-2052`) is memoized in module globals and costs exactly
   `_get_spi_buvid()` + `_active_buvid()` — two requests, once per process. S9's README list names exactly the
   three switch-gated live tests (one gated `def test_live_smoke_*` per file; the offline
   `test_live_smoke_switch_is_opt_in` monkeypatches the variable and needs no switch).

### 3. New findings (both non-blocking, PM-owned one-liners)

- **[N-1] Spec §1.3's URL bullet states only the protocol-relative normalization, while the shipped boundary now accepts three forms and refuses the rest (`specs/subtitle-gateway.md:94-99` vs `bilibili_api_gateway.py:399-408`)** → add one clause to §1.3: an absolute value is put on the wire as `https:` (a plain `http:` value is upgraded), and a value outside the protocol-relative/`http`/`https` forms is a `shape_error`.
  - Source Type: deep-lens: Contract Lens (docs-match-code); a direct echo of the "or record the scheme rule explicitly in spec §1.3" alternative F-001 offered.
  - Verification: `:94-96` names the two upstream forms but not the rule; `:98-99` locks only "a protocol-relative value is normalized to `https:`"; §5's table (`:262`) routes a non-normalizable *entry* to `shape_error` and has no row for an unreadable *URL*; the adapter accepts the three forms and raises otherwise (`:399-408`), pinned by the wave's upgrade and refusal rows.
  - Expected vs observed: expected — the contract text from which the next plan derives the boundary; observed — the refusal and the `http:` upgrade are derivable only from the code and its tests. F-001 is **closed** by the code+test branch; this is the text half, offered not demanded.
  - Impact: low (one sentence, no shipped behaviour); Confidence: High.
- **[N-2] Spec §4 item 3 still glosses the re-list trigger as "HTTP status != 200", the 404-covering reading F-003 and qc2's QC2-001 both quoted (`specs/subtitle-gateway.md:238-241`)** → carry the same exception clause the §1.3 clarification uses ("HTTP 404 excepted — section 5 governs") in §4 item 3, or hoist that governing sentence into §4.
  - Source Type: deep-lens: Contract Lens (spec internal consistency).
  - Verification: `:239-240` is byte-identical to the sentence quoted in F-003/QC2-001; the wave's dated clarification landed in §1.3 (`:112-114`) and the §4 paragraph has no hunk; §5's rows still route HTTP 404 to `not_found` (`:265`) and reserve `transport_error` for the post-re-list case (`:268`); the code arms the re-list only on `GatewayTransportError` (`:635`) after the 404 mapping (`:820-821`).
  - Expected vs observed: expected — §4 alone yields the retry class; observed — §4 alone still yields "any non-200 re-lists", the exact reader F-003 was written for. Substance is fixed (§1.3 defines the class 404-excepted; §5 governs), so this is a self-containedness edit.
  - Impact: low (docs only); Confidence: High.

Both are one-line spec edits on a PM-owned file; if the PM prefers not to re-touch the spec, each qualifies for a
`defer` residual with a non-empty target under the same engine rule R1 satisfies (`findingsCleanupGate` accepts
`defer` + non-empty `target`), so the mode's gate is not blocked either way. R1 itself re-verified in place:
`severity: low`, `decision: defer`, target now "the next plan whose file list includes
`src/bili_asr/sources/bilibili_api_gateway.py` (the CLI plan does not; expected: the audio/ASR iteration)"
(`.mstar/projects/_default/residuals.json:5-17`) — the W3 correction is applied, and my original F-004 text now
names R1, so the report and the register agree.

### 4. Updated severity counts and verdict

| Severity | Initial review | Open after revalidation |
|---|---|---|
| 🔴 Critical | 0 | 0 |
| 🟡 Warning | 0 | 0 |
| 🟢 Suggestion | 4 (F-001…F-004) | **2 (N-1, N-2)** — F-001…F-004 all closed |
| ⚪ Unconfirmed | 0 | 0 |

**Verdict**: Approve

**Revalidation rationale.** On the reviewed revision `9322239` (confirmed by ref + reflog file read, single commit
on top of `6002f99`), all four findings are closed: F-001 by the normalization plus a discriminating upgrade row
and two exact-call-list refusal rows (I accept the refusal branch — it removes a guaranteed-failure forwarded path
and cannot leak the value), F-002 by the dated provenance note, F-003 in substance by the dated "§5 governs"
clarification, F-004 by the truthful docstring naming R1. The regression lens holds: **0 modified/removed
assertions**, **exactly one production behaviour change**, metadata path and taxonomy byte-unchanged, the new
message bounded and static, and the wave's other seat items (W1, S5, S8, S9) real on inspection. The two new items
are single-sentence contract-text echoes of F-001/F-003 on a PM-owned file — no code, no test, no gate evidence —
so with Critical 0, Warning 0 and Unconfirmed 0 the verdict stays **Approve**.

**Gate-owned items unchanged (not run by this seat)**: offline suite totals at HEAD (must be re-read as "green with
the documented per-task deltas"), the live probe re-run (from the worktree package dir with the control
interpreter — the README's `.venv/bin/python` form is the control-checkout form; the worktree has no `.venv`), the
archive-db part-selection branch, and `floor` against real seconds (the new offline row is now the proof; do not
read the live timeline as conversion evidence).
