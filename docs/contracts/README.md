# Manuscript Export Contracts

The public reader consumes `catalog.json` matching
`publication-catalog.schema.json`. The root is an object with
`schemaVersion: 1`, `manuscriptType: "publication"`, and `articles`. A legacy
array catalog, private review export, unknown field, or unsupported version is
an error. An empty `articles` array is valid.

Each article represents one effective published release for a stable video
part. `file` is relative to the export root, for example
`articles/part-7/publish.md`. The reader must validate the full catalog before
rendering, require each referenced file, verify its UTF-8 bytes against
`artifactSha256`, and require its file set to match the public manifest. It must
also check that `slug`, `file`, `sourceUrl`, and the video identity fields agree.
`publishedAt` is a Unix timestamp in seconds. Edition IDs are 32 lowercase hex
characters; AI revision, release, and SHA-256 identities are 64 characters.

Titles, summary, tags, attribution, and editor notes are frozen reader content
covered by `contentSha256`. The public artifact contains that same content,
including its fixed title and source. Current video metadata, current draft
editions, AI review state, model configuration, review actors, and audit events
must not be used to amend public entries. There is no public `review.md` view.

`publication-export-manifest.json` follows the public manifest schema. Its
`files` list includes the catalog and all public Markdown files, sorted by path.
Each byte digest is independent of the content object digest. `snapshotId` is
SHA-256 of the list encoded as UTF-8 JSON with sorted keys, separators `,` and
`:`, and no whitespace. The manifest does not list itself. Unknown files and
directories are refused rather than removed.

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
