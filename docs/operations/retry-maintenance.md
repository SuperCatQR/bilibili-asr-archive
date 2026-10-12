# Bounded retry maintenance

`bili-asr retry-maintenance tick` is an opt-in single-host maintenance pass for
failed workflow jobs. It is deliberately independent of worker liveness. A
deployment must provide four separate files: a reviewed policy, the production
state JSON, a stable lock path shared by every maintenance invocation, and a
health JSON path. The state must already contain `retry_holds` and
`retry_ledger`; missing or malformed state fails closed.

The policy is versioned JSON. It names exact job or part IDs and explicit job
kinds, one allowlist of transient error codes per kind, a retry count, one
delay per retry, and a maintenance interval. The first delay starts at the
latest failed attempt's completion time; later delays start at the ledger's
last reserved retry time. The stricter delay from the shared policy and the reviewed maintenance
schedule applies. Source quality failures,
publication timestamp contract failures, cancellation, payment responses, and
unknown errors are not retryable. The advisory error category on a source
workflow attempt is evidence for investigation, never proof of silent audio.
Status, explain, CLI retry and maintenance share `failure_policy`,
`decide_retry` and the scalar `editorial_retry_facts` projection. Maintenance
allowlists can only narrow the shared automatic policy; validation failures,
lease recovery and unknown codes cannot be enabled by adding them to a policy.
Database attempts remain a lower bound on spent job retries. The external
ledger, holds, backoff, active or successful replacement jobs and the frozen
physical call budget can further deny dispatch. Proofread jobs additionally
require the scalar editorial physical-budget gate.
New inputs honor the persisted physical call budget. Historical frozen inputs
and their original request policy remain unchanged; the shared automatic
policy still denies validation errors. Investigate them through explicit repair
or a reviewed manual retry. A complete saved response can be replayed without
a new provider call, subject to the same job-level admission decision. The maintenance pass never
rewrites a historical input or enables a new regeneration policy. A hold always
wins over an allowlist.

Before changing SQLite, the maintenance ledger durably reserves one retry for
the exact failed attempt. It then performs a compare-and-swap requiring the
same job status, attempt count, error, and latest failed attempt identity. A
process crash can consume an allowance, but cannot create a free retry. The
workflow repository keeps every attempt and cancellation record. No scope
advancement or blanket `requeue_failed()` call is performed.

Example policy and timer setup (replace paths with deployment-local values):

```json
{"schema_version":1,"job_ids":[],"part_ids":[1100],"kinds":["audio"],
 "retryable_errors":{"audio":["TimeoutError"]},"max_retries":2,
 "delays_seconds":[0,600],"interval_seconds":600}
```

```ini
[Service]
Type=oneshot
ExecStart=/opt/bili-asr/.venv/bin/bili-asr retry-maintenance tick \
  --archive-root /srv/bilibili/archive \
  --policy /etc/bili-asr/retry-policy.json \
  --state /srv/bilibili/production-ops/state.json \
  --lock /srv/bilibili/production-ops/maintenance.lock \
  --health /srv/bilibili/production-ops/retry-maintenance-health.json
```

Run `bili-asr retry-maintenance health --health ... --worker-health ...` from
monitoring. Worker health and retry-maintenance health are independent
snapshots: an alive worker does not prove that maintenance is succeeding.
Inspect `last_started_at`, `last_succeeded_at`, `last_failed_at`,
`last_lock_skipped_at`, `lock_skip_count`, and `next_due_at` before taking
action. A lock skip updates its own timestamp and counter, without advancing
`last_succeeded_at`. `health` returns exit code 1 for stale, failed, and
never-succeeded maintenance; worker snapshot contents are returned separately.
The default stale threshold is 180 seconds for a 60-second timer; set it to a
larger value for a slower deployment. A hung initial pass remains
`never_succeeded`, while a pass after an old success becomes `stale`.

Deployment templates live under `scripts/deployment/`. The example policy has
empty selectors and therefore intentionally fails until exact authorized IDs
are filled in. Each selector supports at most 400 items; when both job and
part selectors are present, their intersection is used. Fill the environment
file with absolute paths and keep the timer interval aligned with
`interval_seconds`. Enable the copied service/timer only after the following
handoff has been completed:

1. Stop the old retry-owning tick/timer. Preserve its planning, scope advancement,
   and worker supervision separately, removing its blanket failed-job retry
   loop. Every remaining writer of production state must use the **same existing
   maintenance.lock**, including manual operational scripts. Running the old
   retry loop concurrently would bypass this policy even though lock exclusion
   prevents simultaneous writes.
2. Under that lock, back up the original production state and inspect its
   `retry_ledger` and `retry_holds`. Preserve every existing entry and all unrelated
   fields. If a key was historically absent, add it only after checking prior
   retry/hold evidence; reconstruct prior retry counts rather than starting them
   at zero. A brand-new reviewed deployment may initialize both objects as `{}`.
3. Install a reviewed policy scoped to existing jobs/parts and kinds. Run one
   explicit `tick` and inspect events, ledger, and health. Do not import uploader
   scope implicitly or infer authorization from all failed database rows.
4. Install `bili-asr-retry-maintenance.service`, its timer and the environment file;
   verify a scheduled pass records a new success. Health failure is independent
   of whether worker processes are alive.

Never edit a held production state entry to force recovery; resolve the
investigation and remove a hold through the reviewed production process. A
ledger reservation with an uncertain dispatch is intentionally retained. If
the same attempt remains failed, maintenance reports
`reservation_requires_review`; reconcile SQLite and the retained evidence
before an explicit operational decision. Neither process restart nor changing
job attempt IDs resets cumulative retry counts.

The checked deployment policy example allows `deepseek_transport_failed` and
the historical `DeepSeekTransportError` only, with two retries and delays
`[0,600]`, within the shared three-attempt cap. Fill its empty selectors with
reviewed exact jobs or parts before enabling it. `RevisionValidationError`,
`lease_expired`, HTTP 402 and generic `DeepSeekError` remain denied. The template
correction is an independent deployment change; it does not rewrite product
source, retained attempts or production state.
