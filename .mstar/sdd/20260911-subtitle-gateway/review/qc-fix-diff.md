# Plan-QC Fix Wave Diff — 20260911-subtitle-gateway

Base: `6002f99`
Head: `9322239`
Scope: consolidated W1 + S1/S4/S5/S8/S9

```diff
diff --git a/bilibili-asr-archive/README.md b/bilibili-asr-archive/README.md
index d044657..0f41c13 100644
--- a/bilibili-asr-archive/README.md
+++ b/bilibili-asr-archive/README.md
@@ -563,6 +563,25 @@ Exit 2 variants:
 
 #### Opt-in bounded live smoke
 
+Three tests share the one switch (`BILI_LIVE_SMOKE=1`); every default pytest
+run skips all three and makes no network call:
+
+- `tests/test_live_metadata_smoke.py` — the real CLI against the real upstream:
+  exactly one public metadata page for UID 23191782, into a temporary archive
+  root, calling no subtitle/playback/audio/ASR code (detailed below);
+- `tests/test_live_subtitle_smoke.py` — the real subtitle adapter against the
+  real upstream: one part's track inventory and, when a track is visible, that
+  track's caption document. It resolves the part from the operator's archive
+  database when one is readable and falls back to a fixed public sample
+  otherwise (`part_source=archive-db|fixed-sample`), and it prints bounded
+  facts only — counts, language codes, `ai|cc`, segment count, milliseconds,
+  and credential presence — never a URL, body, label, or credential. Run it
+  from the package directory with the pinned distribution installed:
+  `BILI_LIVE_SMOKE=1 .venv/bin/python -m pytest tests/test_live_subtitle_smoke.py -s -v`;
+- `tests/test_bilibili_api_gateway.py::test_live_smoke_single_public_page_for_archive_owner`
+  — the adapter-level ancestor of the CLI smoke: one real metadata page for UID
+  23191782 ingested into a temporary database through the real gateway.
+
 `tests/test_live_metadata_smoke.py` drives the real CLI against the real
 upstream: exactly one public metadata page for UID 23191782
 (`--start-page 1 --limit-pages 1`) into a temporary archive root, calling no
diff --git a/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py b/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
index 27ebef8..d226352 100644
--- a/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
+++ b/bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py
@@ -67,6 +67,15 @@ _SUBTITLE_NOT_FOUND_API_CODES = _NOT_FOUND_API_CODES | {-101}
 # Same shape check the package itself applies in Video.set_bvid.
 _BVID_PATTERN = re.compile(r"^BV[a-zA-Z0-9]{10}$")
 
+# The one scheme a signed subtitle-document URL is put on the wire under, and
+# the plain-``http`` form upstream may answer with instead.  Upstream answers
+# the URL sometimes protocol-relative and sometimes absolute (spec section
+# 1.3); the document's own request carries no credential by design, but the
+# signed URL is itself the capability token for the document, so it is
+# normalized to ``https:`` rather than forwarded as delivered.
+_HTTPS_SCHEME = "https://"
+_PLAIN_HTTP_SCHEME = "http://"
+
 # The package's own endpoint description for the user-video page call
 # (``bilibili_api.user.API["info"]["video"]``).  ``url``/``method``/
 # ``verify``/``wbi`` are read from it so this adapter cannot drift from the
@@ -375,8 +384,15 @@ def _read_subtitle_document_url(entry: Mapping) -> str:
     """Read one entry's signed document URL, normalized to ``https:``.
 
     Upstream answers the URL sometimes absolutely and sometimes
-    protocol-relative; the normalized absolute form is what the package
-    transport is handed, and it stays process-local.
+    protocol-relative, and an absolute answer is not guaranteed to be TLS, so
+    the scheme is decided here rather than taken as delivered: a
+    protocol-relative value and a plain ``http:`` value are both rewritten to
+    ``https:`` — the signed URL *is* the document's capability token, so it
+    never rides a cleartext request — while a value that is neither of those
+    nor already ``https:`` cannot be read as this document's URL at all and is
+    a bounded shape error.  Every value that leaves this function is therefore
+    an absolute ``https:`` URL; it is handed to the package transport for the
+    duration of one call and stays process-local.
     """
 
     url = entry.get("subtitle_url")
@@ -384,8 +400,12 @@ def _read_subtitle_document_url(entry: Mapping) -> str:
         raise GatewayShapeError(detail="subtitle track has no document URL")
     normalized = url.strip()
     if normalized.startswith("//"):
-        normalized = f"https:{normalized}"
-    return normalized
+        return f"https:{normalized}"
+    if normalized.startswith(_PLAIN_HTTP_SCHEME):
+        return f"{_HTTPS_SCHEME}{normalized[len(_PLAIN_HTTP_SCHEME):]}"
+    if normalized.startswith(_HTTPS_SCHEME):
+        return normalized
+    raise GatewayShapeError(detail="subtitle track has an unreadable document URL")
 
 
 def _normalize_subtitle_document(document: object) -> tuple[SubtitleSegment, ...]:
diff --git a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
index d7174cd..4ec0b04 100644
--- a/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
+++ b/bilibili-asr-archive/tests/test_bilibili_api_gateway.py
@@ -1709,9 +1709,17 @@ def test_gateway_imports_stay_on_metadata_surface():
     ``Video``), and the five exception names.  The page call reads
     ``user.API["info"]["video"]`` and the subtitle call reads the player
     endpoint description from the same surface, so ``utils.network.Api`` stays
-    the one request path.  ``User`` is deliberately not among them: the page
-    call goes through the ``user`` module's endpoint description and the
-    package ``Api``, never a ``user.User`` delegate.
+    the one request path.  ``User`` is not an allow-listed name of its own,
+    because the ``user`` module is bound whole: the adapter reaches the class
+    through it (``user.User(uid=mid, credential=self._credential)``, whose
+    ``get_access_id()`` serves the optional ``w_webid`` token route — the
+    attribute the next test's positive control requires the scanned source to
+    carry).  That
+    module-wide binding — every other endpoint description reachable through
+    ``user.get_api`` included — is residual R1, deferred to the next plan that
+    touches this module.  The page call itself still goes through the ``user``
+    module's endpoint description and the package ``Api``, never through that
+    delegate.
     """
 
     gateway_path = (
@@ -2675,6 +2683,40 @@ def test_fetch_subtitle_segments_normalizes_the_document_and_drops_degenerate_ro
     assert bilibili_api_seam.calls == [_listing_call(), "subtitle.body"]
 
 
+def test_caption_seconds_are_floored_rather_than_rounded_to_milliseconds(
+    bilibili_api_seam,
+):
+    """The suite's one conversion row that discriminates ``floor`` from ``round``.
+
+    Spec section 3 locks ``floor(seconds * 1000)`` against the legacy
+    ``subtitles.json_to_srt`` conversion, which rounds.  Every other
+    conversion literal in this module — the drop matrix included — multiplies
+    out exactly (``0.0``/``1.0``/``1.5``/``2.0``/``2.5``/``2.75``/``3.0``), so
+    those rows pass under either conversion and a floor→round regression would
+    leave the whole suite green.  This row is the discriminating one:
+    ``3.14159 * 1000`` lands strictly between two integers, so ``floor``
+    yields ``3141`` where ``round`` would yield ``3142``, and its end second
+    discriminates the same way (``3241`` vs ``3242``).  Both endpoints are
+    asserted, so the row discriminates at the start and at the end.
+    """
+
+    gateway = _load_subtitle_gateway(bilibili_api_seam, make_subtitle_track())
+    bilibili_api_seam.subtitle_bodies = {
+        SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document(
+            _subtitle_row(3.14159, 3.24159, "向下取整"),
+        )
+    }
+
+    segments = asyncio.run(
+        gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID)
+    )
+
+    assert segments == (
+        SubtitleSegment(start_ms=3141, end_ms=3241, text="向下取整"),
+    )
+    assert bilibili_api_seam.calls == [_listing_call(), "subtitle.body"]
+
+
 def test_subtitle_document_request_carries_the_locked_transport_shape(
     bilibili_api_seam,
 ):
@@ -2731,6 +2773,71 @@ def test_fetch_subtitle_segments_normalizes_a_protocol_relative_document_url(
     assert bilibili_api_seam.calls == [_listing_call(), "subtitle.body"]
 
 
+def test_fetch_subtitle_segments_upgrades_a_plain_http_document_url_to_https(
+    bilibili_api_seam,
+):
+    """An absolute ``http:`` signed URL is fetched in its ``https:`` form.
+
+    Upstream may answer the URL absolutely without TLS, and the signed URL is
+    itself the document's capability token, so the adapter normalizes the
+    scheme instead of forwarding the value as delivered: the request carries
+    an explicitly empty credential, which is no reason to put the token in
+    clear.  The seam scripts only the ``https:`` form, so an un-upgraded URL
+    would hit an unscripted location and fail loudly there.  (The ``http:``
+    twin still carries the protocol-relative marker as a substring, so the
+    no-leak scanner covers this form too.)
+    """
+
+    plain_http_url = f"http://{SIGNED_SUBTITLE_URL_MARKER.removeprefix('https://')}"
+    gateway = _load_subtitle_gateway(
+        bilibili_api_seam, make_subtitle_track(subtitle_url=plain_http_url)
+    )
+    bilibili_api_seam.subtitle_bodies = {
+        SIGNED_SUBTITLE_URL_MARKER: make_subtitle_document(make_subtitle_entry())
+    }
+
+    segments = asyncio.run(
+        gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID)
+    )
+
+    assert [segment.text for segment in segments] == ["未明子"]
+    assert bilibili_api_seam.api_requests[-1].url == SIGNED_SUBTITLE_URL_MARKER
+    assert bilibili_api_seam.calls == [_listing_call(), "subtitle.body"]
+
+
+@pytest.mark.parametrize(
+    "unreadable_url",
+    [
+        "ftp://aisubtitle.hdslb.com/subtitle.json?sig=1",
+        "aisubtitle.hdslb.com/subtitle.json?sig=1",
+    ],
+)
+def test_fetch_subtitle_segments_rejects_a_document_url_it_cannot_normalize(
+    bilibili_api_seam, unreadable_url
+):
+    """A present ``subtitle_url`` outside the normalizable forms is a shape error.
+
+    Only a protocol-relative, ``http:``, or ``https:`` value can be read as
+    this document's URL, so every value the adapter puts on the wire is TLS;
+    anything else is refused at the boundary rather than handed to a transport
+    that might resolve another scheme.  The refusal happens before the request
+    is built, which the exact call list proves (no document fetch), and the
+    message carries the static bounded detail instead of the value.
+    """
+
+    gateway = _load_subtitle_gateway(
+        bilibili_api_seam, make_subtitle_track(subtitle_url=unreadable_url)
+    )
+
+    with pytest.raises(GatewayShapeError) as caught:
+        asyncio.run(gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID))
+
+    assert caught.value.code == "shape_error"
+    assert caught.value.detail == "subtitle track has an unreadable document URL"
+    assert unreadable_url not in str(caught.value)
+    assert bilibili_api_seam.calls == [_listing_call()]
+
+
 def test_fetch_subtitle_segments_resolves_the_requested_track_by_identity(
     bilibili_api_seam,
 ):
@@ -2923,6 +3030,34 @@ def test_fetch_subtitle_segments_rejects_an_unreadable_document(
     assert bilibili_api_seam.calls == [_listing_call(), "subtitle.body"]
 
 
+def test_a_cancelled_document_fetch_propagates_instead_of_being_mapped(
+    bilibili_api_seam,
+):
+    """``CancelledError`` is not an unexpected upstream failure.
+
+    The mapper's broad ``except Exception`` is what turns every unmapped
+    upstream failure into the bounded ``transport_error``, and that is the
+    contract the sibling cases here pin.  Cancellation is not that kind of
+    failure: ``asyncio.CancelledError`` derives from ``BaseException``, so it
+    must reach the caller and stop the task instead of being rewritten into a
+    bounded code — a rewrite would additionally arm the adapter's single
+    re-list, i.e. a cancelled call would spend two more network requests.  The
+    seam raises the scripted ``BaseException`` as-is, and the exact call list
+    proves the document fetch was actually issued (so this cannot pass by
+    never reaching the mapper) and that no re-list followed it.
+    """
+
+    gateway = _load_subtitle_gateway(bilibili_api_seam, make_subtitle_track())
+    bilibili_api_seam.subtitle_bodies = {
+        SIGNED_SUBTITLE_URL_MARKER: asyncio.CancelledError()
+    }
+
+    with pytest.raises(asyncio.CancelledError):
+        asyncio.run(gateway.fetch_subtitle_segments(_seam_track(), BVID, PART_CID))
+
+    assert bilibili_api_seam.calls == [_listing_call(), "subtitle.body"]
+
+
 @pytest.mark.parametrize(
     ("body_outcome", "expected", "attempts"),
     [
diff --git a/bilibili-asr-archive/tests/test_live_subtitle_smoke.py b/bilibili-asr-archive/tests/test_live_subtitle_smoke.py
index 5274bb2..02f035c 100644
--- a/bilibili-asr-archive/tests/test_live_subtitle_smoke.py
+++ b/bilibili-asr-archive/tests/test_live_subtitle_smoke.py
@@ -25,11 +25,27 @@ Where the probed part comes from:
   (:data:`SAMPLE_BVID` / :data:`SAMPLE_CID`): one part of the archive owner's
   own public collection, discovered once through the delivered metadata
   gateway while this probe was authored.  The fallback deliberately costs no
-  metadata call at run time, so the only live surfaces the probe touches are
-  the player endpoint and the signed document it lists — the routes under test.
-  The evidence line records which source answered (``part_source=archive-db``
-  or ``part_source=fixed-sample``) together with the probed ``bvid``/``cid``,
-  so a sample that upstream has since removed is visible rather than silent.
+  metadata call at run time.  The evidence line records which source answered
+  (``part_source=archive-db`` or ``part_source=fixed-sample``) together with
+  the probed ``bvid``/``cid``, so a sample that upstream has since removed is
+  visible rather than silent.
+
+The probe's live surface is wider than the two calls it drives itself — one
+listing and one document fetch — because the pinned package and the delivered
+adapter each add to that bound:
+
+- the listing is WBI-signed, and the pin's own request loop re-signs and
+  retries it on a ``-403`` answer, up to the pin's ``wbi_retry_times`` budget
+  (3 attempts by default);
+- the document fetch is issued with ``wbi=False``, so the pin neither re-signs
+  nor retries it: one attempt per fetch call;
+- the first adapter call in a process bootstraps the pin's process-global
+  ``buvid`` fingerprint whenever the credential carries none — which the
+  document fetch's explicitly empty ``Credential()`` always does — costing up
+  to two further requests (the SPI fingerprint endpoint and its activation
+  POST), once per process;
+- the delivered adapter adds at most one re-list + fetch pair per
+  ``fetch_subtitle_segments`` call, and only on the expiry/transport class.
 
 Default pytest runs skip the probe; it executes only when the operator sets
 ``BILI_LIVE_SMOKE=1``.  An opted-in probe fails loudly when the pinned
```
