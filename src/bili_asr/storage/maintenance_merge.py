"""Lossless relational union. Conflicting identities never overwrite history."""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from bili_asr.storage.maintenance_selection import _JSON_EDGES
from bili_asr.storage.snapshots import _identifier as quote, _schema, validate_snapshot_database
from bili_asr.storage.upgrade_evidence import readonly


def merge_database(incoming: Path, destination: Path) -> dict:
    """Union identical/disjoint rows and map colliding integer primary keys.

    UUID/natural-key collisions with different evidence are conflicts. Mapping
    touches registered identity envelopes, never arbitrary frozen provider text.
    All changes occur in a caller-owned staging database, in one transaction.
    """
    validate_snapshot_database(incoming)
    validate_snapshot_database(destination)
    with closing(readonly(incoming)) as source, closing(sqlite3.connect(destination)) as target:
        if _schema(source) != _schema(target):
            raise ValueError("merge requires identical registered database schemas")
        tables = [row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        shapes = {}
        mappings = {}
        counts = {}
        # Determine mappings before copying any dependent rows.
        for name in tables:
            info = list(source.execute(f"PRAGMA table_info({quote(name)})"))
            columns = [row[1] for row in info]
            keys = [row[1] for row in sorted(info, key=lambda row: row[5]) if row[5]]
            integer = len(keys) == 1 and next(row[2].upper() for row in info if row[1] == keys[0]) == "INTEGER"
            shapes[name] = (columns, keys, integer)
            mappings[name] = {}
            counts[name] = {"added": 0, "skipped": 0, "mapped": 0}
            if not integer:
                continue
            key = keys[0]
            maximum = max(source.execute(f"SELECT COALESCE(MAX({quote(key)}),0) FROM {quote(name)}").fetchone()[0],
                          target.execute(f"SELECT COALESCE(MAX({quote(key)}),0) FROM {quote(name)}").fetchone()[0])
            for row in source.execute(f"SELECT * FROM {quote(name)} ORDER BY {quote(key)}"):
                identity = row[columns.index(key)]
                existing = target.execute(f"SELECT * FROM {quote(name)} WHERE {quote(key)}=?", (identity,)).fetchone()
                if existing is not None and existing != row:
                    maximum += 1
                    mappings[name][identity] = maximum
                    counts[name]["mapped"] += 1
        def rewrite_envelope(value):
            if not isinstance(value, dict):
                return value
            result = dict(value)
            for key, (table, _) in _JSON_EDGES.items():
                if key in result:
                    result[key] = mappings[table].get(result[key], result[key])
            if isinstance(result.get("preserve_publication"), dict):
                result["preserve_publication"] = rewrite_envelope(result["preserve_publication"])
            return result
        foreign_keys = {}
        for name in tables:
            groups = defaultdict(list)
            for fk in source.execute(f"PRAGMA foreign_key_list({quote(name)})"):
                groups[fk[0]].append(fk)
            foreign_keys[name] = list(groups.values())

        def transformed(name, original):
            columns, keys, integer = shapes[name]
            row = list(original)
            if integer:
                index = columns.index(keys[0])
                row[index] = mappings[name].get(row[index], row[index])
            for group in foreign_keys[name]:
                if len(group) == 1:
                    fk = group[0]
                    index = columns.index(fk[3])
                    row[index] = mappings[fk[2]].get(row[index], row[index])
            for column in ("payload_json", "result_json", "evidence_json"):
                if column not in columns or row[columns.index(column)] is None:
                    continue
                if (name, column) not in {("workflow_jobs", "payload_json"), ("workflow_attempts", "result_json"), ("transcript_asr_evidence", "evidence_json")}:
                    continue
                index = columns.index(column)
                value = json.loads(row[index])
                rewritten = rewrite_envelope(value)
                if rewritten != value:
                    row[index] = json.dumps(rewritten, ensure_ascii=False, separators=(",", ":"))
            return row

        # A parent remap can change an otherwise identical child. Reach a fixed
        # point before inserting any rows, so its own integer key also maps.
        while True:
            added = False
            for name in tables:
                columns, keys, integer = shapes[name]
                if not integer:
                    continue
                key = keys[0]
                maximum = max([0, *mappings[name].values(), source.execute(f"SELECT COALESCE(MAX({quote(key)}),0) FROM {quote(name)}").fetchone()[0],
                               target.execute(f"SELECT COALESCE(MAX({quote(key)}),0) FROM {quote(name)}").fetchone()[0]])
                for original in source.execute(f"SELECT * FROM {quote(name)} ORDER BY {quote(key)}"):
                    identity = original[columns.index(key)]
                    if identity in mappings[name]:
                        continue
                    existing = target.execute(f"SELECT * FROM {quote(name)} WHERE {quote(key)}=?", (identity,)).fetchone()
                    if existing is not None and tuple(transformed(name, original)) != existing:
                        maximum += 1
                        mappings[name][identity] = maximum
                        counts[name]["mapped"] += 1
                        added = True
            if not added:
                break
        # Identity embedded in frozen prompts, prepared snapshots, segment refs,
        # publication documents and content digests is evidence, not an FK to
        # rewrite. A mapping of these histories requires a registered semantic
        # converter; refuse it before changing the staging database.
        protected = {"bilibili_users", "source_videos", "source_creators", "video_parts", "transcripts", "transcript_segments", "editorial_inputs",
                     "editorial_input_versions", "editorial_revisions", "editorial_model_calls",
                     "workflow_publications", "publication_editions", "publication_content_versions", "asr_models"}
        conflicts = sorted(name for name in protected if mappings.get(name))
        if conflicts:
            raise ValueError("merge frozen-history identity conflict requires explicit replace or disjoint selection: " + ",".join(conflicts))
        target.execute("PRAGMA foreign_keys=OFF")
        target.execute("BEGIN IMMEDIATE")
        for name in tables:
            columns, keys, integer = shapes[name]
            for original in source.execute(f"SELECT * FROM {quote(name)} ORDER BY rowid"):
                row = transformed(name, original)
                if keys:
                    condition = " AND ".join(f"{quote(key)} IS ?" for key in keys)
                    params = [row[columns.index(key)] for key in keys]
                    existing = target.execute(f"SELECT * FROM {quote(name)} WHERE {condition}", params).fetchone()
                else:
                    condition = " AND ".join(f"{quote(column)} IS ?" for column in columns)
                    existing = target.execute(f"SELECT * FROM {quote(name)} WHERE {condition} LIMIT 1", row).fetchone()
                if existing is not None:
                    if tuple(row) != existing:
                        raise ValueError("merge identity conflict; choose replace or a narrower selection: " + name)
                    counts[name]["skipped"] += 1
                    continue
                try:
                    target.execute(f"INSERT INTO {quote(name)}({','.join(map(quote, columns))}) VALUES({','.join('?' for _ in columns)})", row)
                except sqlite3.IntegrityError as exc:
                    raise ValueError("merge unique identity conflict: " + name) from exc
                counts[name]["added"] += 1
        if target.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("merge generated dangling foreign keys")
        target.commit()
    validate_snapshot_database(destination)
    return {"tables": counts, "id_mappings": {name: [{"source": key, "target": value} for key, value in sorted(values.items())]
                                             for name, values in mappings.items() if values},
            "overwritten": 0, "conflicts": []}
