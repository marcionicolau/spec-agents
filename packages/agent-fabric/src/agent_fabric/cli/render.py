"""Rich renderables for the agent-fabric CLI: tables, trees, report panels."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

if TYPE_CHECKING:  # pragma: no cover
    from ..agents.runtime import AgentResult, AgentRunReport
    from ..agents.spec import AgentsConfig
    from ..lint import LintIssue

STATUS_STYLE = {"ok": "green", "partial": "yellow", "failed": "red", "skipped": "dim"}
SEVERITY_STYLE = {"error": "red", "warning": "yellow"}


def status_text(status: str) -> Text:
    return Text(status, style=STATUS_STYLE.get(status, "white"))


def issues_table(issues: Iterable[LintIssue]) -> Table:
    t = Table("severity", "code", "where", "message", box=None, pad_edge=False)
    t.columns[0].style = "bold"
    for i in issues:
        t.add_row(
            Text(i.severity, style=SEVERITY_STYLE.get(i.severity, "white")),
            i.code,
            i.where,
            i.msg + (f"\n[dim]{i.hint}[/]" if i.hint else ""),
        )
    return t


def catalog_table(registry: Any) -> Table:
    """All registered components/pipelines: name, kind, domain, ports, description."""
    pipelines = set(registry.pipelines())
    t = Table(
        "name", "kind", "domain", "runtime", "params", "inputs", "outputs", "description", box=None, pad_edge=False
    )
    t.columns[0].style = "bold cyan"
    for name in registry.names():
        spec = registry.spec(name)
        is_pipeline = name in pipelines
        t.add_row(
            name,
            "pipeline" if is_pipeline else "component",
            spec.domain,
            "-" if is_pipeline else spec.runtime,
            str(len(spec.params)),
            ",".join(spec.inputs) or "-",
            ",".join(spec.outputs) or "-",
            Text(spec.description, overflow="ellipsis", no_wrap=True),
        )
    return t


def agent_tree(config: AgentsConfig) -> Tree:
    """The declared agent tree (roots -> sub_agents), annotated with kind/backend."""

    def label(name: str) -> Text:
        s = config.agents[name]
        meta = f"[dim]{s.kind} · {s.backend}" + (f" · {s.strategy}" if s.kind == "supervisor" else "") + "[/]"
        return Text.assemble((name, "bold cyan"), " ", Text.from_markup(meta))

    def add(node: Tree, name: str, trail: tuple[str, ...]) -> None:
        for child in config.agents[name].sub_agents:
            branch = node.add(label(child))
            if child in trail:
                branch.add("[red]cycle![/]")
            else:
                add(branch, child, trail + (child,))

    roots = config.roots() or list(config.agents)
    if len(roots) == 1:
        tree = Tree(label(roots[0]))
        add(tree, roots[0], (roots[0],))
        return tree
    tree = Tree("[bold]agents[/]")
    for r in roots:
        node = tree.add(label(r))
        add(node, r, (r,))
    return tree


def _result_node(r: AgentResult) -> Text:
    line = Text.assemble((r.agent, "bold"), " ", status_text(r.status), f" [dim]{r.kind}[/]")
    if r.summary:
        line.append(" — " + r.summary[:100], style="dim")
    return line


def _result_tree(r: AgentResult) -> Tree:
    node = Tree(_result_node(r))
    for c in r.children:
        node.children.append(_result_tree(c))
    return node


def report_group(report: AgentRunReport, trace: bool = False) -> RenderableType:
    """Final run rendering: agent tree, per-agent results, interpretations, errors, usage."""
    parts: list[RenderableType] = [_result_tree(report.result)]
    for r in report.result.walk():
        out = r.output if isinstance(r.output, dict) else {}
        for it in out.get("interpretations", []):
            findings = "\n".join(f"  - {f}" for f in it["findings"])
            caveats = "\n".join(f"  ! {c}" for c in it["caveats"])
            body = f"[bold]{it['headline']}[/]\n{findings}" + (f"\n[yellow]{caveats}[/]" if caveats else "")
            parts.append(Panel(body, title=f"{it['step_id']} ({it['confidence']})", border_style="blue"))
        if r.error:
            t = Table("loc", "type", "msg", "hint", box=None, pad_edge=False)
            for d in r.error.details[:8]:
                t.add_row(".".join(map(str, d.loc)) or "-", d.type, d.msg, d.hint or "")
            parts.append(Panel(t, title=f"[red]{r.error.category.value}[/] {r.error.message}", border_style="red"))
    usage = ", ".join(f"{k}={v}" for k, v in report.usage.items())
    parts.append(Text(f"usage: {usage}", style="dim"))
    if trace:
        t = Table("t (s)", "path", "event", "detail", box=None, pad_edge=False)
        for e in report.trace:
            t.add_row(f"{e.at:.3f}", e.path, e.event, e.detail)
        parts.append(Panel(t, title="trace", border_style="dim"))
    return Group(*parts)
