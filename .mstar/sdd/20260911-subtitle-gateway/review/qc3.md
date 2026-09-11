---
report_kind: qc
reviewer: qc-specialist-3
reviewer_index: 3
plan_id: "20260911-subtitle-gateway"
verdict: "Approve"
verdict_pass_1: "Request Changes"
generated_at: "2026-09-11"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist-3
- Runtime Agent ID: qc-specialist-3
- Runtime Model: standard tier (delegated QC seat; exact provider/model id not exposed to this session)
- Review Perspective: performance / reliability — with this seat's Assignment emphasis on reliability, evidence honesty, and next-plan readiness
- Report Timestamp: 2026-09-11T14:10+08:00

## Scope
- plan_id: `20260911-subtitle-gateway`
- Review range / Diff basis: `2bd333f..6002f99` (base = the iteration integration branch at feature cut; 4 commits)
- Working branch (verified): `feature/20260911-subtitle-gateway`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-gateway` (`git rev-parse --show-toplevel` = exactly this path; `git status --porcelain` empty before and after this review)
- Files reviewed: 6 (`git diff --stat 2bd333f..6002f99` = 6 files, +3172/−59, matching the Assignment; commits `73fdef0`, `7f7156a`, `c3d362c`, `6002f99`)
- Commit range (not identical to Review range, as expected): `73fdef0..6002f99`; `2bd333f` is the range's excluded base
- Deep review: triggered (S1: 3172 lines / 6 files; S3: `{KNOWLEDGE_DIR}` carries no subtitle-gateway module — 4 architecture-pattern docs, none about the gateway)
- Lenses applied: Reliability Lens, Performance Lens, Enforcement-Path Lens, Ownership / Derived-State Lens, Testing Lens (S3), Bounds Lens
- Analysis methods: `git diff` / `git show` / `read` / `grep` over the branch and the installed pin; a read-only arithmetic check of the conversion literals. No test, build, lint, network, git mutation, or credential file was executed or sourced (`BILI_LIVE_SMOKE` never set).

## Findings

### 🔴 Critical
None.

### 🟡 Warning

- **[QC3-001] The locked `floor(seconds*1000)` rule has no discriminating coverage anywhere in the branch, while the test named for it claims to pin it and spec §9 acceptance names it.**
  -> Add one discriminating conversion case to the offline suite: a row whose product lands strictly between two integers (e.g. `_subtitle_row(3.14159, 3.3, "…")` → `3141` under `floor` vs `3142` under `round`, or `0.0015` → `1` vs `2`), or a focused unit test on `_read_caption_milliseconds`. The fix belongs to the offline suite; the QA gate cannot close this live (see §"QA gate must reproduce").
  - Source Type: deep-lens: Testing Lens
  - Verification: diff/read/grep anchor + arithmetic check. Implementation `src/bili_asr/sources/bilibili_api_gateway.py:434-449` (`math.floor(seconds * 1000)`); the claiming test `tests/test_bilibili_api_gateway.py:2641-2674` (docstring "Seconds become floored milliseconds") uses only `0.0 / 1.5 / 2.5 / 2.75 / 3.0 / 1.0 / 2.0`; the seam default is `tests/fixtures/fake_bilibili_gateway.py:743-751` (`from=0.0, to=1.5`); I enumerated every conversion literal in the suite (all 11 `_subtitle_row` call sites at `tests/test_bilibili_api_gateway.py:2656-2662, 3028-3031` plus every `make_subtitle_entry(...)` site) and all of them multiply out to exact floats. Computed: `2.75*1000 = 2750.0`, `0.46*1000 = 460.0`, `1.5*1000 = 1500.0` — `floor == round` for every one, so no assertion in the branch can fail if the adapter switched to `round()`.
  - Expected vs observed: spec §3 (`…/specs/subtitle-gateway.md:192-195`) locks `floor()` explicitly *against* `subtitles.json_to_srt`'s `round()`, and spec §9 acceptance requires "milliseconds matching `floor(seconds*1000)`"; task-3 review ⚠️2 records this as "stays offline-pinned (seam)" — observed: the seam pin is non-discriminating, so **no evidence channel in this branch verifies the locked rule** (the live probe prints only converted ms and structurally cannot see source seconds).
  - Confidence: High

- **[QC3-002] Spec §9's "one `(bvid, cid)` from the operator's own archive" is not met by the recorded run, and the divergence is nowhere adjudicated, so the QA gate must guess whether the clause passes.**
  -> PM records the governing reading in the plan's "Live probe evidence" / Evidence Index (Task 3's authorized "fixed public sample when the archive is empty" reading), and lists the `archive-db` source path as an explicitly unverified variant handed to QA (rehearsed offline, never executed live) — or amends spec §9 to name the fallback.
  - Source Type: manual-reasoning
  - Verification: diff/read/grep anchor. Spec `…/specs/subtitle-gateway.md:330-332` ("A bounded live probe (one `(bvid, cid)` from the operator's own archive) returns the track list") vs plan `…/plans/20260911-subtitle-gateway.md:225-227` (Task 3 authorizes "one `(bvid, cid)` read from the operator's archive database (or a fixed public sample when the archive is empty)") and plan `:359-363` (recorded run: fixed public sample `bvid=BV1S8hA6MEvy cid=41314223900`, "The operator archive database did not exist, so the plan's fixed-sample fallback applied"). Source module `tests/test_live_subtitle_smoke.py:142-143, 200-259` (fallback + `part_source` label), rehearsed at `:515-535, 538-553, 556-600, 603-633`. The `archive-db` branch is <ins>unreachable</ins> on this host: ledger `progress.md` (Task 3) and task-3 review ⚠️3 both record that no archive database exists and the L2 seat independently confirmed it.
  - Expected vs observed: expected one recorded reading of §9 so the gate can rule on it; observed two defensible readings (local-archive requirement vs the plan-authorized sample fallback) with neither recorded, and the archive-db path never exercised outside a `tmp_root` rehearsal.
  - Confidence: High

- **[QC3-003] Residual R1's registered target cannot discharge it: `20260911-subtitle-cli-cutover` declares no change to the file R1 requires, so R1's trigger is unsatisfiable inside this iteration.**
  -> PM either adds `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py` (plus its `ALLOWED_PACKAGE_IMPORTS` entry) to the CLI plan's file list with a narrowing task, or re-targets R1 to the next plan that will actually edit the adapter and writes that trigger explicitly — plus a completion definition ("`from bilibili_api import user` narrowed to the names used; the exact-set import assertion updated").
  - Source Type: manual-reasoning
  - Verification: diff/read/grep anchor. `projects/_default/residuals.json` R1: `scope` = "…/sources/bilibili_api_gateway.py (import surface) with tests/test_bilibili_api_gateway.py (ALLOWED_PACKAGE_IMPORTS + forbidden tokens)", `target` = "20260911-subtitle-cli-cutover (the next plan touching the adapter)"; plan `:274-277` repeats "narrow it … in the next plan that touches `sources/bilibili_api_gateway.py`". The CLI plan's declared files (`plans/20260911-subtitle-cli-cutover.md:136-138, 190-192, 226-228`) are `services/subtitle_ingest.py`, `cli.py`, three test files, `fixtures/fake_bilibili_gateway.py`, `docs/metadata-storage.md`, `README.md`; `grep -n "bilibili_api_gateway" 20260911-subtitle-cli-cutover.md` = 0 hits. The CLI plan is serial 3/3 and the iteration's last plan, so no later plan in scope inherits the obligation.
  - Expected vs observed: expected a defer whose target can execute it (Durable Roadmap Gate: route + owner + trigger + completion definition); observed a route whose named plan does not touch the adapter, leaving R1 an orphan once the iteration closes.
  - Confidence: High

### 🟢 Suggestion

- **[QC3-004] The anonymous credential tier — the stated rationale for `verify=False`, and half of the spec's product distinction — was never exercised live, and the recorded evidence does not name the tier of the successful run.**
  -> Record `sessdata=present|absent` in the plan's evidence line (the probe already prints it) and give QA one bounded credential-free run, or record the anonymous tier as unverified by design.
  - Source Type: manual-reasoning
  - Verification: diff/read/grep anchor. Spec §1.2 (`:76-82`): mirroring `verify=True` "would turn an anonymous probe into a local `CredentialNoSessdataException` instead of an honest 'nothing usable was visible'"; spec §2.1 (`:158-163`) ties the anonymous-vs-authenticated distinction to `redact_sessdata` presence. Probe: `tests/test_live_subtitle_smoke.py:428-435` prints `sessdata=…` via `redact_sessdata` (presence-only, verified at `src/bili_asr/config.py:144-151`). Plan `:351-363` records the command with `.env` sourced and the words "credential sourced, never echoed" but no presence value.
  - Expected vs observed: expected the tier to travel with the evidence, since the `verify=False` design decision and one acceptance clause both rest on the anonymous path; observed a run whose credential presence is only implied by "sourced".
  - Confidence: Medium

- **[QC3-005] The probe's boundedness claim ("the only live surfaces the probe touches are the player endpoint and the signed document") is narrower than the real live surface.**
  -> State the real bound in the docstring: one listing (up to `wbi_retry_times=3` signed attempts), one document fetch (up to 3 attempts via the same loop), one logical re-list on the transport class, and the pin's one-time process-global buvid bootstrap.
  - Source Type: deep-lens: Reliability Lens
  - Verification: diff/read/grep anchor. Claim at `tests/test_live_subtitle_smoke.py:26-29`. Pin: `utils/network.py:2244-2248` calls `get_buvid()` whenever `buvid3`/`buvid4` are empty and `enable_auto_buvid` is on — and it defaults to on (`:253`); `get_buvid()` (`:2033-2051`) performs `_get_spi_buvid()` (`:1584-1589`, a real `client.request` to the SPI endpoint) plus `_active_buvid()` (`:1597+`, a fingerprint payload POST). The empty `Credential()` the document fetch is built with (`bilibili_api_gateway.py:749`) guarantees empty buvids on the first call in a process. `Api.request` (`:2352-2386`) retries a `-403` up to `request_settings.get_wbi_retry_times()` = 3 (`:252`) on the WBI listing (the document call has `wbi=False`, so it does not re-sign).
  - Expected vs observed: expected a docstring bound that a reader can take literally; observed two extra package-inherent live requests plus a 3-attempt retry budget unmentioned. (Bounded and package-inherent — not a defect, a documentation-accuracy item for the plan/CLI-plan reuse.)
  - Confidence: High

- **[QC3-006] `README.md`'s opt-in live-smoke section documents one module while the shared switch now gates a second one.**
  -> Add one pointer line naming `tests/test_live_subtitle_smoke.py` and its command (the CLI plan already modifies README, so this can fold there).
  - Source Type: deep-lens: Enforcement-Path Lens
  - Verification: diff/read/grep anchor. `README.md:564-585` ("#### Opt-in bounded live smoke") names only `tests/test_live_metadata_smoke.py`; the new module shares `BILI_LIVE_SMOKE` (`tests/test_live_subtitle_smoke.py:119-121`), and a third opt-in live test lives in `tests/test_bilibili_api_gateway.py:3139-3165` (pre-existing at base `2bd333f`, not this branch's change). No README line was touched by this diff.
  - Expected vs observed: expected the docs to match the switch's real blast radius (a whole-suite opted-in run spends extra live calls); observed docs naming one of three gated tests.
  - Confidence: High

- **[QC3-007] The CLI plan authorizes the fixture change as "(scripting only)", which reads against F3's requirement to add the two subtitle methods to the `FakeGateway` double.**
  -> Make the CLI plan's line explicit: "add the two subtitle protocol methods to `FakeGateway` + scripting", so the double conforms to the widened protocol.
  - Source Type: manual-reasoning
  - Verification: diff/read/grep anchor. CLI plan `:191` "Modify: `…/tests/fixtures/fake_bilibili_gateway.py` (scripting only)" vs plan `:271-273` (F3: "extending the shared `FakeGateway` protocol double with the two subtitle methods … the CLI plan owns that seam extension"). Confirmed absent: `tests/fixtures/fake_bilibili_gateway.py:323-372` (`class FakeGateway`) has 0 subtitle members, so it no longer structurally satisfies the six-method protocol declared at `src/bili_asr/sources/models.py:146-176`; no `runtime_checkable` conformance assertion exists in the suite, so the gap surfaces only on first use.
  - Expected vs observed: expected the deferred obligation and the CLI plan's authorization to use the same words; observed "scripting only", which a dispatcher could read as "do not touch the double's methods".
  - Confidence: High

- **[QC3-008] No upper bound is imposed on converted milliseconds at any boundary, so an absurd (but JSON-valid) timestamp would escape the bounded-error contract and surface as an unbounded `OverflowError` at the SQLite insert.**
  -> Storage-plan/QA item: have `TranscriptSegmentRecord` (or the repository) bound `start_ms`/`end_ms` to SQLite's INTEGER range, or accept the risk explicitly.
  - Source Type: deep-lens: Bounds Lens
  - Verification: diff/read/grep anchor. `_read_caption_milliseconds` (`bilibili_api_gateway.py:443-449`): a `float` product that overflows is caught, but a Python-`int` `from`/`to` (a 400-digit JSON integer literal parses to `int`, not `float`) skips the `isinstance(milliseconds, float)` guard entirely and `math.floor` returns a huge int; `SubtitleSegment.__post_init__` (`models.py:138-143`) checks only `>= 0` / `>`; the shipped validation style is minimum-only (`storage/models.py:29`, `_integer(..., minimum=)`), and `specs/transcript-storage.md:449-451` re-validates only `end_ms > start_ms >= 0` at the DB boundary.
  - Expected vs observed: expected a single oversized row to be rejected/truncated at a boundary (Bounds Lens ③) rather than pass both gates; observed it surviving the adapter and the DTO. Low likelihood (requires an out-of-range upstream document); recorded here so the storage plan owns it rather than rediscovering it at the gate.
  - Confidence: Medium

- **[QC3-009] The probe's non-decreasing-timeline assertion is stricter than the contract and can fail a spec-valid document.**
  -> Keep the canary, but have its failure message say "contract-valid input that needs a recorded decision" (it already gestures at this) so QA does not read a future failure as an acceptance failure.
  - Source Type: deep-lens: Standard Lens / Testing Lens
  - Verification: diff/read/grep anchor. `tests/test_live_subtitle_smoke.py:282-304` asserts `starts == sorted(starts)` and fails the run; `specs/transcript-storage.md:454` states "No ordering constraint is imposed on `start_ms`", and the gateway spec preserves upstream order verbatim (`bilibili_api_gateway.py:391-408` drops rows without reordering).
  - Expected vs observed: expected a probe assertion aligned with what the contract promises; observed a document-level ordering gate on a property no spec guarantees.
  - Confidence: High

### ⚪ Unconfirmed
None. Channel note (not a finding): the recorded live PASS is not reproducible from this seat by Assignment (no network, no credential, no `BILI_LIVE_SMOKE`), and task-3 review ⚠️1 already carries it to the QA gate. Per `reviewer-workflow.md` §"Evidence gaps (hand to QA)", it is recorded below as a QA-gate obligation rather than as an unverified finding, so this report's verdict reflects what the diff supports.

## Evidence honesty assessment (Assignment focus 1)

**What the recorded probe does prove.** `track_count=1`, `tracks=ai-zh:ai`, `segments=2913`, `first_start_ms=460`, `last_end_ms=7896020`, `timeline=non-decreasing`, PASSED (plan `:359-363`) is real, useful evidence for: (a) the locked call shape reaching the player endpoint — description mirror + `dm=False` + `verify=False` + `{bvid, cid, isGaiaAvoided, web_location}`, with WBI signing — which was the plan's central unknown and its STOP condition; (b) the signed document being fetched through the package transport with an empty `Credential()` and `request.call(raw=True)`; (c) `is_ai=True` derived from the upstream marker for an `ai-zh` track; (d) 2913 rows surviving the section-3 drop rules in non-decreasing start order.

**What it cannot prove (each traced to source):**
1. `floor(seconds*1000)` — the probe renders converted ms only, never source seconds, so the conversion is unverifiable live by construction; and, per QC3-001, the offline "pin" is non-discriminating. No channel in this branch verifies the rule.
2. The `archive-db` source path — never executed live (no database on this host); only `tmp_root` rehearsals exist. Also unrecorded as a deviation (QC3-002).
3. The anonymous (`sessdata` absent) call shape — the `verify=False` rationale and one acceptance clause rest on it; the recorded run sourced `.env` and does not state the tier (QC3-004).
4. The `-101` → `not_found` divergence and the empty-inventory path — offline-only (the live part had a visible track).
5. The single bounded re-list — never triggered live; bounded offline only.
6. The claim's exact live bound — the pin adds a buvid bootstrap and a 3-attempt retry budget (QC3-005).

**Overstatement check — where I looked and found none:** the plan's "Live probe evidence" section is written in bounded voice ("Observed (bounded facts only — no URL, body, or credential)") and claims nothing beyond those scalars; spec §9's clauses are mostly matched to what the probe asserts; README carries no claim about the new probe; and the pin-level mechanism claims I could check are code-accurate (`Api.verify` → `credential.raise_for_no_sessdata()` only, `utils/network.py:2217`; `raw=True` required because `_process_response` raises `ResponseCodeException(-1, "API 返回数据未含 code 字段")` without it, `:2275-2320`; the fake's `FAKE_PLAYER_ENDPOINT` equals the installed pin's `data/api/video.json` `info.get_player_info` field-for-field, including `verify: true` / `dm: true` and the declared `data` set). The one overstatement I did find is at the level of *reassurance*, not of claim: task-3 review ⚠️2 calls the floor rule "offline-pinned" (QC3-001), and the probe docstring's live-surface bound (QC3-005).

## QA gate must reproduce (Assignment focus 1/2)

- **Reproduce (owed):** the opt-in live run of the shipped revision, one `(bvid, cid)`, using the plan's recorded command shape (`set -a; source .env; set +a`, `BILI_HTTP_PROXY=…`, `BILI_LIVE_SMOKE=1 … -m pytest tests/test_live_subtitle_smoke.py -s -v`) — and record `part_source`, `sessdata=present|absent`, and the bounded facts. The plan's numbers must be treated as claims until then.
- **Do not attempt live:** `floor(seconds*1000)` against source seconds — that would require capturing raw subtitle JSON, which the plan's Global Constraints forbid. The correct channel is the discriminating offline assertion (QC3-001); QA should require it rather than re-run for it.
- **Record as bounded deviations if unreproducible:** the `archive-db` variant (no archive DB exists on this host — QC3-002) and the anonymous tier (needs a credential-free run — QC3-004).
- **Not owed:** the offline totals in the ledger (`1082 passed` / `1091 passed`) — L1/L2 evidence, arithmetically consistent with the recorded baselines; absence of a green CI link is not a finding here.
- **Also verify at the gate:** that the CLI plan has absorbed F3 and R1 before it is dispatched (QC3-003, QC3-007), since both obligations live outside this branch's files.

## Residual discipline (Assignment focus 4)

R1 is a **legitimate defer in substance**: the finding is real (adapter binds the whole `user` module; `user.get_api` reaches every endpoint description without a forbidden-token hit), severity `low` is right (no operator-visible surface, no data risk; the exact-set import assertion plus the forbidden-token scan still guard the module family), the decision is `defer`, an owner (`@project-manager`) and a tracking line exist in both the register and the plan's Durable Roadmap, and the mitigation is verifiable in the branch (`ALLOWED_PACKAGE_IMPORTS` at `tests/test_bilibili_api_gateway.py:115-126` is an exact equality, `bilibili_api.video: {API, Video}` after M1, with `download` restored to `FORBIDDEN_SEAM_METHOD_TOKENS` at `:295-304` after M2). **The plan may proceed to Done with R1 open** — subject to QC3-003: the registered target is the iteration's last plan and that plan does not touch the adapter, so as recorded the defer has no executable trigger and would outlive the iteration. That mismatch is a one-line PM correction (register target and/or CLI-plan scope), not a redesign, and it is the reason this report asks for changes rather than approving outright.

## L2 re-judgement (Assignment focus 5)

- task-1/-2/-3 findings: independently re-derived the load-bearing ones from source and concur with L2's own verdicts (Critical 0 / Important 0). The tightened assertions I checked are genuinely stronger, not looser: exact protocol set (`:1637-1669`), exact `ALLOWED_PACKAGE_IMPORTS`, `download` re-forbidden, protocol-relative URL added to `NO_LEAK_MARKERS` (`fake_bilibili_gateway.py:175-182`), and no assertion deletion visible in the diff.
- **Re-judged upward:** task-3 ⚠️2 — L2's "stays offline-pinned (seam)" is not supported: the seam pin is non-discriminating (QC3-001, Warning). L2's ⚠️3 — L2 treats the sample fallback as satisfying spec §9; I read the clause as needing a recorded governing reading because the archive-db path is unreachable on this host (QC3-002, Warning).
- **Re-judged downward / left as-is:** ⚠️5 (full-suite total) and ⚠️4 (run provenance, already disclosed that run (b) came from a pre-final revision) are contextual, not defects; ⚠️6 and ⚠️7 stay statically resolved as L2 concluded; L2's Minor 6 (monotonic-timeline strictness) is kept visible as QC3-009 at Suggestion severity, below L2's "accepted design choice" weight in gate terms.
- No L2 finding rises to a plan-level **Critical** blocker in my judgement, and I add none: the branch's implementation matches its spec, the leak boundary holds in code and in the fixture scanner, and every finding above is a coverage, traceability, or documentation correction rather than a functional defect.

## Non-findings verified (so the PM does not re-open them)

- **Timeouts:** the pin applies its 30.0 s default when the client session is built (`utils/network.py:248` → `get_client()` `:1060-1090` reads `request_settings` per `client_settings`), so the new CDN fetch inherits a bounded timeout. No finding.
- **`raw=True` necessity:** verified against the pin rather than assumed (`_process_response` `:2275-2320`).
- **Archive access is genuinely read-only:** `mode=ro` URI + `is_file()` pre-check + `finally: connection.close()` on every path (`tests/test_live_subtitle_smoke.py:200-240`), with a rehearsal that records the URI and asserts the `?mode=ro` suffix (`:480-512`).
- **No log-line leak through the pin's request log:** `Api._request` dispatches its own `__dict__` (including the signed URL) and the response payload, but `RequestLog.__handle_events` is gated on `__on` (default `False`, `utils/network.py:64, 127-131`) and the app registers no listener (`grep -rn "request_log" src/ tests/` = 0 hits). The plan's "never in logs" constraint therefore holds for this application.
- **`git diff --check` clean** on `2bd333f..6002f99`; `sources/__init__.py` re-exports exactly the two DTOs; the fake seam mirrors the pin's player description field-for-field (my own read of `data/api/video.json`) and its `dm`-on player path injects real fingerprint parameter names, so the "no fingerprint parameters" assertion detects the defect rather than restating the flag.

## Source Trace
- Finding ID: QC3-001 · Source Type: deep-lens: Testing Lens · Source Reference: `src/bili_asr/sources/bilibili_api_gateway.py:434-449`; `tests/test_bilibili_api_gateway.py:2641-2674`; `tests/fixtures/fake_bilibili_gateway.py:743-751`; spec `:192-195` · Confidence: High
- Finding ID: QC3-002 · Source Type: manual-reasoning · Source Reference: spec `:330-332`; plan `:225-227, 359-363`; `tests/test_live_subtitle_smoke.py:200-259`; `progress.md` Task 3 · Confidence: High
- Finding ID: QC3-003 · Source Type: manual-reasoning · Source Reference: `projects/_default/residuals.json` R1; plan `:274-277`; `plans/20260911-subtitle-cli-cutover.md:136-138, 190-192, 226-228` · Confidence: High
- Finding ID: QC3-004 · Source Type: manual-reasoning · Source Reference: spec `:76-82, 158-163`; `tests/test_live_subtitle_smoke.py:428-435`; `src/bili_asr/config.py:144-151`; plan `:351-363` · Confidence: Medium
- Finding ID: QC3-005 · Source Type: deep-lens: Reliability Lens · Source Reference: `tests/test_live_subtitle_smoke.py:26-29`; pin `utils/network.py:252-253, 1584-1589, 1597+, 2033-2051, 2244-2248, 2352-2386` · Confidence: High
- Finding ID: QC3-006 · Source Type: deep-lens: Enforcement-Path Lens · Source Reference: `bilibili-asr-archive/README.md:564-585`; `tests/test_live_subtitle_smoke.py:119-121`; `tests/test_bilibili_api_gateway.py:3139-3165` (present at base `2bd333f:1582-1608`) · Confidence: High
- Finding ID: QC3-007 · Source Type: manual-reasoning · Source Reference: `plans/20260911-subtitle-cli-cutover.md:191`; plan `:271-273`; `tests/fixtures/fake_bilibili_gateway.py:323-372`; `src/bili_asr/sources/models.py:146-176` · Confidence: High
- Finding ID: QC3-008 · Source Type: deep-lens: Bounds Lens · Source Reference: `bilibili_api_gateway.py:443-449`; `models.py:138-143`; `storage/models.py:29`; spec `transcript-storage.md:449-451` · Confidence: Medium
- Finding ID: QC3-009 · Source Type: deep-lens: Testing Lens · Source Reference: `tests/test_live_subtitle_smoke.py:282-304`; `specs/transcript-storage.md:454`; `bilibili_api_gateway.py:391-408` · Confidence: High

## Summary
| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 3 |
| 🟢 Suggestion | 6 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Request Changes

Blocking rationale: the implementation matches its locked spec and the leak/import/read-only boundaries hold in code, so nothing here is a functional defect; but three Warning-level items are unresolved and each is cheap and documentation- or coverage-scoped: the locked `floor` rule is verified by no evidence channel (QC3-001), spec §9's live-probe acceptance clause has no recorded governing reading while its `archive-db` path is unreachable on this host (QC3-002), and residual R1's registered target cannot discharge it (QC3-003). QC3-001 and QC3-002 must be dispositioned before the QA gate rules on acceptance; QC3-003 is a one-line register/scope correction that should land before this plan reaches Done. The live PASS itself remains a QA-gate obligation, not a finding.

---

# Revalidation (pass 2 — targeted, after the plan-QC fix wave)

**Pass scope.** Fix range `6002f99..9322239` (4 files, +202/−12) read once from `review/qc-fix-diff.md`; plus the PM's control-checkout edits (`plans/20260911-subtitle-gateway.md`, `plans/20260911-subtitle-cli-cutover.md`, `projects/_default/residuals.json`, `review/qc-consolidated.md`). Review cwd `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-gateway`, HEAD `9322239`, `git status --porcelain` empty before and after. Read-only throughout: no commit/checkout/push/worktree mutation, no suite run, no build, no live network, `BILI_LIVE_SMOKE` never set, no credential file sourced or echoed. The earlier sections of this report are the pass-1 record and are left verbatim; the Summary table below is the revalidated one.

**Method and evidence honesty.** Static verification only (read/grep at HEAD + the fix-diff artifact) plus one stdlib arithmetic check. Non-vacuity is judged from the seam and the assertion structure, **not** from an observed run: the implementer's runtime numbers (focused `329 passed, 2 skipped`; full `1096 passed, 3 skipped`; three mutation flips) are claims. Each claim I could check statically is consistent with what I found, but this seat did not reproduce any of them. Where a closure below rests on that static analysis, it says so.

## Per-finding verification

### W1 — QC3-001 (the locked `floor` rule had no discriminating coverage): ✅ closed

- New test `tests/test_bilibili_api_gateway.py:2686-2717` drives the seam (`_load_subtitle_gateway(bilibili_api_seam, make_subtitle_track())`), scripts one row `_subtitle_row(3.14159, 3.24159, "向下取整")` (`:2706`) and asserts tuple equality on **both** endpoints: `SubtitleSegment(start_ms=3141, end_ms=3241, text="向下取整")` (`:2714-2716`).
- Arithmetic (stdlib, no project import): `3.14159*1000 = 3141.5899999999997` → `floor 3141` vs `round 3142`; `3.24159*1000 = 3241.59` → `floor 3241` vs `round 3242`. Both endpoints discriminate; the row survives the drop rules under either conversion, so a floor→round regression fails on the equality rather than being masked by a drop.
- Exclusivity re-verified by enumerating every literal that reaches `_read_caption_milliseconds`: all 12 `_subtitle_row(...)` sites and all 12 `make_subtitle_entry(...)` sites in the suite. Apart from the new row they are `0.0` / `1.0` / `1.5` / `2.0` / `2.5` / `2.75` / `3.0` / `-1.0` — every product exact, so `floor == round` for all of them. The implementer's claim "reverting `floor`→`round` fails exactly that row" is therefore **statically supported**, and the new row is the only channel in the branch that pins the spec §3 rule (`specs/subtitle-gateway.md:192-195`).
- The row exercises the shipped conversion (`src/bili_asr/sources/bilibili_api_gateway.py:454-469`, `math.floor`) through the real adapter module under the injected fake package, not a seam-local reimplementation.
- Residual honesty: closure is on static grounds. An empirical flip (temporary `floor`→`round`, run the one test) is available to QA as a one-command confirmation, but is not required by this finding — the discrimination is arithmetic, not empirical.

### W2 — QC3-002 (spec §9's "operator's own archive" had no governing reading): ✅ closed

- Plan `:363-372` now records the reading I asked for, and it resolves the ambiguity rather than restating it: Task 3's brief authorizes a fixed public sample when the archive has no usable part; this host has no archive DB, so the `archive-db` variant is **unreachable here**; §9's phrase is satisfied through the authorized fallback; the `archive-db` branch is a **bounded deviation the QA gate records**, must not be read as a failed acceptance item, and must not be "fixed" by fabricating an archive; the CLI plan is named as the first live archive-backed runner. That is exactly the disposition requested, and it is durable (main plan, not the ephemeral bundle).
- The factual basis holds under independent re-check: `ARCHIVE_DATABASE_NAME = "archive.db"` (`src/bili_asr/config.py:57`); neither the control- nor the worktree-package `archive/` root exists; `.env.example` declares no `BILI_LIVE_ARCHIVE_DB`; and the only `.db` anywhere in the workspace is `bilibili-asr-archive/refactor/archive-v2/index.db`, whose tables are `runs`, `search_fts*`, `transcript_versions`, `videos` — **no `video_parts`**, so the probe's query (`tests/test_live_subtitle_smoke.py:240-246`) raises `sqlite3.Error` and degrades to `None` → sample fallback even if the operator pointed the env var at it. "Unreachable on this host" is exact, not a convenience.

### W3 — QC3-003 (R1's registered target could not discharge it): ✅ closed

- `projects/_default/residuals.json` R1 carries all nine engine-required fields (`id`/`title`/`severity`/`source`/`scope`/`decision`/`owner`/`target`/`tracking`) plus provenance (`source_plan` == the `entries` key; `registered_at` `2026-09-11`; `lifecycle_id` = the iteration workflow id), and no `lifecycle` key, i.e. open by default. The engine's own rollup in this session reads `residuals: low 1`, so the register parses and `severity: "low"` is a recognized enum value.
- The new `target` — *"the next plan whose file list includes `src/bili_asr/sources/bilibili_api_gateway.py` (the CLI plan does not; expected: the audio/ASR iteration)"* — is executable: the predicate is mechanically checkable, its exclusion clause is true (`grep -c bilibili_api_gateway plans/20260911-subtitle-cli-cutover.md` = 0), and the named expectation is grounded in the iteration's own compass (`iterations/iter-2026-09-subtitle-transcript-sqlite/delivery-compass.md:169` — "**Next iteration (audio/ASR)** — audio download … plus local ASR execution"). Together with `owner: @project-manager`, the `scope` field and plan `:274-277`, the defer now has route + owner + trigger + a checkable completion state. The orphan condition that produced the Warning is gone.
- Not re-opened (unchanged, already adjudicated in pass 1 by all three seats): the defer's admissibility rests on the engine's `findingsCleanupGate` reading (`decision: defer` + non-empty `target`), which is what the consolidated records as verified; nothing about the entry changed except `target`/`tracking`, both non-empty strings.

### S8 — QC3-005 (probe docstring's live-surface bound): ✅ landed as asked

`tests/test_live_subtitle_smoke.py:33-48` now states the bound is wider than the two calls the probe drives, and enumerates: the WBI listing re-signed/retried on `-403` up to the pin's `wbi_retry_times` (3); the document fetch as `wbi=False` → one attempt; the one-time process-global `buvid` bootstrap when the credential carries none ("up to two further requests", once per process); and the adapter's at-most-one re-list + fetch pair per call on the expiry/transport class. Each item matches my pin-level verification in QC3-005, and the sentence that understated the bound is deleted. The last bullet also matches the adapter (`except GatewayTransportError` at `bilibili_api_gateway.py:635-645`).

### S9 — QC3-006 (README gated-test list): ✅ landed as asked

Branch `README.md:564-583` now opens the section with "Three tests share the one switch (`BILI_LIVE_SMOKE=1`); every default pytest run skips all three and makes no network call" and names all three: the metadata smoke, the new subtitle probe (with `part_source=archive-db|fixed-sample` and the bounded-facts promise), and `tests/test_bilibili_api_gateway.py::test_live_smoke_single_public_page_for_archive_owner`. Verified against the suite: that third test exists at `:3288` and skips on `BILI_LIVE_SMOKE` (`:3299-3300`), and the described behaviour matches its own docstring. The pre-existing detailed metadata-smoke block below it is untouched, and the `.venv/bin/python` command matches both the probe's own documented invocation (`test_live_subtitle_smoke.py:80-83`) and the control checkout, which owns the `.venv`.

### S10 — QC3-007 (CLI plan's fixture line, PM-fixed): ✅ landed

`plans/20260911-subtitle-cli-cutover.md:191-193` now reads "scripting only, **plus** the deferred Task-1 finding F3: add the two subtitle methods to the shared `FakeGateway`". The wording collision I raised is resolved.

### Carries S7 / S11 / S12: dispositions acceptable

- **S7 (QC3-004, anonymous credential tier never exercised live)** — acceptable: the evidence gap is a live-run property, and the consolidated hand-off already obliges QA to record `sessdata=present|absent` when reproducing, so the gap travels with the gate instead of evaporating; any credential-free live coverage belongs to the CLI plan, which reuses the probe.
- **S11 (QC3-008, no upper bound on converted ms)** — acceptable: it is a storage-boundary validation decision, and the storage plan already lands the `start_ms`/`end_ms` validation point (`plans/20260911-transcript-storage.md:177-183`) where such a bound belongs. One durability note (not a finding): the *specific* upper-bound decision is not yet spelled out in that plan, and the carry currently lives only in the ephemeral `{SDD_DIR}/review/` bundle — the PM should fold it into the storage plan's task text when that plan opens.
- **S12 (QC3-009, monotonic-timeline canary stricter than the storage contract)** — acceptable: the hand-off already tells QA not to read a canary failure as an acceptance failure, which is the whole substance of the suggestion; keeping the canary is the right call.
- These three are **carried, not open**: none is a defect in this branch's code, none blocks acceptance, and none is a residual in the register (the register holds only R1).

## S1 — the wave's one production behaviour change: **accepted**

Spec §1.3 (`specs/subtitle-gateway.md:92-111`) locks: `subtitle_url` is "sometimes protocol-relative (`//...`) and sometimes absolute"; a protocol-relative value is normalized to `https:` **inside the adapter**; the fetch is built with an explicitly empty `Credential()` and "the package's proxy, TLS and impersonation settings still apply", with the empty credential keeping SESSDATA off the CDN host.

- **Upgrade branch (`//…` and `http://…` → `https:`)** — consistent with §1.3. It generalizes the spec's one explicit normalization to the absolute form, and it is the only reading under which the signed URL — by the spec's own framing the capability token for the document — never rides a cleartext request while §1.3's "TLS … settings still apply" holds. `_read_subtitle_document_url` (`:398-408`) now returns an absolute `https:` URL on every non-raising path.
- **Refusal branch (any other scheme → bounded `shape_error`)** — **I accept it, and I would keep it over the one-line revert path.** Reasons: (a) no new code was invented — `shape_error` is the taxonomy's code for a boundary value that cannot be read (§5/§6), and the refusal carries a static, value-free detail; (b) it fires *before* the request is built, which the test's exact call list proves (`calls == [_listing_call()]`), so no live call is spent, no re-list is armed, and no unbounded error escapes; (c) it closes a real hole: the pre-fix code would hand an arbitrary scheme/host to the package transport, i.e. the capability token could be sent somewhere unspecified, which is the opposite of §7's boundary; (d) both refusal rows and the upgrade row are pinned offline. Reverting to upgrade-only would restore forwarding of unknown schemes for no gain — the only cost of refusal is a bounded `shape_error` for a document URL upstream does not produce (Bilibili answers `//`, `http://`, or `https://`).
- **Does it keep the signed URL out of messages and rows?** Yes. The refusal path's message is the static detail (test asserts `caught.value.detail == "subtitle track has an unreadable document URL"` and `unreadable_url not in str(caught.value)`, `:2835-2837`); the upgrade path only changes the value handed to the transport for one call, and no DTO/message/row receives it (§7 unchanged). The new form is scanner-covered too: the `http:` twin contains `PROTOCOL_RELATIVE_SUBTITLE_URL` (`fake_bilibili_gateway.py:163`) as a substring and that marker is in `NO_LEAK_MARKERS` (`:175-182`), so the test docstring's claim is true as written.
- **Non-blocking notes (not findings).** (i) §1.3 enumerates only the protocol-relative normalization, so a one-line dated spec note recording the http-upgrade + refusal rule would keep spec and code in step — the file already carries dated notes in exactly that idiom, and the CLI plan reuses this adapter. (ii) The legacy paths `bili_client.py:575-577` and `audio.py:65` still do only the `//` → `https:` rewrite; they are explicitly slated for retirement after the CLI cutover (plan `:269-270`), so no action belongs in this plan. (iii) Cosmetic: the S4 docstring has a ragged wrap at `tests/test_bilibili_api_gateway.py:1717` ("That" alone on a short line).

## Regression lens: 0 changed/removed assertions — confirmed

From the fix-diff artifact, the wave removes exactly **12** lines and every one is prose or replaced implementation: 2 adapter docstring lines, 2 adapter body lines (`normalized = f"https:{normalized}"` / `return normalized`), 3 test-docstring lines, 5 probe-docstring lines. **No `assert` line removed or edited, no test function removed, no fixture logic touched**, and the only production behaviour change is the URL normalization (two new module constants plus the body of `_read_subtitle_document_url`). The five new tests are purely additive, which matches the ledger's `1091 → 1096` totals.

## Non-vacuity spot-checks (all three hold)

1. **Floor row** — see W1: discriminated at both endpoints, and the only such row in the suite.
2. **URL rows** — *upgrade* (`:2776-2805`): the seam scripts only the `https:` key and raises a loud `AssertionError("unexpected subtitle-document fetch: …")` for an unscripted URL (`tests/fixtures/fake_bilibili_gateway.py:588-591`), so an un-upgraded adapter cannot pass, and the row also asserts the wire URL equals the `https:` marker. *Refusals* (`:2808-2838`, two params: `ftp://…`, scheme-less host): assert bounded `code`, the static `detail`, value-absence, and `calls == [_listing_call()]` — an adapter that forwarded the value would trip the seam's loud failure instead of raising `GatewayShapeError`, so neither row can pass vacuously. I also enumerated every `subtitle_url` form in the suite (https marker, `+ "&second=1"`, protocol-relative, and the two new unreadable forms): no pre-existing test feeds a form that the new refusal would now reject, so the tightening breaks no existing row.
3. **Cancellation rehearsal** (`:3033-3058`) — the seam re-raises the scripted `BaseException` as-is (`:595-596`); the mapper catches `Exception` only (`bilibili_api_gateway.py:835`), so `asyncio.CancelledError` (a `BaseException`) propagates past the `except GatewayTransportError` re-list (`:635-645`); the exact call list `[listing, subtitle.body]` proves the document fetch was actually issued and that no re-list followed. The docstring's aside is accurate: rewriting it to `transport_error` would arm exactly one listing + fetch pair, i.e. two more requests.

## Other seat's items in the same wave (judged for overall diff quality)

- **S4** — landed and truthful: `ALLOWED_PACKAGE_IMPORTS["bilibili_api"]` is `{"Credential", "request_settings", "user"}` (`tests/test_bilibili_api_gateway.py:118-120`), so `User` genuinely is not an allow-listed name, and the adapter really does reach the class through the module (`bilibili_api_gateway.py:788-790`, `user.User(uid=mid, credential=self._credential).get_access_id()`), which is what the docstring now says — including a pointer to the `get_access_id` positive control at `:1779`. The stale denial is gone.
- **S5** — verified above (non-vacuity item 3).

## Updated severity counts (this seat, after revalidation)

| Severity | Pass 1 | Pass 2 |
|----------|--------|--------|
| 🔴 Critical | 0 | 0 |
| 🟡 Warning | 3 | **0** (W1/W2/W3 all closed with evidence above) |
| 🟢 Suggestion | 6 | **0 open** (S8, S9 fixed in the wave; S10 PM-fixed in the CLI plan; S7, S11, S12 carried with dispositions I accept) |
| ⚪ Unconfirmed | 0 | 0 |

Register state: one open residual, R1 (`low`, `defer`, non-empty executable `target`) — unchanged in substance from pass 1 and consistent with `zero-residual` as the engine's gate reads it.

**Verdict (pass 2)**: **Approve**

Rationale: all three Warnings I raised are closed on evidence I verified myself — the locked `floor` rule now has a discriminating row that is provably the only one in the suite; spec §9's live-probe clause has a durable governing reading whose factual basis ("no archive DB on this host") I re-established independently, down to the only other `.db` in the workspace lacking `video_parts`; and R1's defer now names an executable trigger with a grounded expectation. The wave's single production change (S1) is consistent with spec §1.3's wording and its TLS framing, keeps the signed URL out of messages and rows, and is covered by two discriminating test rows — I accept the refusal branch and recommend against the upgrade-only revert. Regression-wise the wave removes prose only, with zero assertions changed or removed, and all three new non-vacuity claims hold structurally. My pass-1 QA-gate obligations stand unchanged (reproduce the live probe from the worktree package dir, record `part_source` and `sessdata=present|absent`, treat the `archive-db` branch and the anonymous tier as bounded deviations if unreproducible, and do not attempt to prove `floor` live) — the earlier "QA gate must reproduce" section remains the hand-off, with W1's empirical flip now optional rather than owed.
