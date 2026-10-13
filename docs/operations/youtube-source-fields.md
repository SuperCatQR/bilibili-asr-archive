# YouTube source facts and frozen version 2 metadata

New YouTube extractions now persist normalized description, tags and a public
thumbnail in the existing platform-neutral field-observation table. This is the
registered `youtube-source-fields/v1` projection; the immutable raw response is
independent `source-observations/v1` authority when explicitly installed.
Descriptions preserve Unicode, CR/LF and tabs. Tags retain order and deduplicate
names, up to the existing 256-tag boundary. Bilibili `tid`/`aid` are never populated
from YouTube categories, views or chapters; those remain in the private namespace.

Missing keys and explicit nulls preserve the last successful value. Explicit
empty prose and tag lists clear those fields. Invalid types, unsafe text, unsupported
image hosts and signed image URLs are recorded as unavailable without overwriting
known fields. An unsuccessful refresh cannot erase a previously frozen edition.
Field collection time and the last state remain distinct, so a retained old value
is not presented as successfully collected by a later incomplete response.

The frozen `source-metadata/v1` codec and its JSON Schema stay unchanged. New
YouTube snapshots containing these field observations use `source-metadata/v2`.
This version also supports exact `observationBindings`: observation ID, original
payload digest and acquisition envelope digest. A binding is emitted only when
the original receipt exists and verifies. Archives without raw storage still
retain known source fields, with an empty binding list to report unavailable raw
evidence honestly. Old records without these fields remain unknown and keep v1.
Bilibili snapshots retain v1 until the actual accepted DTO-to-field receipt is
recorded. The available private raw history is never treated as proof of which
response supplied a frozen field. No timestamp or latest-response inference is
used to manufacture bindings, and old frozen input/content hashes stay unchanged.

Version 2 public covers allow HTTPS on Bilibili image hosts for Bilibili and
`i.ytimg.com`/`i1`–`i4.ytimg.com` for YouTube. User information, capability/query
parameters, fragments, nonstandard ports, whitespace and lookalike hosts are
rejected. Private original responses retain unprojectable metadata. The current
JSON/CSV source export preserves registered v2 public covers; its other URL and
credential redaction rules remain active.

Scalar and batch metadata readers, metadata search, AI frozen input, human
editions, releases and backup save/check/restore use the same source fact codec.
Batch source reads use set queries for field projections and original receipts;
queries do not grow per part. Projected values are checked against their recorded
raw receipts, including digest, platform, video identity and observation time.
Backup validation rejects a projection whose original receipt differs.
It also checks every historical v2 binding in frozen AI inputs and human editions;
refreshing current metadata cannot hide a missing or altered earlier receipt.

New public/draft catalogs containing v2 metadata use registered catalog v4 and
draft catalog v4 schemas. They accept historical v1 sources alongside v2. Catalog
v2/v3 readers and schemas stay registered. Only receipt IDs/digests accompany the
source fact whitelist; raw payloads, private debug fields, chapters and statistics
never enter a public catalog. Existing origin profiles continue to verify v3/v4
catalogs through their frozen source-metadata hashes.

Validation covers real extractor→repository→read→freeze→publication→backup
round trips, private raw isolation, unknown historical source facts, multilingual
prose, missing/null/empty/invalid refreshes, cover ownership and signed URLs,
mixed old/new releases, projection tampering, and bounded batch query counts.
