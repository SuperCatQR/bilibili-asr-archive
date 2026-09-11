### Task 2: Prove idempotency and security

- [ ] Stop at page 2, assert `next_page=2`, resume at page 2.
- [ ] Assert no duplicate JSONL records and no false claim for failed page.
- [ ] Assert cursor contains no credentials, signed URL, or raw exception text.
- [ ] Document exact resume and exit-2 behavior in README.

## Acceptance Criteria

- A risk stop on page 2 persists a resumable cursor and a later `--resume` starts at page 2.
- Resumption does not duplicate rows or re-enumerate successful pages.
- Completed and intentional-limit runs are not treated as interrupted; `complete` and `limited` remain distinguishable, and only `complete` claims full enumeration.
- Cursor writes are atomic and contain only safe scalar metadata.
- Full Python 3.12 test suite passes; no live HTTP or model downloads.

## STOP Conditions

- Cursor cannot be persisted atomically without coupling HTTP to filesystem I/O.
- Limit semantics cannot distinguish intentional stop from risk interruption.
- Existing JSONL compatibility requires an unplanned schema migration.
- A proposed change alters retry limits or risk taxonomy.

## Prepare → Execute Handoff

After PM lock and specialist edits, execute cursor tests first, then implementation, then README/idempotency coverage. Plan QC is mandatory tri-review and QA is mandatory/full.
