### Task 2: Enumerate and process all pages

- [ ] Implement `list_pages`; create one ledger row per `PageIdentity`.
- [ ] Thread each page `cid` through `probe_subs` and `fetch_playurl_audio`.
- [ ] Keep p0 and p1 status transitions independent and resumable; skip unresolved rows.
- [ ] Two-page fixtures for subtitle and audio branches (no live HTTP).

