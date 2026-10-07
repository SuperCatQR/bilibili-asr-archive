# CI test boundary

The default CI suite is the executable contract for the current SQLite workflow
control plane. It is collected from `tests/` by pytest and runs with the four
shards defined in `.github/workflows/ci.yml`.

## Categories

- **Current, blocking:** tests not listed in `tests/conftest.py::collect_ignore`.
  These cover the shipped package, SQLite repositories, workflow handlers,
  archive products, CLI behavior, and deterministic ASR fakes.
- **Retired, preserved for history:** the files listed in
  `tests/conftest.py::collect_ignore`. They target the removed coordinator,
  manifest, legacy queue, and pre-cutover CLI surfaces. They remain available
  for archaeology but are not a release signal.
- **Opt-in environment checks:** tests marked `live_smoke` or `scale`. They
  require `BILI_LIVE_SMOKE=1` or `BILI_SCALE=1` and are intentionally excluded
  from the normal PR gate.
- **Host-dependent checks:** GPU/ROCm, external API, and large persistence
  probes require a provisioned environment. They belong in a separately
  triggered operational workflow rather than the deterministic PR suite.

Changes that move a test between categories must update this document and the
collection policy in the same pull request. The default suite should remain
deterministic, offline, and runnable on the supported Python version.
