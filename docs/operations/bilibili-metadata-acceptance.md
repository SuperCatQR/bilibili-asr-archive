# Bilibili metadata selection receipts

New Bilibili acquisition records the actual DTO field selections using the
registered `metadata-acceptance/v1` codec. This requires an explicitly created
`universal-v2` archive with `source-observations/v1`. Ordinary reads and writes
do not install a schema extension or upgrade an older database. Historical
plain JSON field caches remain readable; their raw selection is unknown.
Existing frozen v1 inputs, editions and source supplements retain their bytes,
IDs and hashes.

The gateway first captures each requested provider response privately. Only
after its normalizer successfully constructs the typed DTO does it attach a
selection receipt. A receipt contains the actual value, source observation ID,
payload/envelope hashes, exact JSON pointer, normalizer version and context.
List values, detail values, a deliberately completed aid, parts and tags have
separate pure normalizers reusable without importing the SDK. Single-part
title fallback is explicitly recorded as application context; it is not
claimed to be the provider's part title. Missing fields and failed responses
do not fabricate receipts from timestamps, matching historical values or the
newest response.

Each field that actually reaches normalized storage receives an immutable
application node. It uses operation `accepted-metadata`, endpoint
`bili-asr/metadata/acceptance`, extractor `bili-asr` and extractor version
`metadata-acceptance/v1`. The closed payload contains version, external video
ID and exactly one field selection. Parts and tags are selections of their
whole normalized sets. These application nodes and their cache pointers commit
in the same transaction as the normalized values. A failed page/write rolls
them back together while preserving the previously captured provider response
and previous successful selection. Stable aid and publication policies record
only values actually adopted by those policies. A legacy direct write that
changes a value clears that field's stale selection.

The mutable cache wraps the retained value, exact source-field receipt and
application-node binding. Its last-success time belongs to the provider read;
the application node separately records adoption time. Reused parts/tags keep
their real input acquisition time. Description supplements unwrap the retained
value without changing their evidence vocabulary, value or hash calculation.

New frozen source metadata uses v2 when at least one verified selection exists.
Its bindings contain both the selected application nodes and their original
provider observations. The other fields can still have unknown raw selection:
v2 does not assert that every platform field was captured or every normalized
field has a receipt. A later partial refresh can keep earlier description,
parts or tags independently of a newer title. Old immutable selection nodes
remain readable, so frozen history does not depend on the mutable cache.

Offline validation checks node owner, platform, full scope, ID and both hashes,
then reruns the exact registered pure normalizer to check value and pointer.
Current reads also compare the accepted value to the normalized SQL facts.
Snapshot save/check/restore checks both current cache selections and historical
frozen bindings, including their original observations and selected values.
`storage.metadata_acceptance.verify_acceptance_graph` exposes the same private
validation for provenance readers.

Application nodes are excluded from platform superset namespaces, acquisition
coverage and the provider-history count limit. They can be read privately by
their immutable IDs or `ObservationRepository.read_video` with the explicit
`include_acceptances` selector. Public metadata/catalogs include only the
registered source whitelist and binding IDs/hashes. They do not include
selection context or provider/application payloads; signed cover URLs remain
redacted by the versioned public cover rule.

Current reads accept at most 256 part IDs. Cache and normalized collections use
set queries; raw and application nodes are looked up only by selected IDs in
chunks of 256. There is no scan of all historical responses and no 10,000-row
history limit on current reads. Each cache/receipt/collection read phase has
an explicit 64 MiB budget and normalized parts/tags share a 100,000-row budget.
Exceeding a budget raises a clear error and returns no partial metadata.
Historical provider reads retain their explicit count/range/byte limits.

Regression evidence covers actual gateway ingestion, rejected new responses,
partial refresh, atomic rollback, field/pointer/normalizer/scope/hash corruption,
plain-cache and supplement compatibility, offline freeze/backup recovery,
10,001 additional historical responses and a 256-video bounded current read.
