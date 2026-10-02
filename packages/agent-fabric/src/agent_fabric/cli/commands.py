"""Implementations of the ``agent-fabric`` subcommands (testable: backend injectable)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import build_registry, domain_loader
from ..agents import AgentFabric, AgentsConfig
from ..errors import DependencyError, ErrorDetail
from ..report import render_markdown

if TYPE_CHECKING:  # pragma: no cover
    from rich.console import Console


def _registry(a: Any) -> Any:
    reg = build_registry([domain_loader(d) for d in a.domains])
    for d in a.skills:
        reg.load_domain(d)
    return reg


def _fabric(a: Any, backend: Any = None) -> AgentFabric:
    from ..lint import _load_callable

    fabric = AgentFabric(_registry(a), AgentsConfig.load(a.config), backend=backend)
    for ref in a.schemas:
        for name, model in _load_callable(ref).items():
            fabric.register_schema(name, model)
    return fabric


def _load_input(spec: str) -> tuple[str, Any]:
    """'name=path' -> typed artifact by suffix."""
    name, _, raw = spec.partition("=")
    p = Path(raw)
    if not name or not p.is_file():
        raise DependencyError(
            f"invalid --input '{spec}'", [ErrorDetail(type="bad_input", msg="expected NAME=PATH of an existing file")]
        )
    suf = p.suffix.lower()
    if suf in (".csv", ".parquet", ".xlsx"):
        try:
            import pandas as pd
        except ImportError as exc:
            raise DependencyError(
                f"pandas is required for '{suf}' inputs",
                [
                    ErrorDetail(
                        type="missing_dependency",
                        msg="import pandas failed",
                        hint="pip install 'spec-agents-core[tabular]'",
                    )
                ],
            ) from exc
        return name, {".csv": pd.read_csv, ".parquet": pd.read_parquet, ".xlsx": pd.read_excel}[suf](p)
    if suf == ".json":
        return name, json.loads(p.read_text(encoding="utf-8"))
    if suf == ".jsonl":
        return name, [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return name, p.read_text(encoding="utf-8")


# ============================================================================ commands
def cmd_run(a: Any, console: Console, backend: Any = None) -> int:
    from rich.live import Live

    from .live import RunView
    from .render import report_group

    inputs = dict(_load_input(s) for s in a.input)
    fabric = _fabric(a, backend)
    plain = a.plain or not console.is_terminal
    if plain:
        report = fabric.run(a.instruction, inputs, session_id=a.session)
        console.print(render_markdown(report), markup=False)
    else:
        view = RunView(a.instruction)
        with Live(view.renderable(), console=console, refresh_per_second=10, transient=True) as live:
            report = fabric.run(
                a.instruction,
                inputs,
                session_id=a.session,
                on_event=lambda e: live.update(view.on_event(e)),
                on_step=lambda o: live.update(view.on_step(o)),
            )
        console.print(report_group(report))
    if a.out:
        Path(a.out).write_text(render_markdown(report), encoding="utf-8")
        console.print(f"[dim]report written to {a.out}[/]")
    return 0 if report.ok else 1


def cmd_lint(a: Any, console: Console) -> int:
    from ..lint import collect_issues
    from .render import issues_table

    issues = collect_issues(a.domains, a.agents, a.schemas)
    if issues:
        console.print(issues_table(issues))
    else:
        console.print("[green]no issues[/]")
    errors = sum(i.severity == "error" for i in issues)
    warnings = len(issues) - errors
    style = "red" if errors else "yellow" if warnings else "green"
    console.print(f"[{style}]{errors} error(s), {warnings} warning(s)[/]")
    return 1 if errors or (a.strict and warnings) else 0


def cmd_catalog(a: Any, console: Console) -> int:
    from .render import catalog_table

    console.print(catalog_table(_registry(a)))
    return 0


def cmd_export_skills(a: Any, console: Console) -> int:
    from ..skills_export import export_registry, validate_tree

    written = export_registry(_registry(a), a.out)
    problems = validate_tree(a.out)
    for p in problems:
        console.print(f"[red]ERROR[/] {p}", highlight=False)
    console.print(f"{len(written)} skill(s) exported to {a.out}, {len(problems)} problem(s)")
    return 1 if problems else 0


def cmd_agents(a: Any, console: Console) -> int:
    from .render import agent_tree, issues_table

    fabric = _fabric(a)
    console.print(agent_tree(fabric.config))
    issues = fabric.validate()
    if issues:
        from ..lint import LintIssue

        console.print(
            issues_table(
                LintIssue(severity="error", code=d.type, where=".".join(map(str, d.loc)), msg=d.msg, hint=d.hint)
                for d in issues
            )
        )
        return 1
    console.print("[green]agent tree is valid[/]")
    return 0


def main(argv: list[str]) -> int:  # pragma: no cover - entry via cli.main
    from . import main as _main

    return _main(argv)
