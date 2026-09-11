### Task 1: Persist and consume cursor

- [ ] Implement `MetaCursorStore` schema (`mid`, `next_page`, `total`, `state`, `last_api_error_code`, `updated_at`).
- [ ] Persist after successful JSONL merge; on risk exhaustion set `risk_interrupted` and `next_page=last_failed_page`, exit 2.
- [ ] `--resume` consumes only matching-mid `risk_interrupted`; without `--resume`, replace stale cursor after first successful page of the new run.
- [ ] `complete` vs `limited` (retain next unenumerated page); summary never calls a capped run complete.
- [ ] `fetch_pages(..., start_page=1)` initializes `pn = start_page`.

