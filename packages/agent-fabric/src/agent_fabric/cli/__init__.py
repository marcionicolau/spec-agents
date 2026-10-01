"""Unified command line for agent_fabric (rich-powered).

```text
agent-fabric run <config_dir> [--input name=path ...] "instruction"
agent-fabric lint [--domains ref|dir ...] [--agents dir] [--schemas mod:MAP ...] [--strict]
agent-fabric catalog [--domains ref|dir ...] [--skills dir ...]
agent-fabric agents <config_dir>
agent-fabric export-skills --out DIR [--domains ref|dir ...] [--skills dir ...]
```

`python -m agent_fabric.cli` accepts the same subcommands.
"""

from __future__ import annotations

import argparse
import sys

from ..errors import FabricError

_PROPS = ("domains", "skills", "schemas")


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--domains", nargs="*", default=[], help="module:register refs or spec dirs (code-free packs)")
    p.add_argument("--skills", nargs="*", default=[], help="extra spec directories (skills/<name>/SKILL.md)")
    p.add_argument("--schemas", nargs="*", default=[], help="module:MAPPING of output schemas")


def build_parser() -> argparse.ArgumentParser:
    """Build the ``agent-fabric`` argument parser.

    Subcommands: ``run``, ``lint``, ``catalog``, ``agents`` and ``export-skills``. Returned separately from `main` so it can be tested and
    used to generate the CLI reference.
    """
    ap = argparse.ArgumentParser(prog="agent-fabric", description="Spec-driven pipelines and agents over LiteLLM.")
    sub = ap.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run an agent tree on an instruction (live view on a terminal)")
    run.add_argument("config", help="config dir (fabric.md + agents/*/AGENT.md) or fabric.md file")
    run.add_argument("instruction")
    run.add_argument(
        "--input",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="input artifact: .csv/.parquet (pandas), .json/.jsonl, .txt/.md",
    )
    run.add_argument("--session", default="default")
    run.add_argument("--out", help="also write the Markdown report to this file")
    run.add_argument("--plain", action="store_true", help="plain Markdown output, no live view")
    _common(run)

    lint = sub.add_parser("lint", help="drift lint for skills and agents (rich tables)")
    lint.add_argument("--agents", help="agents config dir or file")
    lint.add_argument("--strict", action="store_true", help="fail on warnings too")
    _common(lint)

    catalog = sub.add_parser("catalog", help="table of registered components and pipelines")
    _common(catalog)

    agents = sub.add_parser("agents", help="show the declared agent tree of a config dir")
    agents.add_argument("config")
    _common(agents)

    export = sub.add_parser(
        "export-skills",
        help="write spec-compliant Agent Skills (agentskills.io) for every registered skill and validate them",
    )
    export.add_argument("--out", required=True, help="output directory (one <kebab-name>/SKILL.md per skill)")
    _common(export)

    return ap


def main(argv: list[str] | None = None) -> int:
    """Entry point of the ``agent-fabric`` command; returns the process exit code.

    Parses ``argv`` (default ``sys.argv``), picks plain or rich output depending on ``--plain`` and whether stdout is a terminal, and
    reports a `FabricError` as a located error instead of a traceback.
    """
    from rich.console import Console

    from . import commands

    a = build_parser().parse_args(argv)
    plain = getattr(a, "plain", False)
    console = Console(no_color=plain or not sys.stdout.isatty(), highlight=not plain)
    fn = {
        "run": commands.cmd_run,
        "lint": commands.cmd_lint,
        "catalog": commands.cmd_catalog,
        "agents": commands.cmd_agents,
        "export-skills": commands.cmd_export_skills,
    }[a.command]
    try:
        return fn(a, console)
    except FabricError as exc:
        console.print(f"[bold red]error[/] ({exc.category.value}): {exc.message}")
        for d in exc.details[:10]:
            loc = ".".join(map(str, d.loc)) or "-"
            console.print(f"  [red]{d.type}[/] [dim]{loc}[/] {d.msg}" + (f"  [cyan]{d.hint}[/]" if d.hint else ""))
        return 2
    except KeyboardInterrupt:
        console.print("[yellow]interrupted[/]")
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = ["build_parser", "main"]
