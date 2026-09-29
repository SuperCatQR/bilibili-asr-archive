# Full-visible-corpus scheduler delta

This iteration-scoped delta extends the shipped bounded `pilot`/`run` surfaces into an explicit, sequential, resumable scheduler without changing the frozen MVP manifest schema or risk taxonomy.

## Contract to lock

- A scheduler call has an explicit scope and finite batch limit.
- Cursor and run/coordinator sidecars distinguish `complete`, deliberate `limited`, and `risk_interrupted`; only a matching risk-interrupted state is resumable.
- The scheduler composes `BiliClient`, `ManifestStore`, `MetaCursorStore`, `RunLedger`, `RunCoordinator`, audio budget, and reclaim; it does not own HTTP or create a second state machine.
- Long-live processing is explicit acceptance coverage, not a silent change to the default short-video pilot filter.
- Multi-hour audio is checked before download against current `audio/` usage plus the conservative 64 kbps estimate, then reclaimed after successful archive.
