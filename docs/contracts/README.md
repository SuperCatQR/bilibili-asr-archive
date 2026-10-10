# Manuscript Export Contracts

## Authoritative definitions and generated mirrors

The executable JSON Schemas live in `src/bili_asr/contracts/schemas/` and ship
inside the wheel. This directory is their byte-identical publication mirror.
The [contract registry](registry.json) records 34 identities, their owners,
definition paths, consumers, capabilities and dependencies; 15 entries have
JSON Schemas. See [governance and compatibility](../contract-governance.md).

```powershell
python -m bili_asr.contracts --write-docs docs/contracts
python -m bili_asr.contracts --check-docs docs/contracts
```

Runtime validation resolves all cross-schema references from packaged resources
offline. Structural checks precede domain identity, hash and file-set checks.
Edit the packaged source and regenerate this mirror; CI rejects drift.

The seven-file private manifest remains [editorial manifest v1](editorial-export-manifest.schema.json).
Imported preserved-body packages use the distinct [ten-file layout](editorial-import-export-manifest.schema.json).
Both retain the existing wire `schemaVersion: 1`.
Review envelopes also retain v1: [AI template v1](editorial-review.schema.json) and
[AI template v2](editorial-review-universal.schema.json) have separate structural definitions.



The explicit `universal-origin-v1` profile uses catalog v3 with universal
articles only, [origins v1](publication-origins-v1.schema.json) and
[manifest v2](publication-origin-manifest-v2.schema.json). It permits verified
legacy-body imports while retaining their real v1 input/revision/template
identities. See [installation, policy, review and retry semantics](../preserved-body-import.md).
Existing manifest v1 exports do not accept imported editions. A consumer must
implement the new profile before serving these snapshots; the sections below
describe the existing interfaces without changing their version-1 algorithm.

Optional editor-confirmed `series.json` is described by
[the public schema](publication-series.schema.json) and
[private editorial schema](publication-series-editorial.schema.json).
See [semantic validation, maintenance and export](../publication-series.md).
Its exact byte hash belongs to the existing version-1 manifest; absent series
preserves previous snapshots, and manuscript/catalog versions remain unchanged.

The historical version-2 schemas below remain available unchanged. An export
containing content-version 2 uses `publication-catalog-v3.schema.json` or
`publication-draft-catalog-v3.schema.json`. Version 3 can mix exact historical
Bilibili article shapes with universal articles. Universal articles explicitly
declare `contentVersion: 2`, platform, external video ID, part index and the
complete immutable `source-metadata-v1` snapshot. They never manufacture BVIDs.
Their release template is `publish-v2`; draft catalogs still have no template or
release fields. The manifest envelope remains version 1.

The JSON Schemas describe field shapes. A consumer must also validate provider
IDs, canonical URLs, metadata/source identity equality, derived publication
time, slug and file identity, file hashes and exact manifest membership. Source
time can be null when unknown; collection and release times cannot replace it.
Current database metadata cannot alter either historical or universal editions.
See [implementation boundaries](../issues-implementation.md) for version
registration and migration. The independent reading-site delivery must adopt
catalog version 3 before serving new universal entries.

The remaining paragraphs describe the historical version-2 reader contract.

The public reader consumes `catalog.json` matching
`publication-catalog.schema.json`. The root is an object with
`schemaVersion: 2`, `manuscriptType: "publication"`, and `articles`. A legacy
array catalog, private review export, unknown field, or unsupported version is
an error. An empty `articles` array is valid.

Each article represents one effective published release for a stable video
part. `file` is relative to the export root, for example
`articles/part-7/publish.md`. The reader must validate the full catalog before
rendering, require each referenced file, verify its UTF-8 bytes against
`artifactSha256`, require the paired `reviewFile` bytes to match
`reviewArtifactSha256`, and require both file sets to match the public manifest. It must
also check that `slug`, `file`, `sourceUrl`, and the video identity fields agree.
`publishedAt` is a Unix timestamp in seconds. Edition IDs are 32 lowercase hex
characters; AI revision, release, and SHA-256 identities are 64 characters.

Titles, summary, tags, attribution, and editor notes are frozen reader content
covered by `contentSha256`. The public artifact contains that same content,
including its fixed title and source. Current video metadata, current draft
editions, AI review state, review actors, and audit events must not be used to
amend public entries. Each article also exports the original `review.md` of its
exact `aiRevisionId`, at `articles/part-<videoPartId>/review.md`. This reference
contains original/compiled text, source identifiers, timestamps, replay links,
issues and non-sensitive model parameters. It is not an approval record and
does not claim to review later manual edits. The bytes are copied unchanged
after verifying the complete immutable AI pair. Model-call requests/responses,
credentials, `review.json`, review actors and audit events are not exported.

`publication-export-manifest.json` follows the public manifest schema. Its
`files` list includes the catalog and all public Markdown files, sorted by path.
Each byte digest is independent of the content object digest. `snapshotId` is
SHA-256 of the list encoded as UTF-8 JSON with sorted keys, separators `,` and
`:`, and no whitespace. The manifest does not list itself. Unknown files and
directories are refused rather than removed.

The generic release and draft manifest envelopes remain at `schemaVersion: 1`;
their catalog envelopes require version 2. Version 1 catalogs, including empty
ones, are refused without fallback or automatic migration. Export to new,
separate directories when upgrading, validate the resulting version 2
snapshots, then replace the deployed snapshots as complete directories. Keep
previous snapshots outside the serving roots until the upgrade is verified.

Explicit reader draft previews use a separate output directory and
`publication-draft-catalog.schema.json`. The catalog envelope has
`schemaVersion: 2`, `manuscriptType: "publication-draft"`, and `articles`.
`publication export-drafts --out DIR` selects each current draft head only if
that edition has never had any release, including a superseded or withdrawn
release. It includes all five review states, including `rejected`; review
approval alone does not make the preview a release. Only the current edition
for each part appears. Publishing it removes it from the next draft snapshot.
A published edition A and a new, never released draft B may appear in the two
separate catalogs; the same edition must not appear in both.

Each preview has `slug: "edition-<32 lowercase hex editionId>"` and
`file: "drafts/edition-<editionId>/preview.md"`, relative to the draft export
root. Its Markdown contains the complete frozen reader content, paired with
`reviewFile: "drafts/edition-<editionId>/review.md"` and
`reviewArtifactSha256` for the exact AI revision's original reference bytes. Preview
identity includes `editionId`, `aiRevisionId`, the video/source fields,
`contentSha256`, `artifactSha256`, `reviewStatus`, and `createdAt` (edition
creation Unix seconds). It has no `releaseId`, `publishedAt`, or
`templateVersion`. The public reference contains its existing non-sensitive
model parameters and source comparison. The catalog must not contain private
review notes, actors, events, raw responses, or paths to private review files.
The exporter verifies the immutable AI baseline and complete edition identity
before rendering, while exporting reader content, its review status, and the
paired original reference.

`publication-draft-export-manifest.json` follows
`publication-draft-export-manifest.schema.json` and has
`manuscriptType: "publication-draft-export"`. The hashing and exact file-set
rules match the release manifest. Draft, release, and private review outputs
have distinct catalog/manifest contracts and cannot replace one another's
managed directories. An empty draft catalog is valid. Consumers must validate
both catalogs independently, retain the draft label and review state, and
never substitute a preview for an unavailable released article. The release
catalog continues to accept only effective approved releases.

Private review exports use a separate output and contain exactly `ai-draft.md`,
the fixed baseline `review.md`, complete rendered `edition.md`, reader-content
object `edition.json`, review metadata `review.json`, and two unified patches in
`differences/`. Patches compare the entire content object with the AI baseline
and the selected edition's parent. For the first edition, both comparisons use
the baseline. This includes changes to titles, summary, tags, and editor notes
as well as the body. The private manifest follows
`editorial-export-manifest.schema.json`; review metadata follows
`editorial-review.schema.json`. The package does not copy model requests or full
responses.

The website validates `content/` and `draft-content/` independently and rejects
the same edition appearing in both. Published A and unpublished B of the same
video part may coexist. Directory search and article routes stay separate.

An exporter locks the output, builds and validates a complete staged directory,
and switches directories using an atomically installed durable recovery journal. A directory may be
briefly unavailable during the switch; a successful export always contains one
complete snapshot. Ordinary switch failures restore the previous output.
Interruption recovery runs on the next export under the same OS lock. Unknown
or ambiguous recovery state is preserved and reported.

The output directory is the serving boundary. Its parent must stay private:
hidden lock, staging, backup, and recovery journal files are siblings of the
output and must never enter static deployment or be served through the parent
directory. A cleanup interruption may leave a private backup orphan after the
new snapshot is committed. Deploy only the exact validated output. A local
withdrawal export removes the article from that output; deployments and caches
need their own corresponding refresh.

The `examples/` directory contains one valid public catalog and deliberately
invalid legacy and private catalogs for consumer contract tests. They are
illustrative metadata fixtures; their Markdown byte hashes are not a deployable
export.
