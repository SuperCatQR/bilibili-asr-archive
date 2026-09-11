### Task 5: Bound the default page size to an upstream-accepted value

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/sources/models.py` (protocol default)
- Modify: `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py` (adapter default)
- Modify: `bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py`
- Test: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`
- Modify: any test that pins the old default (disclose each)

**Interfaces:**
- Consumes: the Task-3 call shape and the ingestor's page-based cursor contract.
- Produces: a default page size upstream accepts, with the live path able to collect a page.

- [ ] Change the protocol/adapter default page size from 100 to **30** (locked), keeping the
  parameter name and the ability to pass an explicit `page_size`; do not add a CLI flag.
- [ ] Update the seam + tests that pin the old default (disclose every changed assertion);
  add a test asserting the default is 30 and that an explicit override still flows through.
- [ ] PM annotates the pinned spec's "Required upstream calls #1" with the page-size bound
  and the evidence (implementers must not edit the spec).
- [ ] Live re-run of the bounded smoke (one page, UID 23191782, temporary root, credential
  + proxy) — record the outcome, row counts, and cursor in the report.

Run: `cd bilibili-asr-archive && /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_bilibili_api_gateway.py tests/test_metadata_ingest.py -v`

## STOP Conditions

- The corrected call shape (`dm=False`, `w_webid` present) still returns 412/-352 from a
  cooled-down egress → document the bounded blocker with the exact evidence and escalate;
  do not add fingerprint spoofing, retry storms, or alternate credentials.
- The package cannot issue the page call without `dm` parameters in any supported shape →
  stop and escalate (upstream library change needed).
- Satisfying the transport requires changing the pinned library version → stop and ask;
  the pin is spec-locked.
- Any change would require touching the ingestor, repository, schema, or DTO contract →
  stop; that is out of scope for this plan.

## Durable Roadmap and Dependencies

- This plan closes the "live path actually works" gap left by
  `iter-2026-09-bilibili-api-sqlite`; the next iteration (subtitle/transcript) inherits the
  fixed transport.
- Deferred: real `w_webid` derivation once the upstream dynamic page restores SSR data, and
  a first-class `dm` setting if the library adds one; both are upstream-dependent and need
  no local code until then.
- Deferred: the iteration's QA note wording ("anonymous anti-bot rejection") is corrected
  by this plan's problem statement; no further remediation is required.

## Acceptance / Done Criteria

- [ ] `curl_cffi` is declared in `pyproject.toml`, `uv.lock` is reproducible
  (`uv lock --check` no-op), and a fresh install can import an HTTP backend.
- [ ] `BilibiliApiGateway` resolves and applies a proxy with the locked precedence; an
  unset proxy leaves library behaviour untouched; no proxy/credential value leaks into
  output, logs, or rows.
- [ ] The user-video page call is issued with `dm` disabled and `w_webid` present
  (non-empty preferred when available), with the bounded error taxonomy unchanged.
- [ ] The adapter/protocol default page size is 30 (upstream-accepted; `ps=100` is rejected
  with `-400`/412) and an explicit `page_size` override still flows through.
- [ ] The opt-in live smoke completes one page for UID 23191782 into a temporary archive
  root with real normalized rows and an advanced cursor — or records an explicit, cooled-down
  upstream blocker with evidence.
- [ ] Offline suites remain green (baseline: 865 passed, 2 skipped), including the AST
  import-boundary test and the no-leak scans.
- [ ] `docs/metadata-storage.md`, README, and `.env.example` describe the backend, the
  proxy knob, and the live-smoke expectations accurately.
- [ ] `git diff --check` is clean.

## Prepare → Execute Handoff

The diagnosis above is the Prepare input: evidence was produced live on 2026-09-11
(§Problem). Execute Task 1 → Task 2 → Task 3 → Task 4 (serial). After all tasks: SDD branch
review package, mandatory QC tri-review (N=3), mandatory QA gate (which owns the live
re-run), then merge to `main` via PR.

## Review Gate Summary

- Decision: pending
- Review range / Diff basis: pending
- Review bundle: `.mstar/sdd/20260911-live-metadata-path-fix/review/`
- QC inputs: `qc1.md`, `qc2.md`, `qc3.md`
- Blocking result: pending
- Residual findings: pending

## QA Gate Summary

- QA gate: mandatory
- QA mode: acceptance (owns the bounded live smoke re-run)
- Evidence: pending

## Sign-off

- Product intent: pending product-manager review
- Architecture: pending architect review
- Writing/corpus hygiene: pending writing-specialist review
- PM lock: locked (PM, 2026-09-11; Prepare input = live diagnosis §Problem)
- Implementation owner: fullstack-dev
- QA owner: qa-engineer
- Review cleanup: zero-residual

## Plan self-review

1. Every defect (D1/D2/D3) maps to a task and an acceptance criterion.
2. No task requires changing DTOs, the ingestor, the repository, or the schema.
3. The pinned spec deviation is explicit and annotated, not silent.
4. The live verification is bounded and has an honest blocker path.
5. No new credential surface, retry storm, or risk-control evasion is introduced.

## Evidence Index

- Iteration that shipped the stack:
  `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/delivery-compass.md`
- Pinned gateway spec (transport clause superseded):
  `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/bilibili-api-gateway.md`
- Knowledge: `.mstar/knowledge/architecture-patterns/normalized-metadata-stack.md`
- Live diagnosis artifacts: `/tmp/live-*` archive roots from the 2026-09-11 session
  (failure evidence); the corrected-shape success is recorded in this plan's §Problem.

## Status Transition

Starts `Todo`; enters `InProgress` once the feature branch exists; `InReview` after
implementation; `Done` only by `project-manager`/`qa-engineer` after QC and the mandatory
QA gate, then merged to `main` by PR.

## End

The gateway stays the only module that knows the third-party transport; everything below it
keeps the contract it already has.
