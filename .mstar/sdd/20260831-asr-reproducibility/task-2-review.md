# Task 2 Review — ASRConfig/ASRRunner and coordinator integration

## Spec Compliance

**Verdict: Needs fixes.** The implementation provides the requested class names and a lazy per-instance model field, but it does not satisfy the full frozen contract.

- `ASRRunner` lazily constructs and reuses `_model` for an explicitly injected runner. Generation normalization and the compatibility wrapper remain present.
- `trust_remote_code=False`, CPU default, offline/local intent kwargs, and redacted error messages are present in the implementation.
- The coordinator accepts an additive `asr_runner` and routes audio rows through it when supplied; subtitle-first rows are not sent through that ASR stage.
- However, `RunCoordinator.run_batch()` does **not** create a default run-scoped runner after the `archive_writer` boundary. With the default path, each audio row still calls `asr_module.transcribe()`, which creates a fresh `ASRRunner` and model. Thus the required production/run-scoped reuse occurs only when an external caller manually injects a runner, rather than as coordinator lifecycle behavior.
- `ASRConfig` validation is materially weaker than the contract: it does not type-check or reject empty/whitespace `model_revision`, `device`, or `local_source`, and `_FORBIDDEN_SOURCE` only catches some markers at the beginning of a string. Embedded absolute paths, URLs, and forbidden credential markers can pass. Since `provenance()` emits `model_name` and `local_source` verbatim, this permits forbidden identifiers/path-like values to enter persisted evidence if callers provide such config.
- The factory fallback on `TypeError` retries with a reduced kwargs set. This violates deterministic factory kwargs and can mask a genuine `TypeError` raised inside a factory. It also drops offline/local intent. Revision is passed as `revision`, while the diff/report and requested deterministic contract identify model revision separately; this should be confirmed and made exact against the frozen interface.
- No global cache, worker pool, daemon, or new network owner was observed. The runner does not directly mutate manifest state.

## Strengths

1. Model construction is lazy for an explicitly supplied `ASRRunner`, and repeated `transcribe()` calls on that runner reuse one model.
2. Model construction kwargs explicitly disable remote code and carry CPU/offline/local intent.
3. Existing normalization and output conversion functions remain available; errors are wrapped into the existing `ASRDependencyError`/`ASRModelError` classes with non-sensitive messages.
4. Coordinator injection is additive and preserves the existing monkeypatchable compatibility seam.
5. Subtitle-first routing occurs before audio/ASR handling, and no ASR runner is needed for that branch.

## Issues by severity

### High

- **Coordinator does not establish the required run-scoped lifecycle.** `run_batch()` enters `archive_writer` and immediately processes rows, but never constructs a runner for the batch. Default audio processing calls the compatibility wrapper per row, reconstructing the model. This directly fails the frozen requirement that the coordinator create/reuse a runner within the writer-owned run scope. Fix by constructing one runner only after writer acquisition, while retaining the compatibility behavior as a deliberate compatibility path where required, and ensure it is not instantiated for subtitle-only batches.

- **Provenance redaction is not safe for all accepted configuration values.** `ASRConfig` accepts arbitrary `model_name` and insufficiently validates `local_source`, and `provenance()` returns them unchanged. URLs, absolute paths, and credential-like markers can therefore leak. Strengthen validation/redaction so provenance contains only opaque, safe identifiers/revisions/config values and rejects or redacts every forbidden marker, including embedded occurrences and Windows/UNC/path forms.

### Medium

- **Factory kwargs are not deterministic.** Catching any `TypeError` and retrying with fewer kwargs changes invocation semantics and can hide real implementation errors. The required fake-factory contract should receive one fixed kwargs mapping (including `trust_remote_code=False` and offline/local intent); unsupported injected fakes should be updated rather than silently retried.

- **Config validation is incomplete.** Validate all fields’ declared types and non-empty semantics, including `model_revision` when supplied, `device`, and `local_source`; reject whitespace-only values. Validate the exact revision keyword required by the frozen interface and tests (`model_revision` versus `revision`) consistently.

- **Required tests are missing or non-binding.** The runner reuse test remains `xfail(strict=False)`, so it cannot fail the implementation. There is no effective coordinator test proving one injected/default runner is reused across multiple audio rows, no lifecycle test proving construction occurs after writer acquisition and is released at scope end, and no test proving subtitle-first rows do not instantiate a runner. Provenance tests do not exercise hostile values passed through `ASRConfig`/`provenance()` directly.

### Low

- Several modified lines collapse long expressions into one line, reducing readability and diverging from the surrounding formatting. This is not independently blocking but should be cleaned while correcting the logic.
- The implementer report says it modified `progress.md`, which is outside the task’s permitted source/test files and conflicts with the explicit Phase 1 instruction not to modify `.mstar` knowledge content. The supplied diff does not show that file, so confirm the actual review range and remove unrelated changes if present.

## Assessment

**Needs fixes.** The core reusable runner exists and the compatibility/error boundaries are directionally correct, but coordinator default lifecycle reuse, strict config/provenance safety, deterministic factory invocation, and binding tests are still actionable gaps. Do not mark this task Approved until those issues are corrected and the required tests demonstrate the contracts.