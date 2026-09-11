Task 1: dispatched (BASE 5b392cc)
Task 1: complete (5b392cc..6827180, review clean)

## Minor (for plan QC)
- M1 duplicated failure_codes (process_row + run_batch both append same code) — stderr prints "(ASRModelError, ASRModelError)"
- M2 exit-code conflation: scope-resolution errors return 1 same as per-item failures
- M3 O(n²) whole-file rewrite per ledger append (fine at current scale)
- M4 dead `broken`/`outcomes` vars in test_cli_run_per_item_failure_batch_continues
- M5 imprecise 3s sleep condition after skipped live rows
Task 2: complete (6827180..2abf3e4, review clean)

## Minor (for plan QC)
- T2-M1 offline routing double-reads subtitle raw/audio before stage helpers re-derive them (wasteful, correct)
- T2-M2 offline harvest/skipped ledger record omits pre-computed started_at (defaults fill; timestamps collapse to one instant)
