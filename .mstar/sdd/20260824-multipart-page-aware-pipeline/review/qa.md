---
report_kind: qa
role_id: qa-engineer
plan_id: "20260824-multipart-page-aware-pipeline"
verdict: Approve
qa_gate: mandatory
qa_mode: full
generated_at: "2026-08-24"
review_cwd: "/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline"
working_branch: "plan/20260824-multipart-page-aware-pipeline"
head: "361530d0a4da34de93bb86c778d1efbe061500c4"
review_range: "a79b84b6f9586410941503a5e04989eca020efe6..361530d0a4da34de93bb86c778d1efbe061500c4"
---

# QA Report (mandatory / full)

## Checkout alignment

| Field | Assignment | Observed |
|-------|------------|----------|
| Review cwd | `.worktrees/20260824-multipart-page-aware-pipeline` | match |
| Working branch | `plan/20260824-multipart-page-aware-pipeline` | match (`git rev-parse --abbrev-ref HEAD`) |
| HEAD | `361530d0a4da34de93bb86c778d1efbe061500c4` | match (`git rev-parse HEAD`) |
| Review range | `a79b84b6..361530d0` | `git log` lists 7 commits, tip `361530d` |
| QC consolidated | Approve, same range | match |

Worktree dirty only: untracked `bilibili-asr-archive/src/bili_asr.egg-info/` and `bilibili-asr-archive/uv.lock` (not in review range; ignored for acceptance).

## DoD / Acceptance Criteria mapping

| AC | Evidence (tests; suite below) |
|----|-------------------------------|
| Two-page fixture → `bvid:p0` and `bvid:p1` with distinct `cid` and independent outcomes | `tests/test_page_pipeline.py`: `test_list_pages_zero_based_indices`, `test_harvest_pages_independent_status`, `test_download_pages_independent_status`, `test_asr_pending_p0_failure_does_not_suppress_p1` |
| Subtitle/audio requests use each page cid; never silent page zero | `test_probe_subs_none_cid_on_two_page_raises`, `test_probe_subs_uses_explicit_cid_not_pages0`, `test_fetch_playurl_audio_none_cid_on_two_page_raises`, `test_fetch_playurl_audio_uses_explicit_cid` |
| Artifact paths distinct and stable across reruns | `tests/test_archive_md.py`: `test_write_archive_pages_do_not_collide_and_rerun_is_stable`; `tests/test_page_identity.py`: `test_artifact_stem_has_no_colon` |
| Legacy single-page migrate or explicit unresolved; artifacts unchanged; no auto page assign | `tests/test_manifest.py`: `test_migrate_single_page_bare_row`, `test_freeze_multipart_bare_row_byte_stable`, `test_migrate_stops_on_pN_artifact_collision`, `test_migrate_collision_existing_work_id_row`, `test_migrate_collision_on_existing_p0_artifact`, `test_get_compatible_does_not_guess_among_pages`; CLI STOP: `test_cli_harvest_subs_bvid_unresolved_stops`, `test_cli_download_audio_bvid_unresolved_stops`; `test_write_archive_unresolved_keeps_bare_bvid_stem` |
| Full Python 3.12 suite; no live HTTP / model download | Command below; 147 passed; tests use fixtures/`monkeypatch` HTTP, no model download |

QC inputs: `qc-consolidated.md` Decision **Approve**; open Critical/Warning 0; open R# none. `{HARNESS_DIR}/projects/` absent — no residual register entries.

## Pytest (full, this HEAD)

Cwd: `/root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive`

Command:

```text
.venv-pm/bin/python -m pytest -q
```

Output:

```text
........................................................................ [ 48%]
........................................................................ [ 97%]
...                                                                      [100%]
147 passed in 0.38s
```

Exit 0. No live HTTP. No model download.

## Findings

None.

## Not tested

Live Bilibili HTTP, real SESSDATA, SenseVoice model download, real media transfer (plan Global Constraints / STOP).

## Residual

Open R#: none. Findings cleanup: zero-residual. Satisfied.

## Recommendation

**Approve.** Recommend plan `Done`. Do not merge Git. No PR.

Working branch used: `plan/20260824-multipart-page-aware-pipeline`
