# Storage and metadata issue burndown

Date: 2026-10-06. Issue numbers are the current GitHub numbers from the
open-issue snapshot, not the older batch ledger. No issue state changed here.

| Issue | Resolution and evidence |
| --- | --- |
| #69 | Tag observations use a 256-entry LRU per run, with separate page answers so eviction cannot drop a page's tag writes. `test_tag_cache_eviction_preserves_page_answers_and_refetches_old_video` lowers capacity to two, exceeds it on one page, checks within-page deduplication and later refetch, and checks all stored inventories. Existing recent cross-page and multipart dedup tests remain. |
| #70 | Recorded freshness decision: resume starts a new observation cache; persisted tags alone cannot prove that current tags are unchanged or now empty. Repeated requests across runs remain intentional. `test_resumed_run_refreshes_tags_for_relisted_video` fails the first run after collecting tags, resumes at its cursor with the same video, and verifies a newly empty inventory clears old tags. This resolves the deferred design question, not a promise of zero redundant requests. |
| #75 | Author observations are page-scoped: later named pages refresh the label, nameless pages preserve it. Identical labels no longer restamp `updated_at`. `test_later_named_page_updates_author_and_nameless_page_preserves_it` and `test_identical_user_label_preserves_updated_at` cover these boundaries; existing nameless-run tests remain. |
| #90 | `list_queue_gaps` delegates positive limit validation to `_integer`. `test_gap_and_limit_validation_follow_the_module_rule` verifies scalar errors and bool rejection with the shared validator's messages. |
| #92 | Recorded transaction ownership: SELECT preflight on the supported DEFERRED connection starts no read transaction. Missing part/transcript/run refusals leave idle connections idle and preserve ambient caller transactions. `test_lookup_refusal_preserves_caller_transaction` covers audio part and transcript part/id/run, each idle and ambient; caller writes remain pending and caller rollback still works. No rollback of caller work was added. |
| #93 | Operator documentation now explains cross-view semantics: gone parts leave subtitle/audio acquisition queues but retained archived audio remains locally transcribable. Existing `test_each_gap_holds_exactly_the_parts_its_view_defines` checks gone membership across all three queues. No queue predicate change needed. |

The metadata-storage operational document records the cache, resume freshness,
user timestamp, transaction ownership, and gone-part contracts. #70 and #92
retain their deliberate behavior under explicit documented contracts; neither
is represented as an external live validation result.

## Verification

Focused WSL verification on Ubuntu-24.04, Python 3.12 from
`/home/chosenecho/.venvs/bili-asr-pipeline/bin/python`:

```sh
cd /mnt/c/wt/bd-s/bilibili-asr-archive
PYTHONPATH=src /home/chosenecho/.venvs/bili-asr-pipeline/bin/python -m pytest -q tests/test_metadata_ingest.py tests/test_metadata_repository.py tests/test_storage_queue_writes.py tests/test_storage_queue_gaps.py
```

Result: **180 passed in 140.56s**. The first run exposed fixture mistakes in
new tests (duplicate aids and an incorrect resume keyword) and the old limit
message assertions; these were repaired before the successful run.

The resume test was then strengthened from a limited run to an actual gateway
failure followed by resume. A supplementary run with that test and the metadata
CLI/end-to-end suites passed: **38 passed in 81.08s**.

```sh
PYTHONPATH=src /home/chosenecho/.venvs/bili-asr-pipeline/bin/python -m pytest -q tests/test_metadata_ingest.py::test_resumed_run_refreshes_tags_for_relisted_video tests/test_metadata_cli.py tests/test_metadata_e2e.py
```

`git diff --check` passes. Integration-wide verification belongs to the root
lane after all independent changes are combined.

## Evidence gaps outside this change

#61 still needs independent archive-wide, real-world collection coverage proof;
offline repository and ingestion tests do not establish it. #66 requires the
independent L2 review owned by the integration lane. Neither is claimed resolved
by this report.
