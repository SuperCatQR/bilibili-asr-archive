# Architecture Diagram Maintenance

`docs/architecture.json` is the editable architecture specification.
`docs/architecture.html` is the generated viewer and must be regenerated from
that JSON; do not hand-edit the HTML. `docs/architecture.md` is the short
written companion for readers who need the ownership and state rules without
opening the viewer.

The diagram is a repository-backed snapshot. Its
`meta.repository.revision` must be the forty-character commit whose source
tree the cited paths and line ranges describe. A documentation-only commit can
therefore leave the revision unchanged. When code and the diagram change in
the same effort, merge or commit the code first, then refresh the diagram from
that code commit so the evidence is verifiable.

Refresh the diagram after any change to one of these surfaces:

- CLI commands, command registration, or the workflow planner and executor;
- SQLite schema, repositories, leases, attempts, or transcript ownership;
- acquisition services, ASR/editorial handlers, archive publication, or read
  projections;
- a new durable product such as the reading site, dedup report, search index,
  or publication artifact.

From the repository root, use the Archify CLI installed with the `archify`
skill. The candidate is edited in place and the output path stays stable:

```powershell
$archify = Join-Path $env:USERPROFILE '.agents\skills\archify\bin\archify.mjs'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outDir = Join-Path '.archify' "architecture-maintenance-$stamp"
$revision = (git rev-parse HEAD).Trim()
node $archify `
  finalize architecture docs\architecture.json docs\architecture.html `
  --repo-root . --quality showcase `
  --out-dir $outDir --json
```

Before running the command, update `meta.repository.revision` in
`docs/architecture.json` to the resolved commit. If the repository is dirty,
finish or commit the code changes first; repository evidence is checked against
committed bytes, not uncommitted edits.

After a successful finalize, run the browser evidence check in the same output
directory:

```powershell
node $archify `
  visual-check docs\architecture.html `
  --out-dir $outDir `
  --summary --require-provenance --json
```

Review the light and dark desktop captures, especially the main workflow path,
relationship labels, node text, and the lower publication/query sections. The
automated checks must pass for containment, readability, theme states, viewer
chrome, and captures. Treat any route-crossing recommendation as a review item
and record the remaining limitation in the pull request rather than silently
claiming visual acceptance.

Commit the updated `docs/architecture.json`, regenerated
`docs/architecture.html`, and any necessary changes to
`docs/architecture.md`. Keep Archify receipts, screenshots, and temporary
repair candidates under the ignored `.archify/` directory; do not commit them
as product documentation. The focused application tests remain the source of
truth for behavior; the architecture diagram explains the current ownership
and relationships and does not replace those tests.
