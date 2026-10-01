"""Architecture rules from CLAUDE.md, enforced on the core's source (no import-linter needed).

1. The core never imports a domain pack (rule 3).
2. Optional frameworks (and heavy scientific stacks) are imported lazily: never unguarded at module level (rule 7).
   A guarded import (`try: import x` / `except ImportError`) is allowed: that is how adapter modules such as
   `integrations/dspy.py` degrade when the extra is missing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

CORE_SRC = Path(__file__).resolve().parents[1] / "src" / "agent_fabric"

DOMAIN_PACKS = {"stat_fabric", "lake_fabric", "coworker_fabric", "text_pack"}
LAZY_ONLY = {
    "pydantic_ai",
    "dspy",
    "crewai",
    "langchain",
    "langchain_core",
    "langchain_community",
    "litellm",
    "openai",
    "pandas",
    "scipy",
    "statsmodels",
    "sklearn",
}
# modules that exist only for an optional extra and are themselves imported lazily (registry.py -> register_tabular_types)
MODULE_LEVEL_ALLOWED = {"tabular.py": {"pandas"}}


def _roots(node: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(node, ast.Import):
        return [a.name.split(".")[0] for a in node.names]
    return [] if node.level or not node.module else [node.module.split(".")[0]]


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    names = []
    if isinstance(handler.type, ast.Name):
        names = [handler.type.id]
    elif isinstance(handler.type, ast.Tuple):
        names = [e.id for e in handler.type.elts if isinstance(e, ast.Name)]
    return bool({"ImportError", "ModuleNotFoundError"} & set(names))


def _module_level_imports(tree: ast.Module) -> list[ast.Import | ast.ImportFrom]:
    """Unguarded imports executed on module import: top level and `if` blocks, minus `if TYPE_CHECKING` and
    `try` bodies that catch ImportError."""
    found: list[ast.Import | ast.ImportFrom] = []

    def walk(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.Import | ast.ImportFrom):
                found.append(node)
            elif isinstance(node, ast.If):
                if not (isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"):
                    walk(node.body)
                walk(node.orelse)
            elif isinstance(node, ast.Try):
                if not any(_catches_import_error(h) for h in node.handlers):
                    walk(node.body)
                for handler in node.handlers:
                    walk(handler.body)
                walk(node.orelse)
                walk(node.finalbody)

    walk(tree.body)
    return found


def violations(source: str, filename: str = "m.py") -> list[str]:
    tree = ast.parse(source)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            out += [f"{filename}:{node.lineno} imports domain pack '{r}'" for r in _roots(node) if r in DOMAIN_PACKS]
    allowed = MODULE_LEVEL_ALLOWED.get(filename, set())
    for node in _module_level_imports(tree):
        out += [
            f"{filename}:{node.lineno} imports '{r}' at module level (import it lazily)"
            for r in _roots(node)
            if r in LAZY_ONLY and r not in allowed
        ]
    return out


def test_scanner_detects_violations():
    src = (
        "import dspy\n"
        "try:\n    import crewai\nexcept ImportError:\n    crewai = None\n"
        "try:\n    import litellm\nexcept ValueError:\n    pass\n"
        "from stat_fabric.domain import register\n"
        "def f():\n    import pydantic_ai\n    from text_pack import register\n"
    )
    found = violations(src)
    assert any("'dspy' at module level" in v for v in found)
    assert not any("crewai" in v for v in found)  # guarded by `except ImportError`
    assert any("'litellm' at module level" in v for v in found)  # the guard must catch ImportError
    assert any("domain pack 'stat_fabric'" in v for v in found)
    assert any("domain pack 'text_pack'" in v for v in found)  # banned even inside a function
    assert not any("pydantic_ai" in v for v in found)  # lazy import in a function is fine


def test_type_checking_and_relative_imports_are_fine():
    src = "from typing import TYPE_CHECKING\nfrom . import tabular\nif TYPE_CHECKING:\n    import pandas\n"
    assert violations(src) == []


@pytest.mark.parametrize("path", sorted(CORE_SRC.rglob("*.py")), ids=lambda p: str(p.relative_to(CORE_SRC)))
def test_core_respects_boundaries(path: Path):
    found = violations(path.read_text(), filename=path.name)
    assert not found, "\n".join(found)
