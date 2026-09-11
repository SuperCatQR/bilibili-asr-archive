### Task 3: Bounded live subtitle probe evidence

**Files:**
- Modify: `bilibili-asr-archive/tests/test_live_metadata_smoke.py` (or a sibling opt-in test)
- Test: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`

**Interfaces:**
- Consumes: the Task-2 adapter and the operator's credential/proxy environment.
- Produces: opt-in live evidence that a real track list is returned and, when a track exists,
  that segments normalize as expected; and a recorded answer to "does the locked call shape
  reach this endpoint".

- [ ] Add an opt-in `BILI_LIVE_SMOKE=1` probe for one `(bvid, cid)` read from the operator's
      archive database (or a fixed public sample when the archive is empty); skip by default,
      loud-fail when opted in without the required environment.
- [ ] Assert only bounded facts (track count, languages, `ai|cc`; segment count and monotonic
      milliseconds) — never print URLs, bodies, or credentials.
- [ ] Record the probe command and the observed outcome in the plan/README for the CLI plan,
      including the bounded code when the endpoint refuses the locked shape.

**PM-authorized tightenings (2026-09-11, from the Task-2 L2 review).** Small, recorded follow-ups
to the Task-2 implementation; each is a tightening or a coverage gap, not a redesign:

- [ ] **M1 — narrow the adapter's `video` import** to the exact names it needs (`from
  bilibili_api.video import API, Video`, or the minimal equivalent), so binding the module no
  longer makes `Episode`, `VideoOnlineMonitor`, `get_api`, `get_cid_info`, `get_client`
  source-reachable and unflagged; keep `ALLOWED_PACKAGE_IMPORTS` an exact equality.
- [ ] **M2 — re-add `download` to `FORBIDDEN_SEAM_METHOD_TOKENS`** (keep `subtitle`/`player`
  allowed): removing it un-guards a future `get_download_url`, and this iteration acquires no
  media.
- [ ] **M4 — pin the fetch's own initial-listing transport failure** with a focused test
  (implementation already correct).

Run: `cd bilibili-asr-archive && BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_live_metadata_smoke.py -v`

## STOP Conditions

- The player endpoint refuses the locked shape (`dm=False`, `verify=False`, no invented
  parameters) with a risk-control code → stop and escalate with the recorded evidence; do not
  enable the fabricated `dm` fingerprint parameters and do not add undeclared parameters
  (`w_webid`, `need_login_subtitle`) to make the call pass.
- The pinned package cannot reach the player endpoint without a call shape that leaks
  signed URLs or credentials into application DTOs → stop and escalate the contract gap.
- Subtitle acquisition requires playback/audio APIs or a different library → stop; that
  crosses into the next iteration's scope.
- A required normalization rule cannot be satisfied without storing raw JSON → stop and
  update the spec instead of persisting payloads.
- The fake seam cannot mirror the pin's endpoint description without weakening existing
  assertions → stop and report; do not loosen another test to make room.

## Durable Roadmap and Dependencies

- This plan is the acquisition half of the iteration; `20260911-transcript-storage` persists
  what it returns and `20260911-subtitle-cli-cutover` exposes it. No plan claims caption
  coverage on its own, and this plan claims none at all: a returned track list describes what
  the current credential could see for one part at one moment.
- Deferred: retiring `bili_client`'s subtitle methods (only after the CLI cutover plan proves
  the new path); audio/playback APIs stay out of this iteration entirely.
- Deferred to `20260911-subtitle-cli-cutover`: extending the shared `FakeGateway` protocol double
  with the two subtitle methods (Task-1 finding F3) — the CLI plan is the first consumer that
  scripts subtitle calls through the double, and it owns that seam extension.
- Deferred with a named owner (`project-manager`, trigger "this iteration delivered"):
  promoting the iteration's durable storage/transport contract out of
  `{ITERATION_DIR}/iter-2026-09-subtitle-transcript-sqlite/specs/` at iteration-close. No file
  is written directly into `{SPECS_DIR}` during Prepare, so the frozen copy is authored once the
  code and tests have confirmed it.

## Drift Check

Before implementing, inspect `src/bili_asr/subtitles.py`, `src/bili_asr/bili_client.py`
(probe/download methods), and the existing fake seam; confirm the new DTOs do not duplicate
`subtitles.pick_subtitle` behaviour (selection stays in the service layer) and that
`subtitles._LAN_PREFERENCE` is not reused anywhere on the new path.

## Acceptance / Done Criteria

- [ ] Subtitle DTOs + two protocol methods exist with validation and are covered offline.
- [ ] The adapter issues the WBI-signed player call in the locked shape (description mirror,
      `dm=False`, `verify=False`, `bvid`-based parameter set) and normalizes tracks/segments per
      the spec, so a probe result distinguishes language, display label, and AI vs CC.
- [ ] A part with no usable track yields an empty tuple from the listing and `not_found` from
      the body fetch — bounded, non-error outcomes the caller records as `no-subtitle`.
- [ ] Every failure maps to a bounded scalar code; no signed URL or credential appears in
      any DTO, message, log, fixture, or row.
- [ ] Offline suite green (baseline recorded at plan open: 903 passed, 2 skipped) including
      the AST import-boundary test and no-leak scans.
- [ ] Opt-in live probe recorded (real track list, or explicit bounded blocker), asserting
      only bounded facts: track count, languages, AI/CC, segment count, monotonic milliseconds.
- [ ] `git diff --check` clean.

## Prepare → Execute Handoff

Execute Task 1 → Task 2 → Task 3 (serial). After all tasks: SDD branch review package,
mandatory QC tri-review (N=3), mandatory QA gate, then merge into the iteration branch.

## Review Gate Summary

- Decision: pending
- Review range / Diff basis: pending
- Review bundle: `.mstar/sdd/20260911-subtitle-gateway/review/`
- QC inputs: `qc1.md`, `qc2.md`, `qc3.md`
- Blocking result: pending
- Residual findings: pending

## QA Gate Summary

- QA gate: mandatory
- QA mode: acceptance
- Evidence: pending

## Sign-off

- Product intent: reviewed (product-manager, 2026-09-11)
- Architecture: reviewed (architect, 2026-09-11)
- Writing/corpus hygiene: reviewed (writing-specialist, 2026-09-11)
- PM lock: pending
- Implementation owner: fullstack-dev
- QA owner: qa-engineer
- Review cleanup: zero-residual

## Plan self-review

1. Every spec requirement maps to a task and an offline assertion.
2. No task depends on raw response dictionaries.
3. The signed-URL/credential boundary is explicit and testable, and the no-track signalling is
   decided per method (empty tuple / `not_found`).
4. The live probe is bounded and has an honest blocker path, including for a refused call shape.
5. Nothing in this plan touches storage, the CLI, or playback/audio APIs.
6. The plan claims a typed contract and bounded evidence only — it claims no caption
   coverage, and its operator-facing facts (language, label, AI vs CC) are the ones the CLI
   later prints.

## Evidence Index

- Primary spec: `.mstar/iterations/iter-2026-09-subtitle-transcript-sqlite/specs/subtitle-gateway.md`
- Tests: `tests/test_bilibili_api_gateway.py`, `tests/test_live_metadata_smoke.py`
- SDD runtime: `.mstar/sdd/20260911-subtitle-gateway/`

## Status Transition

Starts `Todo`; `InProgress` after the Phase 2 lease; `InReview` after implementation;
`Done` only after QC + the mandatory QA gate and the integration merge.

## End

Subtitle acquisition is a transport concern; the DTO and transcript contracts downstream
are what later iterations build on.
