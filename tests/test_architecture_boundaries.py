"""Protect the dependency directions established by the architecture repair."""

import ast
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "src" / "bili_asr"


def imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = "bili_asr." + ".".join(path.relative_to(SOURCE).parts[:-1])
    package = package.rstrip(".")
    names = set()

    def walk(node):
        # Static annotations and an explicit historical -m entry do not create
        # dependencies during ordinary application imports.
        if isinstance(node, ast.If):
            if isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
                return
            if isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__":
                return
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = ".".join(package.split(".")[:len(package.split(".")) - node.level + 1]) if node.level else ""
            names.add(".".join(part for part in (prefix, node.module) if part))
        for child in ast.iter_child_nodes(node):
            walk(child)
    walk(tree)
    return names


def test_storage_and_services_never_import_command_or_application_owners():
    forbidden = {"bili_asr.cli", "bili_asr.publication", "bili_asr.workflow_runtime", "bili_asr.editorial_runtime"}
    violations = []
    for layer in ("storage", "services"):
        for path in (SOURCE / layer).glob("*.py"):
            # This module is deliberately an application composition root.
            if path.name == "workflow_application.py":
                continue
            for target in imports(path):
                if any(target == name or target.startswith(name + ".") for name in forbidden):
                    violations.append((path.name, target))
                if layer == "storage" and (target == "bili_asr.services" or target.startswith("bili_asr.services.")):
                    violations.append((path.name, target))
    assert violations == []


def test_pure_shared_models_and_policies_do_not_import_persistence_or_adapters():
    names = ("bilibili_identity", "canonical_json", "cue_models", "error_codes", "platform_identity", "transcript_selection",
             "workflow_models", "workflow_payloads", "workflow_planning", "publication_content", "publication_identity")
    forbidden = ("bili_asr.storage", "bili_asr.services", "bili_asr.cli", "bili_asr.sources", "sqlite3", "requests")
    violations = [(name, target) for name in names for target in imports(SOURCE / f"{name}.py")
                  if any(target == prefix or target.startswith(prefix + ".") for prefix in forbidden)]
    assert violations == []


def test_executor_and_parser_have_no_back_edge_to_their_consumers():
    assert "bili_asr.storage.workflow" not in imports(SOURCE / "workflow.py")
    assert "bili_asr.quality" not in imports(SOURCE / "cues.py")
    assert "bili_asr.asr.runner" not in imports(SOURCE / "asr" / "provenance.py")
