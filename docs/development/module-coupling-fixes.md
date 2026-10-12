# Module coupling repair

This change addresses issues #372–#383 against the fixed source baseline
98904edbb01fd23a5c3fb857a27e919df6b34e70. It preserves stored schema DDL,
profile identities, publication bytes, retry history and caller-owned transaction
boundaries. It does not migrate or requeue a production archive.

## Ownership changes

| Issue | Result | Regression evidence |
| --- | --- | --- |
| #372 | Schema primitives live in storage/schema_contract; optional validation is composed by archive_validation over independent extension_contracts. | test_coupling_schema_validation: partial/unknown/changed schemas, no implicit DDL, direct validation compatibility. |
| #373 | workflow_outputs, artifact_policies and artifact_releases own audio/publication/policy/release writes. Services retain fencing and installation order. | test_coupling_storage_transactions plus workflow staging, transfer and policy suites. |
| #374 | Input preparation, content normalization and versioned renderers have separate owners; registry composes renderers. | test_frozen_publication_compat compares v1/v2 input IDs and artifact SHA-256 against the original baseline. |
| #375 | file_ops owns locks, fsync, strict file creation and atomic replacement. Origin validation is independent; preserved_body_evidence owns read-only verification. | test_file_ops, test_export_lock and publication/import/series regressions. |
| #376 | services/editorial_application owns freeze, job association and render binding in one owned transaction; repositories share read projections. | Late render-binding failure rolls back input, association and scheduling; historical upgrade tests. |
| #377 | WorkflowControl declares peek_candidate and conditional claim(expected_candidate). | Independent MemoryControl exercises preparation failure, changed candidate, cancellation and lost lease. |
| #378 | SourceWorkflowPorts and typed acquisition/caption/factory protocols replace the full archive handler dependency. Provider CaptionPolicy owns its error/selection vocabulary. | Independent source fake installs captions/audio; existing YouTube budget and Bilibili policy regressions. |
| #379 | artifact_child/artifact_fences provide the child access kernel; ASR does not import business services. | Child hash/fence checks, persistent session and timeout/cancellation suites. |
| #380 | profile_codec freezes v2 omission and nested-extension encoding rules independently of runtime strategy defaults. | Golden historical digests, config field mapping, unsupported extension rejection. |
| #381 | storage and ASR facades load exports on request; CLI registry resolves explicit handler owners. Help parses before opening persistence capabilities. | Fresh-process config/model/parser/help imports, import order, runtime type annotations, falsey factory and installed CLI tests. |
| #382 | Import graph resolves relative/aliased child imports, local imports and literal import_module calls; distinguishes type-only and executable-entry edges. | Parser, transitive reachability, SCC membership/edge regressions, ASR layer rule and high-risk write ownership. |
| #383 | Contract/export fixture I/O and installed subprocess text encoding are explicit UTF-8. | Nine original export regressions with Python UTF-8 mode disabled on Windows cp936, plus independent JSON I/O subprocess. |

## Dependency graph and remaining exception

The same explicit-edge parser gives the following comparison. This covers
top-level and function-local imports and excludes type-only/executable-entry
edges. Implicit package initialization and arbitrary dynamic imports are checked
separately through supported fresh-process entrypoints.

| Measure | Baseline | Repaired |
| --- | ---: | ---: |
| Python modules | 213 | 239 |
| Explicit internal edges | 893 | 913 |
| Cyclic strongly connected components | 6 | 1 |
| Largest cyclic component | 20 | 8 |

Additional modules give existing responsibilities distinct owners; total edge
count alone is not a measure of coupling quality. No top-level explicit cycles
remain. The remaining deferred business component contains content_rights,
manuscript_artifacts, preserved_body_evidence, publication, publication_tags,
storage.import_origins, storage.publication and storage.source_supplements.
It represents current rights/origin/edition validation lookups. Tests pin both
its exact allowed members and its internal edges; new components, expansion or
new internal edges fail. Further removal requires changing the ownership of
those business lookups and is not claimed by this repair.

## Supported entrypoints

The console script bili-asr and python -m bili_asr remain supported.
python -m bili_asr.cli and python -m bili_asr.cli.main use the same dispatcher.
The package exports main as a callable module, build_parser and
DEFAULT_ARCHIVE_ROOT. Legacy private handler exports remain lazy aliases, but
production dispatch uses the command owner's function. Tests patch the owner
or the entrypoint's explicit parser/dispatcher seams.

The historical cli.main.main import alias remains until the next minor release
(0.2), without a production dependency back to the CLI facade. ASR transcribe
and provenance retain factory injection; a callable with false truth value
remains a valid factory. Public annotations resolve without importing a runner.

## Validation scope

Verification uses project-authored synthetic fixtures and offline test doubles.
No real model/GPU inference, paid editorial endpoint or production retry action
is included. Fixed schema resources and contract documentation remain unchanged.
The contract checker still verifies 51 registered contracts and 26 JSON schemas.

The first managed checkout test attempt had directory permission errors.
A writable branch snapshot completed the Windows suite: 3226 passed, 82 skipped,
12 failed. One failed test patched the old roots_for location and was migrated
to artifact_root; it passed on rerun. The remaining failures concern Windows
symlink privileges, Linux loader/bash assumptions, platform path separators,
or temporary-directory root discovery. They are retained in the original
test evidence and are not reported as a successful Windows full suite.

Targeted final Windows tests cover architecture/import/facade/search/UTF-8 I/O
(79 passed) and isolated installed CLI behavior (13 passed). The default-cp936
run covers the eight origin binding failures, explicit export scope and an
independent subprocess (10 passed). Three independent agents implemented and
cross-reviewed the changes; a final read-only review also ran the 25 schema,
transaction and profile tests successfully.

Mutation checks detected an unconditional candidate claim, omitted render
binding and incomplete file writes. Each mutation was isolated/restored and is
excluded from the passing-test counts. Ruff E9, compilation and the contract
documentation check pass. Linux full-suite results are recorded after the final
run completes.
