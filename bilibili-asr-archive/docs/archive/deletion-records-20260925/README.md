# 2026-09-25 deletion archive — published copy

**This directory is the second, tracked home of the 2026-09-25 deletion archive.** It was
published on 2026-09-28 by plan `20260928-workspace-reclamation` (Task 2) under compass **D12**,
so that the bytes survive any `.tmp/` sweep by construction rather than by prose exclusion.

`.tmp/deletion-records/` remains the **working original** and was **not** moved or deleted.
Before this publication it was the *only* surviving copy of anything on this page.

## Provenance

On **2026-09-25** the operator had the harness records of the parked iteration
`iter-2026-09-transcript-editorial-stages` deleted: 8 roots, 24 files, 433 316 bytes of
`.mstar/**` trees (plus the same layout inside two gitignored scratch fixtures). `HANDOFF.md` §9
is the authoritative record of what went and what remained.

The archive below was written to the **123pan delivery side** under `bili-asr-e2e/deletion-records/`.
**That delivery side is retired:** `/mnt/123pan` is not a mountpoint and is empty, its
`rclone-123pan.service` is gone, and no `bili-asr-e2e` tree exists anywhere under `/srv`. The
archive root that *did* move to `/srv` is the **product** archive
(`/srv/bili-asr-archive/{archive.db,manifest,transcripts}`) — it is not this archive and holds no
copy of it. §9's 123pan path is left unrewritten there, as the record of where the archive *was*
written; this page is the dated pointer to where the bytes now live.

## File inventory

| File | Bytes | sha256 |
|---|---|---|
| `harness-editorial-stages-deleted-20260925.tar.gz` | 147 218 | `d212a8b712fd25a7b17b9f6710720cec119bf4ed72934812221ec02ba196394e` |
| `pre-delete-report-20260925-harness-editorial-stages.txt` | 71 489 | `9d394651b4adb62e3e06648e154093b4de7a8c669007c7f0581f7a3f40dec413` |

Both sha256 values are recorded verbatim in `HANDOFF.md` §9, which read them back from the remote
after upload. This copy was verified **three ways** at publication (see below).

### What the tarball carries

A byte-exact copy of every deleted file — 24 members: the 4-file iteration package
(`delivery-compass.md`, `direction-lock.md`, `README.md`, `specs/editorial-stage-contract.md`),
the 2-file workflow snapshot (`snapshot.json`, `agent-flow.jsonl`), the two un-started plans
(`20260923-reading-edition.md`, `20260923-editorial-skills.md`), and the two duplicate package
copies inside each of the two gitignored scratch fixtures.

**The bytes that exist only here.** §9 records that the deleted on-disk `delivery-compass.md` was
**55 232 B** while every committed revision is 47 394 B — the on-disk file carried a delta that was
never committed, and that delta exists **only** in this archive. §9 also records that
`20260923-reading-edition.md` and `20260923-editorial-skills.md` were **never committed to any
ref**, and that `workflows/<id>/` was machine-local by design: for those three groups the archive
is the only copy, and after this publication that claim holds against a clone too.

## `HANDOFF.md` §9 anchors

- §9 heading: `## 9. The 2026-09-25 deletion — what went, what stayed, what is only in the archive`
- §9 "Deleted from disk (8 roots, 24 files, 433 316 bytes)" — the per-root table.
- §9 "**Archive — the only complete copy.**" — the two filenames, their byte sizes and their sha256
  values, and the sentence naming the 123pan delivery side. **Retired**, see Provenance above.
- §9 "**Recovery, by kind:**" — the three groups above, and the paths
  (`f33ee02`, `89a9ebb`, both kept branches) from which the iteration package is also recoverable
  from git.
- `.mstar/iterations/README.md:26` — the `iter-2026-09-transcript-editorial-stages` row, which
  points at `HANDOFF.md` §9 for the deleted package's recovery path.

§9 itself is left **byte-identical** by this plan; the pointer to this directory sits outside it.

## Verification (re-runnable)

```sh
# 1. the published bytes are identical to the .tmp/ working original
cmp .tmp/deletion-records/harness-editorial-stages-deleted-20260925.tar.gz \
    bilibili-asr-archive/docs/archive/deletion-records-20260925/harness-editorial-stages-deleted-20260925.tar.gz
cmp .tmp/deletion-records/pre-delete-report-20260925-harness-editorial-stages.txt \
    bilibili-asr-archive/docs/archive/deletion-records-20260925/pre-delete-report-20260925-harness-editorial-stages.txt

# 2. the hashes match HANDOFF.md §9's recorded values
sha256sum bilibili-asr-archive/docs/archive/deletion-records-20260925/*

# 3. the copies are tracked, not merely present on this disk
git ls-files bilibili-asr-archive/docs/archive/deletion-records-20260925/

# 4. the negative control: the .tmp/ working original still exists and still hashes to §9's value
sha256sum .tmp/deletion-records/*     # must be unchanged
```

The archive is small (two files, ~213 KB) and `pyproject.toml`'s `packages.find` /
`package-data` do not ship `docs/`, so publishing does not change the installed wheel.

**Residual risk (plan B `D-4`).** There is no automated gate asserting these bytes; a byte-asserting
test was considered and rejected on contract grounds (this plan is Git-and-documentation-only, and
plan A's checker is scoped to the documents the engine reads). What tracking buys is that loss
becomes a `git status` fact instead of a silent deletion.
