"""Fresh imports exercise the public API without relying on collection order."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_fresh(code: str) -> None:
    environment = os.environ.copy()
    source = Path(__file__).resolve().parents[1] / "src"
    environment["PYTHONPATH"] = str(source) + os.pathsep + environment.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, env=environment, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


@pytest.mark.parametrize("first", [
    "bili_asr.platform_identity", "bili_asr.sources.protocols", "bili_asr.sources.models",
])
def test_pure_source_ports_do_not_bootstrap_storage_or_clients(first):
    _run_fresh(f"""
from importlib import import_module
import sys
import_module({first!r})
from bili_asr.sources import ContentRef, SourceAccessObservation, VideoPart, GatewayError
assert VideoPart('BVtest', 2, 99, 'p2', 1000).content_ref == ContentRef('bilibili', 'BVtest', 2)
assert SourceAccessObservation('anonymous', True).verified is True
assert GatewayError('rate_limited').code == 'rate_limited'
assert 'bili_asr.storage' not in sys.modules
assert not any(name == 'bilibili_api' or name.startswith('bilibili_api.') for name in sys.modules)
""")


def test_legacy_identity_codec_does_not_initialize_source_adapters():
    _run_fresh("""
import sys
from bili_asr.bilibili_identity import legacy_bilibili_source_ref, bilibili_source_url
source = {'bvid': 'BVtest', 'pageIndex': 2, 'videoPartId': 7,
          'url': 'https://www.bilibili.com/video/BVtest/?p=3'}
ref = legacy_bilibili_source_ref(source)
assert bilibili_source_url(ref) == source['url']
assert 'bili_asr.sources' not in sys.modules
assert 'bili_asr.storage' not in sys.modules
from bili_asr.publication_content import normalize_content
assert callable(normalize_content)
assert 'bili_asr.sources' not in sys.modules
assert 'bili_asr.storage' not in sys.modules
from bili_asr.sources.bilibili_identity import legacy_bilibili_source_ref as alias
assert alias is legacy_bilibili_source_ref
""")


@pytest.mark.parametrize("first", [
    "bili_asr.asr.provenance", "bili_asr.asr.runner", "bili_asr.storage.editorial",
    "bili_asr.publication", "bili_asr.archive", "bili_asr.workflow",
])
def test_public_apis_work_after_any_supported_import_order(first):
    _run_fresh(f"""
from importlib import import_module
from types import ModuleType
import_module({first!r})
for name in ('bili_asr.asr.runner', 'bili_asr.asr.provenance', 'bili_asr.archive',
             'bili_asr.storage.editorial', 'bili_asr.publication', 'bili_asr.workflow'):
    import_module(name)
from bili_asr import asr
from bili_asr.error_codes import validate_error_code
from bili_asr.storage import validate_error_code as storage_code
from bili_asr.publication import normalize_content
assert type(asr) is ModuleType
assert type(import_module('bili_asr.asr.provenance')) is ModuleType
assert asr.provenance()['model_name']
assert storage_code is validate_error_code
assert storage_code('rate_limited') == 'rate_limited'
content = normalize_content({{'title': 'title', 'markdown': 'body', 'summary': '', 'tags': [],
    'source': {{'bvid': 'BVtest', 'pageIndex': 2, 'videoPartId': 7,
               'url': 'https://www.bilibili.com/video/BVtest/?p=3'}},
    'attribution': 'author', 'editorNote': ''}})
assert content['markdown'] == 'body\\n'
assert content['source']['pageIndex'] == 2
assert 'platform' not in content['source']
""")
