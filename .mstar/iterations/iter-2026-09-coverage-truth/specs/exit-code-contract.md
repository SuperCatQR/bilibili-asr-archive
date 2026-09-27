---
spec_id: exit-code-contract
title: verify / coverage exit-code contract — findings graded, backlog not an error
status: draft
owner: architect
created_at: 2026-09-27
iteration: iter-2026-09-coverage-truth
---

# Exit-code contract (iteration-scoped draft)

> Architect seat, Phase-1 chain seat 2 of 3. Decides compass D5/Q3 and
> dashboard-plan DD1.

## 1. Decision (DD1 resolved): option (a) — backlog → exit 0, `--strict` restores exit 1

Rejected alternatives: (b) graded exit codes (e.g. backlog=3) — invents a new
vocabulary every caller must learn, and `retryable_incomplete` is *normal
operations*, not a defect class; (c) doc-only — leaves cron unusable, which is
the operator pain this iteration exists to remove.

## 2. Contract

`bili-asr verify` and `bili-asr coverage` partition findings into exactly two
classes. **Code-accurate boundary (architect, seat 2)** — the shipped readers
already emit distinct signals, and the fix is a re-classification at the CLI
boundary (`cli.py:3552` verify, `cli.py:1949` / `:1967` / `:1971` coverage),
not a new findings taxonomy:

| Class | Meaning | Shipped signal today | Exit contribution (default) |
|-------|---------|----------------------|------------------------------|
| `defect` | archive corruption / format violation — malformed manifest JSONL, schema-violating rows, store inconsistency | verify: `diagnostics` (e.g. `structural_input_error`, `missing_attempts_sidecar`) + non-retryable defect codes; coverage: `diagnostics` (`manifest_malformed`, `denominator_unavailable`, …) | non-empty → exit `1` |
| `backlog` | work not yet done — `retryable_incomplete`, `needs_audio` / `pending` rows | verify defect code `retryable_incomplete` only (`integrity.py:385`); coverage per-row `status` in {`pending`,`meta_ok`,`sub_checked`,`needs_audio`,`audio_ok`} | reported in a separate `backlog:` section; **zero effect on exit code** |

- Default invocation: exit `0` when the archive is well-formed, **regardless
  of backlog size**. The measured case (`e2e-23191782-subtitle-publish-webdav`,
  84 `needs_audio` rows / 84 `retryable_incomplete` / 6 published rows clean)
  must exit `0` and print the backlog section.
- `--strict`: pre-cutover behaviour — any finding (either class) → exit `1`.
  Documented as the CI/compatibility mode.
- **Malformed ≠ backlog, as code-able assertions.** malformed/structural
  verdicts are reserved for the `defect` class and are exactly the cases where
  an input cannot be parsed or validated at all. The high residual
  `e2e-23191782-season-7686105 · R2` (readers killing a healthy manifest)
  stays closed by guards already shipped at the reader layer; this contract
  pins the CLI-side half:
  - a manifest that parses and whose rows satisfy the manifest schema
    (`manifest.py` `VALID_STATUSES` + work_id/bvid identity) is **well-formed**
    and must not surface as `defect`;
  - append-only history (multiple rows sharing one `work_id`) is not itself a
    defect — backlog/duplicate attribution only;
  - a coverage denominator is "unavailable" only on a genuine read/parse
    failure, never as a forced override.

## 2h. PM scope call on the DECLARED axis (asked by the round-2 re-review, 2026-09-27)

§2f ruled item 2 as "stop dropping the inferred candidate when `exists()` is false". The round-2
re-review asked whether the principle also covers a *second* axis it did not name:

**The declaration axis.** `quality._artifact_paths` computes `inferred = not values` (`quality.py:424`)
and only then offers the inferred candidate families, while `verify`'s §2f widening builds
`raw_candidates` unconditionally (`integrity.py:415-443`). So a row that declares **any** path key never
has the two inferred raw names offered to `coverage`, and an escape at the *undeclared* raw location is
invisible to it while `verify` reports it.

**Ruling: §2f's principle extends to the declared axis — the pair must agree there too. But the fix is
NOT owed by the closed iteration, and it is not a `warn-only` follow-up: it is registered (D-R10) with a
measured closure path.**

Reasoning, in the order that decides it:

1. **The principle is about the pair, and it does not name the axis.** §2f's operative sentence is "the
   agreement property is over the reader **pair**", and the closing rule it imposed is that "any future
   agreement sweep must enumerate candidates from the readers' own tables, not from the shapes already
   known". A declaration gate is exactly a difference between the readers' own candidate tables, so
   leaving it open contradicts §2f's own remedy. The letter said *existence*; the principle it states is
   broader, and the principle governs.
2. **But the axis is not a regression and not writer-reachable.** The reviewer measured it as **neutral**
   on the §2f diff (`pre` and `post` both 1/0; a different form exists at `base0`), and no writer emits a
   declaring row that also leaves an escaping raw at the other location. It is fail-open on one reader
   only, and the failure is not silent (the other reader reports it). That is why this is a **registered
   low-severity item with a known cost**, not a blocker for the closed iteration.
3. **The PM could not reproduce the reviewer's end-to-end exit split.** Three fixture attempts produced
   *invalid bundles* that both readers correctly flagged (`missing_transcript` / `identity_mismatch`),
   so the end-to-end 1/0 was not independently confirmed. What **was** confirmed is the structural
   asymmetry, by reading both gates on `main@2696711`. D-R10 is therefore registered at **structural
   strength with the non-reproduction disclosed** — not at the strength of the reviewer's measurement.
   Anyone closing it must first build a *valid* `write_archive` bundle (the writer's own naming rule,
   `archive.py:455-471`, including the `.bundle-ready` marker) and then measure.

**What would settle it** (for whoever owns D-R10): offer the inferred raw candidates to `coverage`
*in addition to* declared values rather than *instead of* them, then re-run the pair sweep over the
candidate tables of both readers. The reviewer's attached candidate patch
(`review/qc3-r2-candidate-B-R18.patch`) does this and passes the touched suites plus the full suite; it
is **not applied** — a merged-and-closed iteration does not take new code, and the cost it adds
(~0.56 s → 2.01 s on 3000 healthy declared rows, deliberately naive) belongs in a change that can be
profiled and reviewed on its own.

## 3. Caller impact list (Q3)

Verified call sites of the two commands (disk survey 2026-09-27):

- `src/bili_asr/coverage_report.py:129` — ledger exit-code echo (internal;
  follows the command's own exit, unaffected by the class split).
- **No cron/systemd timer, Makefile, or CI job** invokes either command (disk
  survey: no crontab/`Makefile`/`.github` references the strings). The
  consumers are human-run and docs.
- **Docs that show the commands and must gain one `--strict` sentence**: README
  §Command reference (`bili-asr coverage` / `bili-asr verify` blocks,
  `README.md:475-485`) and §coverage/verify prose (`:754-771`);
  `docs/artifact-root.md:97-98`; `docs/audio-retention-policy.md:206,250`.
  These are presentation-only — they record invocations, not exit-code
  expectations.
- **e2e workflow snapshots** that observed the current (buggy) exit-1-on-backlog
  behaviour, recorded as findings not pass criteria — they do not pin a
  non-zero expectation, so **no e2e row needs its expectation flipped**, but the
  disposition must note the contract change:
  - `e2e-23191782-subtitle-publish-webdav` F-4 (low): the run itself flagged
    "exit 1 on a store that legitimately holds unprocessed rows" as a PM
    decision point. Its A6 row passes on the six rows regardless of exit code,
    so the change is compatible.
  - `e2e-23191782-asr-vs-subtitle-webdav` A8: `verify` exited 1 with
    `authoritative:false` + `missing_attempts_sidecar` (a **diagnostic**, class
    `defect` under §2) while `coverage --quality` exited 0 on the same
    archive — the readers disagreed. Under this contract verify still exits 1
    (a real diagnostic), so **no silent change**; the reader-disagreement
    follow-up stays registered to the media-queue service's attempt-evidence
    backfill, outside this plan.
- **Consequence: no caller migration.** The only behaviour change is
  exit-1→0 on backlog-only archives; every archived invocation either expected
  exit 0 already or recorded exit 1 as a finding. README's command table gains
  one sentence on `--strict`.

## 4. Status queue view (product decision D7/DD2, restated here as contract input)

- Grouping: by gap type — `缺字幕` / `缺音频` / `缺转写` — each with count +
  detail rows (default top 20 per group, `--all` for full list), sorted
  `pubdate DESC` within group.
- Header line: totals + last-fetch timestamp (from `acquisition_runs`).
- Data source: `MediaQueueRepository.list_queue_gaps` / `count_queue_gaps`
  (`queue-cutover-contract.md` §4). Ordering resolved (architect, seat 2): the
  status command is **store-first, manifest-never** — the store is the queue's
  authority (compass D2), and within the compat window the manifest is only a
  legacy *reader*, never a status data source. The headline coverage figure
  (§5) is the single manifest-reading surface, and it carries the explicit
  "source + reproduce command" annotation.

## 5. Coverage reproducibility note

Every coverage figure printed carries a source annotation: **which relation it
was computed from** (store relation vs manifest row counts), the row counts,
and the command to reproduce it (`bili-asr coverage --archive-root <root>`). A
figure computed from a different host's archive must be qualified with that
host. Headline numbers become reproducible on any machine holding the archive
(closes `20260925-archive-db-review · R3`-low's "originates on another machine"
half by making origin explicit and local). During the A-plan compat window the
denominator may still be manifest-derived; the annotation must say so rather
than imply a store source.

## 6. Code-able assertions (for the dashboard plan's tasks)

1. `verify` on a fixture with only `needs_audio` rows exits `0` and prints a
   `backlog:` section naming them; same fixture with `--strict` exits `1`.
2. `verify` on a manifest with one malformed JSONL line exits `1`, class
   `defect`, and never emits `backlog:` for that line.
3. `coverage`'s printed totals equal the row counts of the store/manifest it
   read (asserted in tests against fixture row counts).
4. `status` on a metadata-only root shows all three gap groups with the
   fixture's pubdate ordering.
