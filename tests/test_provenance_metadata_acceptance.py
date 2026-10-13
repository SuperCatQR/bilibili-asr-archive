"""Portable source choices come from real DTO receipts, including cold reads."""
from __future__ import annotations

import hashlib
import json
from contextlib import closing
from copy import deepcopy

import pytest

from bili_asr.canonical_json import canonical, digest
from bili_asr.metadata_acceptance import CONTRACT
from bili_asr.provenance_contract import read_graph, verify_graph, write_graph
from bili_asr.provenance_report import report_graph
from bili_asr.services.archive_migration import initialize_archive
from bili_asr.services.archive_snapshot import restore_snapshot, save_snapshot
from bili_asr.services.metadata_ingest import MetadataIngestor
from bili_asr.services.metadata_refresh import MetadataRefreshService
from bili_asr.services.provenance import TraceReader, public_summary, trace
from bili_asr.storage.database import connect_database
from bili_asr.storage.metadata import MetadataRepository
from bili_asr.storage.source_observations import ObservationRepository
from tests.fixtures.fake_bilibili_gateway import (
    MID,
    make_detail_response,
    make_part_item,
    make_tag_item,
    make_videos_response,
    make_vlist_item,
)
from tests.fixtures.fake_bilibili_gateway import (
    bilibili_api_seam as bilibili_api_seam,  # noqa: PLC0414 - fixture registration
)
from tests.test_import_order import _run_fresh
from tests.test_provenance_trace import _rehash, manuscript

pytestmark = pytest.mark.usefixtures("enable_content_publication_for_tests")
BVID = "BV1DETAILSD0"
DESCRIPTION = "已采用的原文\nDeuxième\t🙂"


async def _no_sleep(_):
    return None


def seed(root, seam):
    from bili_asr.sources.bilibili_api_gateway import BilibiliApiGateway

    initialize_archive(root, with_source_observations=True)
    seam.videos_response = make_videos_response(make_vlist_item(bvid=BVID, description=DESCRIPTION,
        private_unknown={"nested": [True, None, "原样保留"]}), count=1)
    seam.parts_response = [make_part_item(part="第一\n部分", duration=2)]
    seam.tags_response = [make_tag_item(tag_name="主题")]
    gateway = BilibiliApiGateway(_sleeper=_no_sleep)
    with closing(connect_database(root / "archive.db")) as connection:
        result = MetadataIngestor(gateway, MetadataRepository(connection)).collect_user_pages(MID, start_page=1, page_limit=1)
        assert result.outcome == "limited"
        part = connection.execute("SELECT video_part_id FROM video_parts WHERE bvid=?", (BVID,)).fetchone()[0]
    return gateway, part


def source_graph(connection, part):
    """Isolate domain validation from unrelated AI input/container digests."""
    reader = TraceReader(connection, ())
    metadata = MetadataRepository(connection).read_source_metadata(part)
    source = reader.source({"source_metadata": metadata.to_dict()})
    content = "Private source closure\n"
    sha256 = hashlib.sha256(content.encode()).hexdigest()
    artifact = reader.graph.add("artifact", "documents/fixture.md", {"name": "fixture.md",
        "relative_path": "documents/fixture.md", "sha256": sha256, "text": content,
        "availability": "embedded_verified"}, (source,))
    return reader.graph.seal({"kind": "artifact", "value": sha256}, [artifact])


def _acceptance(graph, field="desc"):
    return next(node for node in graph["nodes"] if node["kind"] == "metadata-acceptance"
                and json.loads(node["record"]["payload_json"])["fields"][0]["field"] == field)


def _replace_acceptance_payload(graph, node, document):
    record = node["record"]
    payload = json.dumps(document, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    envelope = json.loads(record["envelope_json"])
    envelope["payloadSha256"] = hashlib.sha256(payload.encode()).hexdigest()
    record.update(payload_json=payload, payload_sha256=envelope["payloadSha256"],
                  envelope_json=canonical(envelope), envelope_sha256=digest(envelope))
    source = next(item for item in graph["nodes"] if item["kind"] == "source")
    metadata = source["record"]["metadata"]["source_metadata"]
    binding = next(item for item in metadata["observationBindings"] if item["observationId"] == node["identity"])
    binding.update(payloadSha256=record["payload_sha256"], envelopeSha256=record["envelope_sha256"])
    source["identity"] = digest(source["record"]["metadata"])


def test_actual_gateway_choices_reach_final_artifact_with_explicit_application_owner(tmp_path, bilibili_api_seam):
    seeded = {}
    def seed_part(root):
        seeded["gateway"], part = seed(root, bilibili_api_seam)
        return part
    connection, root, _revision, _edition, release, _producers = manuscript(tmp_path, seed_part=seed_part)
    with closing(connection):
        graph = trace(connection, release_id=release["release_id"], artifact_roots=(root,))
        facts = report_graph(graph)["revisions"][0]
        assert facts["metadata_selection"] == {"state": "recorded_fields",
            "fields": ["aid", "desc", "parts", "pic", "pubdate", "tags", "tid", "title"]}
        assert len(facts["raw_observation_digests"]) == 3
        assert all(item["owner"] == "provider" for item in facts["raw_observation_digests"])
        assert len(facts["application_acceptance_digests"]) == 8
        assert all(item["owner"] == "application" and item["codec"] == CONTRACT
                   for item in facts["application_acceptance_digests"])
        frozen = facts["source_metadata"]["metadata"]["source_metadata"]
        assert frozen["description"] == DESCRIPTION and frozen["partTitle"] == "第一 部分"
        nodes = {item["sha256"]: item for item in graph["nodes"]}
        for acceptance in (item for item in nodes.values() if item["kind"] == "metadata-acceptance"):
            field = json.loads(acceptance["record"]["payload_json"])["fields"][0]
            assert len(acceptance["dependencies"]) == 1
            original = nodes[acceptance["dependencies"][0]]
            assert original["kind"] == "observation" and original["identity"] == field["source"]["observationId"]
        description = _acceptance(graph)
        document = json.loads(description["record"]["payload_json"])
        assert document["fields"][0]["jsonPointer"] == "/list/vlist/0/description"
        original = nodes[description["dependencies"][0]]
        assert json.loads(original["record"]["payload_json"])["list"]["vlist"][0] == bilibili_api_seam.videos_response["list"]["vlist"][0]
        public = public_summary(connection, release["release_id"], (root,))
        assert "application_acceptance" not in str(public) and DESCRIPTION not in str(public)
        private = tmp_path / "private.json"
        write_graph(private, graph)
    assert report_graph(read_graph(private))["revisions"][0] == facts


def test_rejected_or_later_accepted_raw_never_replaces_frozen_adoption(tmp_path, bilibili_api_seam):
    seeded = {}
    def seed_part(root):
        seeded["gateway"], part = seed(root, bilibili_api_seam)
        return part
    connection, root, _revision, _edition, release, _producers = manuscript(tmp_path, seed_part=seed_part)
    with closing(connection):
        before = trace(connection, release_id=release["release_id"], artifact_roots=(root,))
        frozen = connection.execute("SELECT prepared_json FROM editorial_inputs").fetchone()[0]
        bilibili_api_seam.info_response = make_detail_response(bvid=BVID, title="Rejected later", desc="Rejected", tid=-1)
        refresh = MetadataRefreshService(seeded["gateway"], MetadataRepository(connection))
        assert all(item.error_code == "shape_error" for item in refresh.refresh((BVID,), operations=("summary", "details")))
        rejected = next(item for item in ObservationRepository(connection).read_video("bilibili", BVID)
                        if item.envelope["operation"] == "details")
        assert rejected.observation_id not in str(before)
        assert trace(connection, release_id=release["release_id"], artifact_roots=(root,)) == before
        bilibili_api_seam.info_response = make_detail_response(bvid=BVID, title="Accepted later", desc="New current text")
        assert refresh.refresh((BVID,), operations=("summary",))[0].state == "present"
        assert connection.execute("SELECT title FROM videos WHERE bvid=?", (BVID,)).fetchone()[0] == "Accepted later"
        assert connection.execute("SELECT prepared_json FROM editorial_inputs").fetchone()[0] == frozen
        assert trace(connection, release_id=release["release_id"], artifact_roots=(root,)) == before


@pytest.mark.parametrize("fault", ["pointer", "value", "normalizer", "owner", "source-binding", "context-scope",
                                 "dependency", "extra-dependency", "node-owner"])
def test_fully_resealed_application_receipt_still_requires_exact_original_relationship(tmp_path, bilibili_api_seam, fault):
    root = tmp_path / "archive"
    _, part = seed(root, bilibili_api_seam)
    with closing(connect_database(root / "archive.db")) as connection:
        graph = source_graph(connection, part)
    altered = deepcopy(graph)
    acceptance = _acceptance(altered)
    document = json.loads(acceptance["record"]["payload_json"])
    field = document["fields"][0]
    if fault == "pointer":
        field["jsonPointer"] = "/list/vlist/0/title"
    elif fault == "value":
        field["value"] = "Counterfeit adopted value"
        source = next(item for item in altered["nodes"] if item["kind"] == "source")
        source["record"]["metadata"]["source_metadata"]["description"] = field["value"]
    elif fault == "normalizer":
        field["normalizer"] = "bilibili-details/v1"
    elif fault == "owner":
        field["context"]["ownerMid"] = MID + 1
    elif fault == "source-binding":
        field["source"]["payloadSha256"] = "a" * 64
    elif fault == "context-scope":
        field["context"]["bvid"] = "BV9876543210"
    elif fault == "dependency":
        acceptance["dependencies"] = []
    elif fault == "extra-dependency":
        other = next(item for item in altered["nodes"] if item["kind"] == "observation"
                     and item["sha256"] not in acceptance["dependencies"])
        acceptance["dependencies"].append(other["sha256"])
    else:
        acceptance["record"]["owner"] = "provider"
    _replace_acceptance_payload(altered, acceptance, document)
    with pytest.raises(ValueError, match="provenance|frozen metadata|binding"):
        verify_graph(_rehash(altered))


@pytest.mark.parametrize("field", ["description", "partTitle", "durationMs", "tags", "coverUrl", "creatorId"])
def test_offline_receipt_must_project_to_the_frozen_metadata(tmp_path, bilibili_api_seam, field):
    root = tmp_path / "archive"
    _, part = seed(root, bilibili_api_seam)
    with closing(connect_database(root / "archive.db")) as connection:
        graph = source_graph(connection, part)
    source = next(item for item in graph["nodes"] if item["kind"] == "source")
    metadata = source["record"]["metadata"]["source_metadata"]
    metadata[field] = {"durationMs": 1000, "tags": ["Another tag"], "creatorId": str(MID + 1),
                       "coverUrl": "https://i1.hdslb.com/bfs/archive/other.jpg"}.get(field, "Another frozen value")
    source["identity"] = digest(source["record"]["metadata"])
    with pytest.raises(ValueError, match="frozen"):
        verify_graph(_rehash(graph))


def test_frozen_source_read_stops_at_its_byte_budget_before_collecting_all_receipts(tmp_path, bilibili_api_seam, monkeypatch):
    root = tmp_path / "archive"
    _, part = seed(root, bilibili_api_seam)
    calls = []
    original = ObservationRepository.get
    def observed(repository, identity):
        calls.append(identity)
        return original(repository, identity)
    monkeypatch.setattr(ObservationRepository, "get", observed)
    monkeypatch.setattr("bili_asr.services.provenance.MAX_BYTES", 1)
    with closing(connect_database(root / "archive.db")) as connection:
        metadata = MetadataRepository(connection).read_source_metadata(part)
        calls.clear()
        with pytest.raises(ValueError, match="observation read exceeds byte limit"):
            TraceReader(connection, ()).source({"source_metadata": metadata.to_dict()})
        assert len(calls) == 1


def test_cold_copy_and_private_graph_keep_exact_originals_and_reject_missing_raw(tmp_path, bilibili_api_seam):
    root = tmp_path / "archive"
    _, part = seed(root, bilibili_api_seam)
    with closing(connect_database(root / "archive.db")) as connection:
        graph = source_graph(connection, part)
    private = tmp_path / "private.json"
    write_graph(private, graph)
    package = tmp_path / "snapshot.zip"
    save_snapshot(root, package)
    restored = tmp_path / "restored"
    restore_snapshot(package, restored)
    root.rename(tmp_path / "original-offline")
    assert read_graph(private) == graph
    _run_fresh(f"""
import sys
from pathlib import Path

class OfflineBoundary:
    def find_spec(self, fullname, *args, **kwargs):
        forbidden = ('bilibili_api', 'yt_dlp', 'requests', 'torch', 'transformers',
                     'bili_asr.storage', 'bili_asr.services', 'bili_asr.deepseek')
        if any(fullname == name or fullname.startswith(name + '.') for name in forbidden):
            raise AssertionError('offline graph imported runtime dependency: ' + fullname)

sys.meta_path.insert(0, OfflineBoundary())
from bili_asr.provenance_contract import read_graph
assert read_graph(Path({str(private)!r}))['graph_sha256'] == {graph['graph_sha256']!r}
""")
    with closing(connect_database(restored / "archive.db")) as connection:
        assert source_graph(connection, part) == graph
        identity = next(item["identity"] for item in graph["nodes"] if item["kind"] == "observation")
        with connection:
            guards = tuple(connection.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='platform_observations'"))
            for name, _ in guards:
                connection.execute('DROP TRIGGER "' + name + '"')
            connection.execute("DELETE FROM platform_observations WHERE observation_id=?", (identity,))
            for _, sql in guards:
                connection.execute(sql)
        with pytest.raises(ValueError, match="receipt is missing|observation ID is unavailable"):
            source_graph(connection, part)
    # A portable graph cannot erase the provider node/edge and merely reseal
    # the remaining application claims and source container digests.
    altered = deepcopy(graph)
    original = next(item for item in altered["nodes"] if item["identity"] == identity)
    altered["nodes"].remove(original)
    for node in altered["nodes"]:
        node["dependencies"] = [key for key in node["dependencies"] if key != original["sha256"]]
        if node["kind"] == "source":
            metadata = node["record"]["metadata"]["source_metadata"]
            metadata["observationBindings"] = [item for item in metadata["observationBindings"] if item["observationId"] != identity]
            node["identity"] = digest(node["record"]["metadata"])
    with pytest.raises(ValueError, match="closure|source binding|provider"):
        verify_graph(_rehash(altered))


def test_one_graph_cannot_rebind_an_immutable_observation_id_in_another_source(tmp_path, bilibili_api_seam):
    root = tmp_path / "archive"
    _, part = seed(root, bilibili_api_seam)
    with closing(connect_database(root / "archive.db")) as connection:
        graph = source_graph(connection, part)
    second = deepcopy(graph)
    acceptance = _acceptance(second)
    original = next(item for item in second["nodes"] if item["sha256"] == acceptance["dependencies"][0])
    source = next(item for item in second["nodes"] if item["kind"] == "source")
    artifact = next(item for item in second["nodes"] if item["kind"] == "artifact")
    # Each raw-only frozen source is individually readable. A combined closure
    # must nevertheless preserve the DB's one-ID/one-immutable-record invariant.
    source["dependencies"] = [original["sha256"]]
    second["nodes"] = [original, source, artifact]
    payload = json.loads(original["record"]["payload_json"])
    payload["private_unknown"] = "A different payload under the same original ID"
    raw = json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    envelope = json.loads(original["record"]["envelope_json"])
    envelope["payloadSha256"] = hashlib.sha256(raw.encode()).hexdigest()
    original["record"].update(payload_json=raw, payload_sha256=envelope["payloadSha256"],
                              envelope_json=canonical(envelope), envelope_sha256=digest(envelope))
    metadata = source["record"]["metadata"]["source_metadata"]
    metadata["observationBindings"] = [{"observationId": original["identity"],
        "payloadSha256": original["record"]["payload_sha256"],
        "envelopeSha256": original["record"]["envelope_sha256"]}]
    source["identity"] = digest(source["record"]["metadata"])
    second = _rehash(second)
    assert verify_graph(second)["valid"]
    combined = deepcopy(graph)
    combined["nodes"] = sorted({node["sha256"]: node for node in graph["nodes"] + second["nodes"]}.values(),
                               key=lambda node: node["sha256"])
    combined["roots"] = sorted(set(graph["roots"] + second["roots"]))
    combined["graph_sha256"] = digest({key: value for key, value in combined.items() if key != "graph_sha256"})
    with pytest.raises(ValueError, match="conflicting immutable observation identity"):
        verify_graph(combined)


def test_unpublished_generic_acceptance_graph_adapter_preserves_original_bytes(tmp_path, bilibili_api_seam):
    root = tmp_path / "archive"
    _, part = seed(root, bilibili_api_seam)
    with closing(connect_database(root / "archive.db")) as connection:
        graph = source_graph(connection, part)
    legacy = deepcopy(graph)
    original_records = {}
    for node in legacy["nodes"]:
        if node["kind"] != "metadata-acceptance":
            continue
        original_records[node["identity"]] = (node["record"]["envelope_json"], node["record"]["payload_json"])
        node["kind"] = "observation"
        node["record"].pop("owner")
        node["record"].pop("codec")
        node["dependencies"] = []
    legacy = _rehash(legacy)
    assert verify_graph(legacy)["valid"]
    private = tmp_path / "original-v1.json"
    write_graph(private, legacy)
    before = private.read_bytes()
    observed = read_graph(private)
    assert observed == legacy and private.read_bytes() == before
    for node in observed["nodes"]:
        if node["identity"] in original_records:
            assert (node["record"]["envelope_json"], node["record"]["payload_json"]) == original_records[node["identity"]]
