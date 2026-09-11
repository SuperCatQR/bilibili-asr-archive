### Task 1: Stage-attempt ledger + coordinator core

- [ ] `RunCoordinator` records per-stage attempts atomically (append-only, no partial lines).
- [ ] `run` command executes stages according to manifest `status`; per-item failures recorded and batch continues.
- [ ] Bounded `--limit`; rerun skips already-terminal rows.

Run: focused `tests/test_coordinator.py` passes with fake transport + stubbed ASR.

