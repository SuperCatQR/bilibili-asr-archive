# Archive maintenance deployment acceptance

The authorized acceptance host was a new container. The deployment used Python
3.12.15 and dependencies from the checked-in `uv.lock`, on top of main
`eaad5844890652e0906d53cc2116196f5f0e100e`. The existing production archive and its
external operational controller were not the fixtures in these checks.

## Actual backup scheduler

The installed Supervisor program `bili-asr-archive-backup` executed the repository
polling runner against a detached, checked-in frozen archive. Five scheduled
`trigger=time` runs succeeded, with an actual ten-second policy interval. The
first restore point was full; subsequent restore points had chain depths two
through five. Every run reported detached materialization, database contract,
foreign-key, typed-row and file-hash verification. Both the source database bytes
and its typed table ledger matched the preflight inventory after the scheduled
runs. The scheduler was stopped after this bounded probe.

A separate explicit probe set one fixture job to running with a lease. Backup
refused it, the second refusal produced `backup_failure_alert`, and neither
refusal reset the job. The probe restored the original fixture fields, then a
manual backup verified recovery and the original typed table ledger. This probe
supplied deterministic run timestamps; those timestamps are not evidence of
actual scheduler invocation times. No live business archive was altered.

Private evidence on the acceptance host:

- `evidence/backup-supervisor-preflight.json`: original ledger and database hash.
- `evidence/backup-supervisor-acceptance.json`: five scheduled receipts,
  dependency chains, two refusal receipts, and verified recovery.
- `backup-deployment/scheduler.log`: actual scheduled output.

## Upgrade interruption and audit

The deployed upgrade tests initially passed **63 tests in 308.04 seconds**. The
suite covered the frozen legacy source and a registered multiple-edge upgrade,
interrupted conversion, journal publication before phase rename, completed-phase
tampering, source drift, hard-link aliases, and post-installation drift audits.
Installation occurred only after complete validation. Original source bytes
remained intact. Further malformed-journal and artifact-only audit regressions
were added after that run and are included in final validation.

`upgrade-check` verifies the installation baseline. `upgrade-check --audit`
separately describes immutable history, current mutable facts, artifacts and
external controls. A changed archive requires a new snapshot; the audit does not
authorize overwriting new work or restarting workers.

## Safety review

Independent review added adversarial regressions for forged retention deletion
sets, temporary hard-link aliases, backup state symlinks, altered run receipts,
public policies confronted with private database packages, external artifact
repository overlap, and a rewritten import plan confronted with unrelated
converted bytes. Self hashes establish identity; apply independently reconstructs
the retention minimum and the import result from its original source and target.

Publication backups verify a rights-gated public projection and file hashes.
Their reports explicitly say `database_recoverable=false` and
`restoration_verified=false`; they cannot substitute for private archive recovery.
ZIP encryption is reserved metadata, with `encryption:null`; no key material is
included. Linux atomic replacement retains the previous archive as a rollback
point. Windows replacement and merge are explicitly refused when atomic exchange
is unavailable; new-target imports remain supported.
