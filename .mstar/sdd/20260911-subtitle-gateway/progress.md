# SDD Progress — 20260911-subtitle-gateway

Task 1: complete (`2bd333f..73fdef0`, review pending)

- Implementer commit: `73fdef0 feat(sources): add subtitle DTOs, protocol methods, and seam scripting`
  (DONE_WITH_CONCERNS)
- Runtime evidence: red-first (`ImportError: cannot import name 'SubtitleSegment'`) → focused
  `179 passed, 1 skipped` (baseline 136+1 → +43 new tests); full offline suite
  `946 passed, 2 skipped` (plan baseline 903+2 → +43, no regressions); `git diff --check` clean
- Scope: `sources/models.py` (frozen `SubtitleTrack` / `SubtitleSegment` + the two locked protocol
  methods; the shipped four signatures pinned by an exact surface test), `tests/fixtures/fake_bilibili_gateway.py`
  (`FAKE_PLAYER_ENDPOINT` mirror, player/track/body scripting, ordered call recording incl. the
  `raw` request argument and SESSDATA presence only), `tests/test_bilibili_api_gateway.py` (43 tests).
  Only one existing assertion updated (the seam surface list `["Video"]` → `["API","Video"]`, still exact).
- Locked signalling implemented: `get_subtitle_tracks` returns a possibly empty tuple (no `not_found`
  for an empty inventory); `fetch_subtitle_segments` raises `GatewayNotFound` and never returns empty.
- PM action on implementer concern **F1**: the spec/plan wording `Api(..., raw=True)` was a factual
  API-shape error (`raw` is a parameter of `Api.request(raw=False, byte=False)`, verified in the pin at
  `utils/network.py:2352`; `Api.result()` calls `request()` bare). PM corrected both artifacts in place
  with a dated note (precedent: the previous iteration's PM spec correction) **before** dispatching Task 2.
- Implementer concerns F2–F4 accepted as scope discipline: `sources/__init__.py` re-exports untouched
  (spec names `sources.models`); `DOCUMENTED_METADATA_CALLS` / the FakeGateway protocol double are
  extended by the consuming task (Task 2/3), not here.

## Next

Task 1 review package (`2bd333f..73fdef0`) → fresh task reviewer → Task 2.

Task 1: review **Approved** — Critical 0 / Important 0 / Minor 4 (+6 ⚠️ handoffs)

- Task reviewer: `review/task-1-review.md` (fresh code-reviewer, Mode A, L2, diff-first); it re-ran the
  sanctioned focused command (`179 passed, 1 skipped`, matching the claim) and independently confirmed
  the pin facts (`Api` dataclass fields vs `request(raw=False, byte=False)`, `result → request()` bare,
  `video.json` `info.get_player_info` == the seam mirror field-for-field).
- Reviewer's calls on the PM context items: (1) the F1 correction is faithful and cannot mislead Task 2;
  (2) the single updated existing assertion (`["Video"]` → `["API","Video"]`) is still exact equality —
  the removed-line audit found only docstring/comment rewrites and relocated page-route lines;
  (3) the locked signalling is encoded exactly and nothing broader; (4) non-vacuity holds for the DTO
  rules and the seam call tokens.
- PM disposition of the ⚠️ handoffs: all folded into **Task 2** via a recorded PM-authorized block in
  the plan (AST forbidden-token family updated with a strengthened positive assertion; documented-call
  allow-list extended; protocol-relative URL added to the no-leak sentinels; protocol-surface test made
  an exact set; `sources/__init__` model re-exports; no-track signalling pinned executably; adapter-side
  trimming). Minors: the same block covers the surface-test over-claim and the leak-marker gap; the
  commit-subject discrepancy is cosmetic (verified by PM at package construction).

## Next

Task 2 (adapter subtitle acquisition) — brief regenerated after the plan amendment.

## Task 1 Gate

- [x] Implementation committed on the assigned feature branch
- [x] Task reviewer completed (Approved; no Critical/Important findings)
- [x] ⚠️ handoffs dispositioned by PM (recorded plan authorization for Task 2)
- [x] Ready to proceed to Task 2

## End of Task 1

Task 2: implemented (`73fdef0..7f7156a`, review in flight)

- Implementer commit: `7f7156a feat(subtitles): implement the adapter subtitle calls in the locked shape`
  (DONE_WITH_CONCERNS)
- Runtime evidence: red before the authorized updates (`2 failed, 177 passed, 1 skipped` — exactly the two
  seam-contract tests) → focused `306 passed, 1 skipped`; full offline suite `1073 passed, 2 skipped`
  (baseline 946+2 → +127 cases, no existing outcome changed); an 18-mutation driver caught 18/18 rules;
  `git diff --check` clean
- Implemented: both adapter methods in the locked shape (transport fields from
  `video.API["info"]["get_player_info"]`, `dm=False`/`verify=False`, params
  `{bvid, cid, isGaiaAvoided: False, web_location: 1315873}`, no `need_login_subtitle`/`w_webid`; body fetch
  `Api(...).request(raw=True)` with internal `https:` normalization; `floor(seconds*1000)`), the unrolled
  single bounded re-list, the `{-101}` not-found extension with the metadata mapping byte-identical, and all
  seven PM-authorized test/contract updates (4 assertions changed, 127 added, 0 deleted — all disclosed).
- PM disposition of the implementer disclosures: **C1 accepted and recorded** — reading the endpoint
  description from `video.API[…]` is required by the spec, so the adapter now imports the `video` module
  (as it already imported `user`) and `ALLOWED_PACKAGE_IMPORTS` moved to the new exact set; no new module
  family became reachable. **C2 (five interpretation calls)** handed to the reviewer to judge against the
  spec; PM records the outcome after the review.
- Task-1 finding F3 (`FakeGateway` double not extended) dispositioned as deferred to the task that scripts
  subtitle calls through the protocol double — the CLI plan owns that; not a residual.

Task 2: review **Approved** — Critical 0 / Important 0 / Minor 6 (+4 ⚠️)

- Task reviewer: `review/task-2-review.md`; it re-ran the sanctioned focused command
  (`306 passed, 1 skipped`, matching the claim), reconciled the coverage counts 1:1 with collected
  test IDs (307 collected = baseline 180 + 127), audited every removed line (31 total: 17
  docstrings/comments + 14 real lines, all replaced by equal-or-stricter forms, **0 assertions
  deleted**), verified the pin mechanics (`update_params` replaces `params`; `request(raw=False,
  byte=False)`; `result → request()`), and ran an AST probe (43 attributes, exactly three carrying a
  removed token).
- Reviewer verdicts: item 5 (authorized updates) — implemented exactly, nothing beyond the
  authorization loosened; `test_gateway_protocol_surface_is_locked` strictly stronger; the sentinel
  test stronger. **C1** — boundary test still exact; minimality partially true (binding the `video`
  module also makes several unnamed attributes source-reachable) → PM disposition M1. **C2a–e** —
  spec-consistent, with (b)'s malformed-marker rejection and (e)'s wrong-typed container noted as
  spec-silent-but-reasonable.
- PM dispositions (recorded in the plan as a Task-3 tightening block, except where noted):
  **M1** narrow the `video` import to the exact names needed; **M2** re-add `download` to the
  forbidden tokens (this iteration acquires no media; `subtitle`/`player` stay allowed); **M4** add
  the missing initial-listing transport-failure test; **M5** accepted with a dated spec
  clarification (trim = surrounding whitespace only, content verbatim); **C2a** confirmed — §5's
  explicit table governs §4.3's loose parenthetical; **M3/M6** accepted (pre-existing patterns);
  **⚠️3 (F3)** recorded in the plan's Durable Roadmap as owned by the CLI plan; **⚠️1/2/4** are the
  QA gate's and the Task-3 live probe's business.

Spec clarification applied (PM, dated): "verbatim" now reads "verbatim in content … surrounding
whitespace is trimmed at the adapter boundary" so the shipped trimming and the product wording agree (M5).

## Next

Task 3 (bounded live probe) — brief regenerated after the plan amendment.

Task 3: implemented (`7f7156a..c3d362c`, review in flight)

- Implementer commit: `c3d362c feat(subtitles): add the bounded live subtitle probe and the Task-2 tightenings`
- **Live evidence (real, not a blocker)**: fixed public sample `bvid=BV1S8hA6MEvy cid=41314223900`;
  `track_count=1`, track `ai-zh:ai`; `segments=2913`, `first_start_ms=460`, `last_end_ms=7896020`,
  timeline non-decreasing; PASSED. Attempt 1 was refused `rate_limited` on the *arc/search metadata*
  route of a discovery-based fallback (the endpoint under test was never reached); after the authorized
  ~120 s cooldown the retry answered, and the fallback is now the plan's literal fixed sample.
- Runtime evidence: focused gateway `308 passed, 1 skipped`; new probe module `7 passed, 1 skipped`
  (clean-env rerun `315 passed, 2 skipped`); full offline suite `1082 passed, 3 skipped`
  (baseline 1073+2 → +9 passed, +1 opt-in skip); M4's pin mutation-verified (2 failed on the extra
  listing, green after revert); `git diff --check` clean; credential scan over the tree: 0 hits.
- Tightenings done: **M1** `from bilibili_api.video import API as VIDEO_API, Video` with
  `ALLOWED_PACKAGE_IMPORTS` still exact; **M2** `download` back in the forbidden tokens
  (`subtitle`/`player` remain the authorized allowances); **M4** initial-listing transport test.
- PM action: the plan's Evidence Index now carries the probe command and the bounded outcome for the
  CLI plan's reuse (the implementer correctly left harness artifacts alone).
- Flagged by the implementer, PM-accepted without action: the `user` module import is still bound whole
  (the same looseness class M1 removed for `video`). Rationale: it is the *delivered* metadata-path
  surface from the previous iteration (reviewed and shipped), the exact-set import test still guards it,
  and tightening it is outside this plan's authorization. Recorded for plan QC.

Task 3: review **Approved** — Critical 0 / Important 0 / Minor 6 (+7 ⚠️); fix wave 1 (`6002f99`) revalidated **Approve** with 0 open Minor.

- Task reviewer: `review/task-3-review.md` (round 1) + `## Revalidation` (fix wave). Round 1 reproduced the sanctioned focused command
  (`315 passed, 2 skipped`), re-derived M1/M2 (AST import map == `ALLOWED_PACKAGE_IMPORTS` exactly; 42 adapter attributes, 0
  forbidden-token hits, positive controls intact), confirmed the read-only archive access (`mode=ro`, no `archive.db` on this host),
  resolved live provenance (conftest prepends the worktree `src`; control `src` has no subtitle methods), and audited the diff
  (0 assertions deleted; every changed assertion equal-or-stricter; no hunk reaches the metadata path).
- **Reviewer disagreement accepted by PM (item 6)**: the whole-module `user` import is NOT "guarded by the exact-set test" — that
  test blesses the module by design, and `user.get_api` reaches every endpoint description without a token hit. Registered as
  **residual R1** (`.mstar/projects/_default/residuals.json`, `severity: low`, `decision: defer`, owner `@project-manager`,
  target `20260911-subtitle-cli-cutover`) with the Durable Roadmap line written into the plan.
- PM dispositions: Minor 1 (stale plan Evidence Index) fixed by PM; Minors 2/3/4 dispatched as fix wave 1 → resolved; Minor 5 →
  R1; Minor 6 (monotonic-timeline strictness) accepted as a disclosed design choice.
- Fix wave 1 (`c3d362c..6002f99`, probe module only): `not_found` listing → bounded evidence line + skip; `processing_status != 'gone'`
  filter + mirrored `BVID_PATTERN` guard on the selected part; offline rehearsals for `_load_gateway`'s ImportError guard, all four
  record-and-skip branches, the empty-listing early return and the evidence chain. Focused `324 passed, 2 skipped`; full suite
  `1091 passed, 3 skipped`; 9 mutations each failing exactly their pinned rehearsal; 0 assertions removed or loosened (reviewer
  independently censused 47 removed / 394 added lines and proved the four assertion/print/skip lines are re-added byte-identically).
- Carried ⚠️ (unchanged, QA gate's business): the live PASS itself, `floor(seconds*1000)` never proven live, the archive-db branch
  never executed live (control flow now rehearsed), run provenance, the full-suite total.

## Plan task status

Task 1 Approved · Task 2 Approved · Task 3 Approved (+ fix wave revalidated) → branch review package + plan QC tri next.

## End of Task 3

Plan QC tri (N=3): seat1 pending · seat2 **Approve** (0C/0W/3S) · seat3 **Request Changes** (0C/3W/6S)

- Seat 2 verified the upstream interaction against the **installed pin** (endpoint mirror field-for-field;
  `need_login_subtitle` absent pin-wide; `w_webid` absent from `video.json`; `raw`/`byte` are `request`
  params; `verify=True` raises locally only; `Credential()` does not read env and emits `SESSDATA: ""`, so
  the CDN fetch cannot carry the credential), the error taxonomy, and the branch's assertion census
  (**exactly one** removed `assert` line branch-wide, replaced by an equal-or-stricter exact-set form).
  It judged the fix wave's `not_found`-records-and-skips change sound (sibling classes still propagate).
- Seat 3 (verdict Request Changes, all three Warnings cheap and non-functional): **QC3-001** the locked
  `floor(seconds*1000)` rule has **no discriminating evidence** (every conversion literal in the suite
  multiplies out exactly, so a floor→round regression passes); **QC3-002** spec §9's "from the operator's
  own archive" is unmet by the recorded run and had no governing reading; **QC3-003** R1's registered
  target cannot discharge it (the CLI plan does not touch the adapter).
- PM dispositions applied in this round: **QC3-002** governing reading recorded in the plan's live-evidence
  section (authorized fixed-sample fallback; the archive-db variant stays a bounded deviation for QA and
  must not be "fixed" by fabricating an archive); **QC3-003** R1 retargeted to *the next plan whose file
  list includes `sources/bilibili_api_gateway.py`* (the CLI plan does not; expected: the audio/ASR
  iteration); **QC3-007** the CLI plan's fixture line now names the deferred F3 double extension;
  **QC2-003** plan `Status` → `InReview`; **QC2-001** spec §4.3 gained the dated HTTP-404 clarification
  (section 5's table governs). **QC3-004** (anonymous credential tier never exercised live) and
  **QC3-008** (no upper bound on converted ms at any boundary) are recorded as carries: the first is a
  QA-gate/CLI-plan live concern, the second belongs to the storage plan's validation decisions.
- Fix-wave candidates handed to the implementer round (after seat 1 lands): QC3-001 discriminating floor
  row; QC2-002 cancellation-contract offline assertion; QC3-005 probe docstring's live-surface bound;
  QC3-006 README's gated-test list.

Plan QC fix wave (`6002f99..9322239`, review in flight): W1 + S1/S4/S5/S8/S9

- Implementer commit: `9322239 fix(subtitles): close the plan QC fix wave (W1, S1, S4, S5, S8, S9)`
- Runtime evidence: focused `329 passed, 2 skipped` (baseline 324+2 → +5 tests); full offline suite
  `1096 passed, 3 skipped` (baseline 1091+3); non-vacuity: `floor`→`round` fails exactly the new
  discriminating row, the pre-fix URL normalizer fails the 3 URL rows, and widening the handler to
  `BaseException` fails the cancellation rehearsal; `git diff --check` clean; 0 changed/removed assertions
- Implemented: **W1** discriminating floor test (`3.14159/3.24159` → `3141/3241` vs round `3142/3242`);
  **S1** total URL normalization (`//…` and `http://…` → `https:`; other schemes → bounded `shape_error`
  with a static message that never contains the URL; upgrade asserted to reach the transport, refusals
  proven to fetch nothing); **S4** truthful docstring naming R1; **S5** cancellation-contract rehearsal
  (scripted `CancelledError` propagates; exact call list proves no re-list armed); **S8** the probe
  docstring now states the real live-surface bound (listing retried up to `wbi_retry_times=3` on `-403`;
  document fetch one attempt; one-time process-global buvid bootstrap ≈2 extra requests; adapter's single
  re-list); **S9** README lists all three `BILI_LIVE_SMOKE`-gated tests (the third verified from the suite).
- Implementer disclosure: the S1 refusal branch is the wave's one judgement call (one-line revert path to
  upgrade-only) — handed to the re-reviewing seats.
- PM note: W1 was intentionally not extended to the metadata path's pre-existing `duration_ms` floor
  (outside the finding's anchor and this branch's diff); recorded here so plan QC does not re-open it.

Plan QC gate: **Approve** after the N=2 targeted re-review (both seats Approve; 0 Critical / 0 Warning /
0 open Suggestion; only residual R1 open as a registered defer)

- Seat 1 revalidation: F-001–F-004 closed; S1's refusal branch accepted and kept; two PM-owned documentation
  one-liners applied (spec §1.3 now records the three accepted URL forms and the refusal; spec §4 item 3 now
  carries the "HTTP 404 excepted — section 5 governs" clause).
- Seat 3 revalidation: W1 (floor discrimination) closed on static grounds — the new row is the suite's only
  discriminating floor-vs-round case; W2 (spec §9 sample source) closed via the plan's durable governing
  reading, whose factual basis the seat re-established independently; W3 (R1 target) closed — the retargeted
  predicate is mechanically checkable and true by exclusion. S8/S9/S10 verified; carries S7/S11/S12 accepted.
- PM action from seat 3's durable-route ask: the S11 millisecond upper-bound decision is now folded into
  `20260911-transcript-storage.md` Task 2 (it previously lived only in the ephemeral review bundle).
- Next: mandatory QA gate (acceptance mode) on HEAD `9322239`, then the integration merge and plan Done.
