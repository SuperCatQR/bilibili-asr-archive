# Metadata collection supervision

`fetch-meta --supervised` admits one bounded collection cycle through the existing
`MetadataIngestor`, gateway, request scheduler, and pagination verification. It
does not create another queue, change credentials, route around rate control, or
skip a failed page. A caller may schedule subsequent invocations; the service
returns immediately while its durable cooldown is active.

```powershell
bili-asr fetch-meta --archive-root C:\archive --mid 23191782 --supervised --limit-pages 3 --request-budget 500 --run-timeout 1800
bili-asr fetch-meta --archive-root C:\archive --mid 23191782 --supervision-status
```

The default state is `ARCHIVE/.metadata-supervision/MID.json`. Keep that file
and its stable `.json.lock` together on persistent local storage. An external
path can be supplied with `--supervision-state`. Writes reuse maintenance IO:
exclusive process lock, fsynced temporary file, atomic replacement, and a
directory fsync where supported. Do not run different state files for the same
creator concurrently. The supervisor lock serializes invocations using the same
state; existing archive/page transaction boundaries remain unchanged.

The state contains the policy version and digest, observed cursor and boundary
digest, unique archived video/part counts, last confirmed progress, consecutive
no-progress count, cumulative observed cooldown, current streak cooldown,
next-action timestamp, and last run outcome/code. No SESSDATA, signed URLs,
upstream response bodies, or arbitrary exception text are stored. The first
observation establishes a baseline: historical failure records do not establish
an unrecorded waiting clock. Scheduled cooldown elapsed across a restart is
counted once; time spent in an interrupted request is not invented as wait.

Default policy:

```json
{
  "version": 1,
  "maximum_consecutive_no_progress": 6,
  "maximum_no_progress_seconds": 21600,
  "maximum_wait_seconds": 14400,
  "initial_backoff_seconds": 900,
  "maximum_backoff_seconds": 3600,
  "maximum_pages_per_cycle": 3
}
```

Use `--supervision-policy PATH` for reviewed overrides. Unknown fields, invalid
bounds, a changed policy for an existing state, corrupt state, scope mismatch,
and a backwards wall clock fail closed. Preserve the old state as investigation
evidence before explicitly choosing a new state file or applying a new policy.
No automatic reset erases an exhausted budget.

Only committed cursor advance or an increase in unique archived video/part
counts resets the no-progress streak. Re-reading the resume prefix, refreshing
timestamps, starting a process, and polling status do not count as progress.
Lifetime cumulative cooldown is retained after new progress. The new streak
gets its own zeroed wait budget. A natural completed run plus a `complete`
cursor is required for supervisor `complete`; `limited`, `ready`, resumable,
and rate-interrupted cursors never imply full UID coverage.

Rate limits, transport failures, and request-budget exhaustion receive capped
exponential cooldown. Authentication, changed/missing resume-prefix evidence,
other deterministic errors, a killed/incomplete run without terminal evidence,
or an exhausted budget produce persistent `needs_attention`. Investigate the
recorded run/page evidence and upstream access before re-enumeration. Explicit
`--incremental`, `--start-page`, and `--skip-failed-page` are refused in supervised
mode; re-enumeration is a separate reviewed invocation. Existing page and
operation retry limits and total request/time budgets still apply.

Exit codes: `0` for a successful bounded cycle or completed collection, `1` for
invalid configuration/state, `2` for a recorded retryable collection failure,
`3` for active cooldown or another supervisor process, and `4` for
`needs_attention`. Inspect the JSON `state` as well: exit `0` with `ready` after
a limited cycle means more enumeration remains. Status uses repository/local
state only and never calls the upstream gateway.

On restart, a state left `running` is reconciled against ingestion runs/pages
created after its recorded run-row boundary. Committed progress is retained;
terminal completion is recognized only with matching cursor completion. An
uncommitted or still-running attempt is held for investigation instead of
silently receiving a fresh retry budget.
