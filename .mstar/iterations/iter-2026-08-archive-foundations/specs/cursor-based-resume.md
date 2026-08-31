# Spec: Resumable metadata cursor

## Problem

Risk interruption after a successful metadata page currently leaves the next page only in transient output. A resume must continue at the first unmerged page, retain earlier rows, and distinguish risk interruption from intentional limits and completion.

## Contract

The archive-root sidecar is `meta-cursor.json` with exactly `mid`, `next_page`, `total`, `state`, `last_api_error_code`, and `updated_at`. Persisted states are `risk_interrupted`, `limited`, and `complete`; `running` is memory-only. `next_page` is a positive 1-based page number. `total` is a non-negative integer or null. Error codes are bounded redacted scalars and the sidecar contains no cookies, URLs, signed URLs, tracebacks, or response bodies.

After each successful archive-list page merge, the cursor records the next page. On retry-budget exhaustion, the cursor remains `risk_interrupted` with the first unmerged page and the terminal scalar code, and the command exits 2 after preserving all fetched rows. `--resume` consumes only a matching-mid `risk_interrupted` cursor. A fresh run without `--resume` starts at page 1 and does not delete existing JSONL records. Intentional `--limit-pages` writes `limited`; reaching the API total writes `complete`. Neither terminal state is auto-consumed by `--resume`.

## Verification

Fixture-only tests must force page 2 risk interruption, assert page 1 and its cursor, rerun with `--resume`, assert the request starts at page 2, and prove JSONL has no duplicate work ownership. Corrupt, mismatched-mid, secret-bearing, and state-invalid sidecars fail closed without mutating the manifest.
