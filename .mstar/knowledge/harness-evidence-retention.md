# Harness evidence retention and archival

Policy date: 2026-10-06. Implements issue #218 under
`.mstar/plans/20261006-concurrent-issue-fixes.md`.

## Boundary and durable records

The tracked/volatile boundary in `.mstar/AGENTS.md` and `.gitignore` remains authoritative.
This policy concerns the eventual retention of **tracked historical evidence**, not a new
ignore rule. Runtime scratch, live `.mstar/snapshots/` caches, locks and local store backups
keep their existing treatment. A workflow's tracked `snapshot.json` is a lifecycle record,
distinct from the ignored live snapshot cache.

Keep the following durable records in Git, including records for completed work:

- Plans, decisions, acceptance/gate summaries and unresolved findings; frozen specs/ADRs
  and promoted knowledge explaining the implementation and its limitations.
- Root/project registers and workflow snapshots, plus every engine-read file and every
  plan/spec path those records reference. Do not replace an engine-readable JSON record
  or a source plan with a Markdown archive pointer.
- Iteration indexes, package READMEs and compasses needed to navigate historical decisions.
- Archival inventories, checksums, pointer records, verification results and original-path
  stubs. These remain discoverable from a normal clone even without archive access.
- Unique evidence supporting an open defect, disputed gate, exception or recovery. Raw
  evidence stays durable until its decision is resolved and a sufficient summary exists.

Archive-eligible material is the bulky supporting layer: raw audit transcripts, repeated
command output, obsolete diffpacks, screenshots, duplicate intermediate review drafts and
generated reports from closed work. Eligibility requires **all** of these conditions:

1. The producing plan/iteration is closed and has had no substantive evidence edit for
   at least 90 days, measured using committed history rather than checkout timestamps.
2. No active plan, unresolved finding or engine reader needs the raw bytes at their current
   path. A historical prose citation may remain only when an original-path stub preserves
   a usable route to the exact archive member. A line-number citation needs its original
   lines/member identified in the inventory; a stub alone does not preserve line numbers.
3. A tracked summary records the outcome, actual validation and skips, residuals, source
   commit and the reason the raw material can leave the working checkout.
4. An external archive has been uploaded and independently restored/verified as below.

Age or size alone never makes a durable record eligible. A closure label alone does not
prove that a snapshot or finding no longer references evidence.

## Measurable review triggers

Review at iteration close and monthly while the repository is maintained. Start an archival
review when **any** of these thresholds is reached: one closed evidence bundle exceeds
10 MiB, tracked raw evidence totals 100 MiB, or a closed bundle has been idle for 180 days.
These thresholds trigger an inventory/review, not deletion; the 90-day eligibility minimum
and every condition above still apply. If nothing is eligible, record why and keep it.

Measure tracked file sizes from Git blobs (`git ls-tree -rl HEAD -- .mstar`), sum only paths
classified as raw evidence in the candidate inventory, and record exact bytes and the
measurement commit. Read last substantive changes with `git log -1 --format=%cI -- <path>`;
exclude housekeeping-only edits by inspecting their diff. The review record states the
closure date, last substantive commit/date and elapsed whole days in UTC. Never report
the entire `.mstar` size as raw-evidence size without classification.

## Stable external pointer and checksum record

Use operator-controlled durable storage outside this repository, with immutable object
versions and a tested retrieval path. A temporary download URL, machine-local path or
expiring signed URL is not the canonical pointer. Access may be private; record who owns
the storage and how an authorized maintainer obtains access. Keep a second independent
copy and record its locator before pruning. Never archive credentials or downloaded media
as harness evidence.

For each bundle create a tracked record at
`.mstar/knowledge/evidence-archives/<archive-id>.md` and a machine-readable member inventory
beside it. Use a date plus descriptive slug as the ID. Record:

| Field | Required value |
| --- | --- |
| Identity | Archive ID, policy version/date, producer plan/iteration and closure evidence |
| Provenance | Full pre-pruning Git commit SHA, original repo-relative paths and relevant historical line ranges |
| Eligibility | Classification/reason per path; summary path; trigger and measured bytes/dates |
| Object | Stable canonical URI and immutable version/object ID; second-copy URI/version |
| Integrity | Archive format, exact byte length and SHA-256 of the uploaded archive bytes |
| Members | Inventory path and its SHA-256; each member's original path, archive member name, byte length and SHA-256 |
| References | Inbound citation inventory, preserved snapshot/plan references and each stub path |
| Verification | Upload/restore UTC date, operator, retrieved object version, size/hash verdicts and check results |
| Change | Pointer/stub commit and subsequent pruning commit; maintenance history for locator migrations |

An archive ID resolves via its tracked record even when storage moves. On a move, retain
the old locator/version in history, add the new one, and repeat retrieval/hash validation;
never silently retarget an ID to different bytes. Commit the pointer and verified inventory
before any pruning commit. Record the pointer commit in the pruning commit message and
the pruning SHA in a follow-up record commit, avoiding a self-referential SHA field.

## Manual pruning procedure

1. Work from a clean, dedicated branch. Record the source commit, candidate paths and sizes,
   eligibility decisions, summaries and all inbound references. Search the whole tracked
   repository (including snapshots/registers, plans and docs), not just the candidate folder.
   Inspect engine-consumed fields and indirect references. Unknown consumers block pruning.
2. Exclude durable/engine-read files and active evidence. Preserve workflow snapshot bytes,
   identities, plan references and source-plan files. For historical raw prose citations,
   prepare a small stub at each original path giving archive ID, record path, member name,
   member SHA-256, source commit and the former line range when applicable. If a consumer
   needs original bytes/schema rather than a human pointer, retain that file unchanged.
3. Package the exact original bytes with repo-relative member paths and no host secrets.
   Generate the member inventory and hash both it and the final archive. Upload the primary
   and second copies. Retrieve the uploaded objects into fresh temporary locations; verify
   object versions, archive sizes/SHA-256 and every extracted member against the inventory.
   A successful upload or listing is insufficient. Record failures and retain source files.
4. Commit the pointer, inventory, summary and verification record first. Review the explicit
   pruning list and stub mapping. Only after that review, replace eligible raw files with
   their stubs in a separate commit; do not delete containing directories indiscriminately.
   Retain records in Git history. This reduces checkout size; it does **not** shrink existing
   Git history and does not authorize history rewriting or garbage collection.
5. From the pruning checkout, run `python scripts/validate_harness_state.py ../.mstar` and
   `python -m pytest tests/test_harness_state.py` in `bilibili-asr-archive/`, using the installed
   engine/runtime. Review the diff for snapshot/register changes and repeat the inbound
   reference audit: every retained path/citation must resolve to original durable bytes or
   a reviewed stub/member mapping. The harness checker does not validate external pointers
   or arbitrary prose citations; archive retrieval and reference audits are separate gates.
6. Record check results and the pruning commit. If any gate fails, restore affected originals
   from the source Git commit or verified archive and leave the pruning unapplied. Keep
   the pointer/inventory record as the audit of the attempted operation.

This issue establishes policy only. No archive upload, evidence removal, snapshot rewrite,
ignore-rule change or history rewrite is performed as part of its implementation.
