### Spec Compliance
- ❌ Issues found (`bilibili-asr-archive/src/bili_asr/storage/database.py:50,96`; `bilibili-asr-archive/pyproject.toml:29-30`)
- The diff otherwise satisfies the requested schema contract: all required metadata and reserved audio/transcript tables are present; the three required views derive `work_id` and aggregates; base tables do not persist `work_id` or aggregate columns; foreign keys use `ON DELETE RESTRICT`; SQLite foreign keys are enabled; the default connection uses explicit deferred transactions; normalization helpers implement `floor(seconds * 1000)` and `page - 1`; imports are offline/stdlib-only; and the change stays within Task 1 rather than implementing repository/gateway/CLI work from Tasks 2–3.
- ⚠️ Cannot verify from diff: the implementer-reported pytest and `git diff --check` results were not rerun under the read-only review boundary. The focused tests also exercise the source checkout, not a built/installed package.

### Strengths
- `schema.sql` closely follows the primary storage specification, including the five schema-only reservation tables and the required candidate-key uniqueness constraints.
- The normalized shape is clear: user/video ownership is joined rather than duplicated, discovery/page/run aggregates are derived in `v_ingestion_run_stats`, and `work_id` is computed only in views.
- The FK and delete-restriction coverage is consistent across metadata, ingestion, audio, and transcript relationships. The deliberate absence of a discovery-to-page FK is compatible with the specified parent-before-child ordering because discoveries are inserted before the page outcome row.
- `open_database()` enables and verifies foreign-key enforcement, creates archive roots, initializes idempotently, and closes the connection on initialization failure.
- The offline test file covers fresh initialization, reopening, formula normalization, orphan rejection, delete restriction, duplicate keys, derived views, base-table denormalization checks, status/non-negative checks, and the specified transaction ordering without adding network or legacy persistence access.

### Issues
#### Critical
- None.

#### Important
- `database.py:50,96` reads `schema.sql` directly from the installed module directory, but the existing `pyproject.toml:29-30` only configures package discovery and does not declare package data (nor is a manifest/package-data rule present in the reviewed project configuration). A non-editable wheel can therefore omit `schema.sql`; `open_database()` would then raise `FileNotFoundError` before a fresh database can be initialized. Package the SQL resource explicitly (and/or load it through the package-resource API), and add an installation-artifact check.

#### Minor
- None.

### Assessment
**Task quality:** Needs fixes

## Revalidation

- **Revalidated diff/base/head:** `task-1-diff.md`; base `c98f1405bded9bfd4a322c2226de7d85e4939e6e`; head `5f22fc6e81371f79cd4f0660cc79eb7f8cae9bfa`.
- **Finding disposition:** **Fixed.** The complete original Important finding is addressed.
- **Evidence from diff:**
  - `bilibili-asr-archive/pyproject.toml:29-32` adds `[tool.setuptools.package-data]` with the literal package key `"bili_asr.storage" = ["schema.sql"]`, so the SQL resource is declared for setuptools packaging.
  - `bilibili-asr-archive/src/bili_asr/storage/database.py:53-64,110` resolves and reads the schema via `importlib.resources.files(__package__).joinpath("schema.sql")`, rather than relying on a source/install directory path.
  - `bilibili-asr-archive/tests/test_storage_schema.py:369-381` adds an offline contract check that parses `pyproject.toml`, asserts the package-data declaration, obtains `schema.sql` through `importlib.resources`, verifies it is a file, and reads a required schema marker.
  - The fix is confined to Task 1's packaging/resource bootstrap and focused schema test; no repository, gateway, CLI, media, ASR, or legacy-persistence work was added.
- **Cannot verify from diff:** The actual built-wheel installation was not performed (and must not be rerun in this read-only review); the diff nevertheless contains the required deterministic offline package-data/resource contract check. The implementer-reported focused test and `git diff --check` results were not rerun.
- **New findings:**
  - **Critical:** None.
  - **Important:** None.
  - **Minor:** None.
- **Final Task quality verdict:** **Approved**
