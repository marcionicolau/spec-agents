"""Generate the API reference pages at build time (mkdocs-gen-files): one page per package.

A module appears when its source defines ``__all__`` (the public API declaration, see tests/test_public_api.py);
mkdocstrings then renders only those public members. Run through ``mkdocs build``; not meant to be imported.
"""

from __future__ import annotations

import ast
from pathlib import Path

import mkdocs_gen_files

ROOT = Path(__file__).resolve().parents[1]
PYPI_NAMES = {
    "agent-fabric": "spec-agents-core",
    "statistics": "spec-agents-statistics",
    "lakehouse": "spec-agents-lakehouse",
    "coworker": "spec-agents-coworker",
    "text-pack": "spec-agents-text",
}
PACKAGES = {  # package directory -> (module, one-line description)
    "agent-fabric": (
        "agent_fabric",
        "Generic core: specs, registry, pipelines, executor, agents, LLM planning, memory, CLI.",
    ),
    "statistics": ("stat_fabric", "Statistics domain pack."),
    "lakehouse": ("lake_fabric", "Lakehouse domain pack: Airflow DAG generation for Trino/Iceberg."),
    "coworker": ("coworker_fabric", "Coworker domain pack: context selection, review and patch proposals."),
    "text-pack": ("text_pack", "Text domain pack and template for new packs."),
}


def has_all(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        isinstance(n, ast.Assign | ast.AnnAssign)
        and "__all__"
        in {t.id for t in (n.targets if isinstance(n, ast.Assign) else [n.target]) if isinstance(t, ast.Name)}
        for n in tree.body
    )


def modules(dist: str, module: str) -> list[str]:
    src = ROOT / "packages" / dist / "src"
    out = []
    for path in sorted((src / module).rglob("*.py")):
        if path.name == "__main__.py" or not has_all(path):
            continue
        rel = path.relative_to(src).with_suffix("")
        parts = rel.parts[:-1] if rel.name == "__init__" else rel.parts
        out.append(".".join(parts))
    return out


nav_lines = ["# API reference", ""]
for dist, (module, summary) in PACKAGES.items():
    names = modules(dist, module)
    page = f"reference/{dist}.md"
    with mkdocs_gen_files.open(page, "w") as f:
        f.write(
            f"# {PYPI_NAMES[dist]}\n\n{summary}\n\nPyPI name: `{PYPI_NAMES[dist]}`. Import name: `{module}`. Only names listed in a module's `__all__` are public API.\n"
        )
        for name in names:
            f.write(f"\n## `{name}`\n\n::: {name}\n    options:\n      heading_level: 3\n")
    mkdocs_gen_files.set_edit_path(page, f"packages/{dist}/src/{module}")
    nav_lines.append(f"- [{PYPI_NAMES[dist]}]({dist}.md) - {summary} ({len(names)} modules)")


def cli_reference() -> str:
    """Help text of every ``agent-fabric`` subcommand, straight from the argparse parser."""
    import argparse

    from agent_fabric.cli import build_parser

    parser = build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    out = [
        "# CLI reference",
        "",
        "Generated from the argument parser (`agent-fabric --help`).",
        "",
        "```text",
        parser.format_help().rstrip(),
        "```",
    ]
    for name, p in sub.choices.items():
        out += ["", f"## `agent-fabric {name}`", "", "```text", p.format_help().rstrip(), "```"]
    return "\n".join(out) + "\n"


with mkdocs_gen_files.open("reference/cli.md", "w") as f:
    f.write(cli_reference())
nav_lines.append("- [CLI](cli.md) - the `agent-fabric` command")
with mkdocs_gen_files.open("reference/index.md", "w") as f:
    f.write("\n".join(nav_lines) + "\n")
