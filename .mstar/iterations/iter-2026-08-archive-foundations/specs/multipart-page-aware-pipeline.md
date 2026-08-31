# Spec: Multipart page-aware archive identity

## Problem

A single Bilibili bvid can expose multiple pagelist entries. Selecting `pages[0]` for all media work loses pages and can overwrite artifacts. Each page must be independently resumable and addressable.

## Contract

The canonical ledger key is `work_id = <bvid>:p<zero-based-page-index>`. A page identity contains `work_id`, `bvid`, `page_index`, positive integer `cid`, and optional page label. Filesystem names use `<bvid>.p<page-index>` and never contain the colon from `work_id`.

Metadata enumeration creates one row per page with the stable page fields. Subtitle probing, audio playurl requests, and archive writers receive the page identity or its explicit `cid`; an automatic multipart path must not collapse to page zero. Public URLs use `?p=<page-index+1>` for pages after the first.

Legacy bare-bvid rows are migrated only when page ownership is unambiguous. Ambiguous rows remain visible as `unresolved` and are excluded from automatic page processing. A migration is atomic and idempotent. Signed URLs, cookies, response bodies, and credentials are never stored in identity or artifact paths.

## Verification

Fixture-only tests must prove two pages create two rows, use two cids, produce distinct artifact paths, and resume one page without skipping or overwriting the other. Existing single-page callers remain compatible through an explicit p0 adapter.
