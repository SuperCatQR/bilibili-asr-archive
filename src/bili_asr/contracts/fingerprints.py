"""Pinned snapshot identities, separate from migration-source signatures."""
from importlib import resources
import json


def database_fingerprint(kind: str, imports: bool = False, supplements: bool = False) -> str:
    if type(imports) is not bool or type(supplements) is not bool:
        raise ValueError("snapshot extension flag must be boolean")
    key = kind + ("+preserved-body-import-v1" if imports else "")
    if supplements:
        key += "+legacy-part-title-supplement-v1"
    document = json.loads(resources.files("bili_asr.contracts").joinpath(
        "database-fingerprints.json").read_text(encoding="utf-8"))
    try:
        return document["contracts"][key]
    except KeyError as exc:
        raise ValueError(f"unsupported snapshot database contract: {key}") from exc
