# Phase 1 product-manager review

- Role: product-manager
- Iteration: `iter-2026-08-archive-foundations`
- Direction lock: page-aware archive identity plus durable risk cursor.
- Scale: `M`, exactly two business plans.
- Shared problem: incomplete multipart archives and repeated metadata requests after risk interruption make corpus progress untrustworthy.
- Accepted scope: canonical `work_id`, collision-free page artifacts, unambiguous legacy migration, `meta-cursor.json`, risk-only resume, and deterministic fixture evidence.
- Explicit non-goals: pilot execution, concurrency, daemonization, status-taxonomy migration, and live traffic in tests.
- Decision: Prepare gate passes; both plans are sufficiently bounded for SDD implementation in isolated branches. The pilot is a documented next-iteration dependency, not a hidden third plan.
- Branch policy: integration `iteration/iter-2026-08-archive-foundations` from `plan/005-bilibili-api-contract-integrity`, target `main`.
- Corpus hygiene: no new knowledge document in the start chain; iteration specs remain under the iteration package.
