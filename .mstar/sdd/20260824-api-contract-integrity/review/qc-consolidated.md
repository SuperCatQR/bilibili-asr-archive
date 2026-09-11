---
report_kind: qc-consolidated
plan_id: "20260824-api-contract-integrity"
verdict: "Approve"
generated_at: "2026-08-24"
review_range: "ab3cd97ca7e166fc6dea65b3785beaef7de597aa..62d91f2"
---

# QC Consolidated Report

## Scope
- Execution mode: `sdd`; mandatory plan-level tri-review, three seats.
- Working branch: `plan/005-bilibili-api-contract-integrity`.
- Review cwd: `/root/workspace/bilibili-asr-archive`.
- Review bundle: `.mstar/sdd/20260824-api-contract-integrity/review/`.
- Final diff basis: `ab3cd97ca7e166fc6dea65b3785beaef7de597aa..62d91f2`.
- Inputs: `qc1.md`, `qc2.md`, `qc3.md`, and final `branch.diff`.

## Gate Decision
- Initial QC wave returned `Request Changes` from all three seats with no Critical findings.
- The zero-residual fix wave landed as commit `62d91f2` (`Close API contract QC findings`), then all original blocking findings received targeted in-place revalidation.
- Final seat verdicts: `qc1 Approve`, `qc2 Approve`, `qc3 Approve`.
- Final finding counts: Critical 0, Warning 0, Suggestion 0, Unconfirmed 0.
- Residual findings: none; no R# was opened under `zero-residual` cleanup.

## Finding Closure
| Source | Finding | Closure evidence | Final state |
|---|---|---|---|
| `qc1.md` F-001 | `last_api_error_code` stayed stale after recovery | Successful `needs_audio`, `subtitle_done`, and `audio_ok` transitions remove the diagnostic; regression assertions cover all three | Resolved |
| `qc1.md` F-002 | Direct unknown `probe-subs --bvid` path lacked coverage | Real CLI-entry test asserts exit 1 and exact minimal `meta_ok` row with numeric API code | Resolved |
| `qc2.md` F-001 | Raw transport/generic exception text could leak through CLI | Exception objects become safe type labels; generic CLI messages are fixed; sentinel output/manifest tests cover fetch, probe, and audio paths | Resolved |
| `qc2.md` U-001 | Unknown probe acceptance evidence gap | Dedicated entry-path regression test added and statically revalidated | Resolved |
| `qc2.md` U-002 | MIME-only FLAC branch untested | MIME-only FLAC test added alongside non-FLAC 30232 coverage | Resolved |
| `qc2.md` U-003 | CDN cookie isolation unasserted | Test asserts SESSDATA on API playurl and empty cookies on CDN stream | Resolved |
| `qc3.md` F-001 | Signed playurl lacked bounded stale-key recovery | First playurl `-403` refreshes keys, re-signs, retries once; second `-403` propagates with no third call | Resolved |
| `qc3.md` F-002 | Broad fixture route could accept obsolete endpoint | Shared fixtures require exact `/x/player/wbi/playurl` fragment | Resolved |
| `qc3.md` F-003 | Runtime acceptance belongs to L4 | Handed to mandatory/full QA; QC did not claim runtime execution | QA handoff |

## Non-Blocking Review Results
- HTTP ownership remains in `bili_client.py`; CLI and media layers retain their existing seams.
- Gone classification remains limited to HTTP 404, API `-404`, and `-62002`; other API failures remain resumable.
- WBI query parameters exclude SESSDATA, and signed CDN URLs are not persisted.
- Audio transfer remains streaming and atomic; 30232 is not inferred as FLAC.

## QA Handoff
- QA gate: `mandatory`.
- QA mode: `full` because this is a behavior/security/API-correctness plan and the final review range changed after the initial QC wave.
- Supplied PC WSL evidence is external L1 evidence: full suite `116 passed in 0.31s`; focused QC coverage `6 passed in 0.03s`.
- L4 must execute or verify final-range acceptance, including direct unknown probe persistence, redaction, WBI retry bound, MIME-only FLAC, CDN cookie isolation, mixed batch exit behavior, and atomic stream failure cleanup.

Verdict: Approve
