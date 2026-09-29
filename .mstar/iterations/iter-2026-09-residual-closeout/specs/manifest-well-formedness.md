# Manifest well-formedness: one definition, three readers

> Promoted to: `{KNOWLEDGE_DIR}/architecture-patterns/operational-sidecars.md` § "Manifest well-formedness: one definition, three readers" (iteration-close 2026-09-18).
> Iteration-scoped spec, `iter-2026-09-residual-closeout` · Phase 1 §1.6 review chain complete;
> PM lock pending ·
> implemented by `{PLAN_DIR}/20260918-verification-surface-truth.md` ·
> closes `e2e-23191782-season-7686105 · R2`.

## 1. The question this settles

The repo has three readers of the same manifest projection and, today, **two answers** to "is this
manifest well-formed?" — and the reader that answers *yes* still exits non-zero on the same input, so
the disagreement is about the exit contract as much as about the word "malformed".
`sidecar_projection.project_manifest_records` emits `manifest_duplicate_work_id` whenever a `work_id`
appears on more than one line and returns the latest valid row — which is correct for an append-only
store. Its three callers then treat the signal three different ways:

| Reader | Treatment of the diagnostic | Consequence on a normally-produced archive |
|---|---|---|
| `integrity.py` (`verify`) | string absent from the recognised vocabulary (L211–229) → else-branch (L228-229) → `structural_input_error` | `defects: 0` but `diagnostics: [structural_input_error]`; `cli.py`'s `0 if not payload["defects"] and not payload["diagnostics"]` (L2800) ⇒ **exit 1** |
| `coverage_report.py` (plain `coverage`) | two judgements in one file: forces `manifest_state = "malformed"` (L76-77) **and** carries the code into the report's `diagnostics` set (L68-75) | `denominator_available = False` (L198) ⇒ `{"count": None, "state": "unavailable"}` (L223-224), every ratio blanked, **exit 1** (`1 if report.data["diagnostics"] else 0`, cli.py L1497) |
| `cli.py` (`coverage --quality`) | its own copy of the same projection (L1267-1274); no `manifest_state` override | denominator correct — `{"count": 39, "state": "available"}` — **but the exit code is wrong the same way**: `1 if (diagnostic_rows or has_defects) else 0` (L1478) turns the same history into exit 1 |

Measured 2026-09-17 on the season archive (39 work_ids, 15 of them carrying 2–3 rows, all appended by
the product's own paths): `verify --scope BV1RFoxBqEzo:p0` → `checked: 1 / defects: 0 / diagnostic:
structural_input_error / EXIT=1`, while `coverage --quality` on the same root reported `39 available`.

Measured again 2026-09-18 on a scratch root built for this review (`/tmp/arch-probe/root2`: three
manifest rows for one work_id — `needs_audio` → `audio_ok` → `archived` — plus a complete, valid
transcript bundle and all four sidecars), because the facts the table above rests on are easy to get
half-right:

- `verify --archive-root <root> --format json` → `{"checked": 2, "defect_count": 0, "defects": [],
  "diagnostics": ["structural_input_error"], "authoritative": true}`, **exit 1**.
- `coverage --archive-root <root> --format json` → `denominator {"count": null, "state":
  "unavailable"}`, diagnostics `[manifest_duplicate_work_id]`, **exit 1**.
- `coverage --quality --archive-root <root> --format json` → `denominator {"count": 2, "state":
  "available"}` **and still exit 1**, with `diagnostics [{"category": "manifest", "code":
  "manifest_duplicate_work_id"}]` — the only diagnostic on the archive.

The third line is the one that changes a decision: **the `--quality` branch is a correct reference
for the denominator, not for the exit code.** Dropping `coverage_report.py`'s `manifest_state`
override alone restores the denominator and leaves the code in the report's `diagnostics` (the
override at L76-77 is downstream of the projection at L68-75 and cannot remove it), so plain
`coverage` would still exit 1 on a healthy archive — the same "looks fixed while the contract stays
broken" failure this spec rejects in §4 for `integrity.py`. Measured after dropping only the
override: `denominator {"count": 2, "state": "available"}`, `cumulative.state "complete"`,
diagnostics still `[manifest_duplicate_work_id]` ⇒ exit 1.

## 2. The definition (locked)

**Append-only state history is well-formed.** A `work_id` appearing on several manifest lines is the
store's normal encoding of a state transition sequence (`needs_audio` → `audio_ok` → `archived`), not a
defect and not a malformation.

This is not a new preference; it is the recorded invariant: `operational-sidecars.md` #10 requires
durable sidecars to stay *append-oriented and projection-based* — "append revisions or attempts
durably, and derive the latest validated row/run without materializing unbounded history". A definition
that called the resulting history malformed would contradict the storage model the same knowledge doc
mandates.

**Consequently, the following are NOT defects and NOT diagnostics:**

- a `work_id` present on more than one line;
- the state transitions encoded by those lines.

"Not a diagnostic" is meant operationally, because a name is not what judges an archive — a reader's
exit rule is. In every reader the fact must reach **neither** `defects` **nor** any diagnostic list
that drives a non-zero exit, and no reader may file it as a record-kind or manifest-kind *failure*.
The emitter may keep reporting it: `sidecar_projection.project_manifest_records` stays as it is (the
projection is allowed to say what it saw). What is forbidden is three readers each inventing what it
means.

So the definition is implemented once, as one named set that the projection module owns, and every
reader subtracts it:

- the single statement lives beside the projection that emits the code
  (`ORDINARY_HISTORY_DIAGNOSTICS`, `sidecar_projection.py`);
- `integrity.py` maps it to *nothing* (its own loop keeps failing closed for every other
  unrecognised code — §3.2);
- both `coverage` paths subtract it from the diagnostics they project (L68-75 in
  `coverage_report.build`, L1267-1274 in `cli._cmd_coverage_quality`), so no exit rule sees it.

Three subtraction sites quoting one set is the smallest shape that keeps the judgement single; three
independent *judgements* — which is today's state — is what the next reader would get wrong again.
The precedent is recorded: `operational-sidecars.md` #6 keeps the defect/content class knowledge in
one module precisely because "one union field would flip healthy ASR archives to exit 1 unless every
consumer learned which codes are defects".

Note for the implementer: `coverage_report.py` also contains a `_read_manifest` helper (L288-329)
whose duplicate branch files `("manifest_duplicate_work_id", "record")` at L325. It has **no call
site** anywhere under `bilibili-asr-archive/` (src/ or tests/) — it is unreachable, so it is neither
the place the fact "stays visible" nor a second judgement to keep in sync. It is left untouched
(criterion 1 retains it) and must not be cited as the reason the emitter stays.

**These remain defects, unchanged:** unparsable lines (with the existing truncated-final tolerance),
invalid statuses, invalid `bvid`/`work_id` pairing, row/byte limits, symlinked sidecars, missing
declared artifacts, identity/path mismatch, and everything else the existing vocabularies already name.

## 3. Required behaviour after the fix

1. `verify` on a healthy archive whose manifest carries real state history: `defects: []`,
   `diagnostics: []`, and **exit 0**. The fixture must carry a `coordinator/attempts.jsonl`
   (integrity.py L238-241 files `missing_attempts_sidecar` when it is absent, which keeps the exit
   at 1 for a reason unrelated to this definition).
2. `verify` on genuinely malformed input: still non-zero exit, still reported — the fix is
   bidirectional and must not be a blanket silence. Unrecognised codes still reach the else-branch
   (L228-229) and still become `structural_input_error`; the row/byte-limit, invalid-status,
   invalid-bvid, truncated-attempts and missing-sidecar branches are unchanged.
3. `coverage --format json` on a healthy archive: `denominator.state == "available"` with `count`
   equal to the number of work_ids, `cumulative.state == "complete"` when the rows are complete, and
   **exit 0** — no diagnostic whose only cause is ordinary history. `coverage --quality --format
   json` reaches the same verdict: exit 0 when the rows are healthy (its exit is
   `1 if (diagnostic_rows or has_defects) else 0`, so a defect code still fails it).
   The CSV projection's `denominator_*` columns, the column tuple and `schema_version` stay
   byte-compatible; the `diagnostic_summary` *cell* legitimately loses the code for such archives —
   that is data, not schema.
4. `coverage_report.py` keeps its `manifest_duplicate_work_id` handling as-is where it already
   exists (the unreachable `_read_manifest` branch at L325; see §2's note) — nothing in this spec
   asks for that helper to be deleted or changed.
5. `recover`'s `authoritative` is unchanged: it is computed from the projection's diagnostic *sets*
   and the presence of the manifest/attempts sidecars (integrity.py L233-236), never from
   `report.diagnostics`, and `manifest_duplicate_work_id` is not in its failure sets nor does it
   change `manifest_state` (sidecar_projection.py L216 only adds the code, L217 still stores the
   latest valid row). Verified by measurement: with the recognition branch added, `authoritative`
   is `true` before and after, and `defects` is identical.

## 4. Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Map the diagnostic to a *benign* diagnostic name in `integrity.py` | `cli.py`'s exit rule counts **any** diagnostic, so a benign entry still forces exit 1 — the contract stays broken while looking fixed |
| Drop only `coverage_report.py`'s `manifest_state = "malformed"` override and leave the code in the report's `diagnostics` | The denominator comes back but the report is still red, for the same reason the row above is rejected: `_cmd_coverage` returns `1 if report.data["diagnostics"] else 0`. Measured: exit 1 with `denominator {"count": 2, "state": "available"}` — a half-fix that reads like a fixed contract |
| Treat `coverage --quality` as the already-correct reader and change nothing there | Its denominator is correct; its exit is not (measured exit 1 on a healthy archive whose only diagnostic is this code). "One definition, three readers" would then be false in the one reader the other two are told to copy |
| Stop `project_manifest_records` from emitting the code at all | Not this iteration's licence: criterion 1 explicitly retains the emitter at `sidecar_projection.py:216`, and the projection reporting what it saw is not the defect — three readers deciding what it means is |
| Call duplicates malformed and stop `ManifestStore.upsert` from appending repeated rows (compaction / in-place rewrite) | Contradicts `operational-sidecars.md` #10's append-oriented invariant; a storage-model change is out of this iteration's scope by its Non-Goals |
| Leave `coverage` as is and tell operators to use `coverage --quality` | Leaves the completeness command unable to state its own denominator, and leaves two schemas of one command disagreeing about one input |

## 5. Test obligation

Every fixture that exercises this definition must write **two or more rows for the same `work_id`** —
the existing clean-archive test writes exactly one row per work_id and asserts only `defects == []`,
never the diagnostics set or the exit code, which is precisely why the defect survived. The plan's
Task 2 pins: healthy history → exit 0, malformed input → non-zero, and `coverage` denominator
availability **and exit code**.

Three existing tests pin the *old* contract, and an implementer who has not been told will read them
as the specification. They assert the defect, so they must be inverted, not merely extended:

| Test | Today | After |
|---|---|---|
| `tests/test_coverage_report.py:129` `test_duplicate_manifest_makes_denominator_unavailable` | `count is None` **and** the code present (L132-133) | count is the work_id count, code absent |
| `tests/test_coverage_report.py:248` `test_cli_returns_diagnostic_exit` | doubling the manifest makes `coverage` non-zero (L250-251) | the duplicate is not a failure; a genuinely malformed row is |
| `tests/test_cli_help.py:227` `test_module_coverage_formats_and_diagnostic_exit` | duplicated manifest → `returncode == 1` and the code in stdout (L242-245) | the code is absent from stdout and the denominator is available; the non-zero half moves to real damage |

Two traps when inverting them: an archive whose sidecars are absent reports `evidence_missing` for
cursor/run-ledger/scheduler, and `verify` without `coordinator/attempts.jsonl` reports
`missing_attempts_sidecar` — both keep the exit at 1 for reasons that have nothing to do with this
definition. Exit-0 assertions need a complete fixture; the code-absent assertion does not.

## 6. Evidence base

- `{WORKFLOW_DIR}/e2e-23191782-season-7686105/reports/e2e.md` — finding F6 and the register-review
  section that measured all three readers against one archive.
- `{PROJECT_DIR}/_default/residuals.json` — `e2e-23191782-season-7686105 · R2` (severity high),
  including the extended blast radius recorded 2026-09-17.
- Architect review pass 2026-09-18 (this spec's line references were re-checked against the tree, and
  the exit-code half of the coverage defect was measured rather than inferred): a scratch archive at
  `/tmp/arch-probe/root2` with three manifest rows for one work_id and all four sidecars valid
  produced `verify` exit 1 / `coverage` `count None` exit 1 / `coverage --quality` `count 2` **exit
  1**; the same tree with `ORDINARY_HISTORY_DIAGNOSTICS` subtracted in the two coverage projections
  and the recognition branch added to `integrity.py` produced `verify` `diagnostics []` exit 0
  (`defects` and `authoritative` unchanged), `coverage` `count 2` / `state available` /
  `cumulative complete` / `diagnostics []` exit 0, and `coverage --quality` exit 0. The patched runs
  executed in-memory copies of the modules; no product file was edited.
- `operational-sidecars.md` #10 (append-oriented, projection-based) and #3 (the stage-attempt ledger's
  scope) — the invariants this definition follows rather than overrides; #6 for the one-module
  class-knowledge precedent quoted in §2.
