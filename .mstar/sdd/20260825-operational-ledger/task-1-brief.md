### Task 1: Persist run records

- [ ] `RunLedger` append-only JSONL writer + loader; atomic per-line writes (no partial records on crash).
- [ ] Fetch-meta appends a record on exit 0 and exit 2 with cursor snapshot.
- [ ] `pilot` appends a run record (branch counts live in coverage_summary / command field; no raw exceptions).
- [ ] Records contain no cookies/SESSDATA/signed URLs/raw exceptions.

Run: focused `tests/test_run_ledger.py` passes.

