from __future__ import annotations

import ast
from pathlib import Path

CORE_MODULES = (
    "scanner.py",
    "planner.py",
    "executor.py",
    "quarantine.py",
    "rollback.py",
    "backup.py",
    "workflow.py",
    "ai_bundle.py",
)
FORBIDDEN_IMPORTS = {"argparse", "PySide6", "requests", "httpx", "openai", "anthropic"}
NETWORK_OR_AI_IMPORTS = {
    "aiohttp",
    "anthropic",
    "httpx",
    "mcp",
    "openai",
    "requests",
    "socket",
    "urllib",
}


def test_core_services_do_not_import_entrypoint_or_network_dependencies() -> None:
    source_root = Path(__file__).parents[1] / "src" / "s4mod"
    for filename in CORE_MODULES:
        tree = ast.parse((source_root / filename).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
        assert imported.isdisjoint(FORBIDDEN_IMPORTS), filename


def test_gui_does_not_reimplement_core_file_rules() -> None:
    source = Path(__file__).parents[1] / "src" / "s4mod" / "gui.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    relative_imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module
    }
    assert relative_imports.isdisjoint(
        {"archives", "hashing", "planner", "quarantine", "scanner", "storage"}
    )


def test_application_has_no_network_or_ai_client_imports() -> None:
    source_root = Path(__file__).parents[1] / "src" / "s4mod"
    for source in source_root.glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
        assert imported.isdisjoint(NETWORK_OR_AI_IMPORTS), source.name
