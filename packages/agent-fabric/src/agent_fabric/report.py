"""Markdown rendering of an agent run (tree, per-agent summaries, pipeline interpretations, trace)."""

from __future__ import annotations

from .agents.runtime import AgentResult, AgentRunReport


def _agent_section(r: AgentResult, level: int) -> list[str]:
    h = "#" * min(level, 6)
    lines = [f"{h} {r.agent} · {r.kind} · {r.status}", ""]
    if r.summary:
        lines += [f"**{r.summary}**", ""]
    out = r.output if isinstance(r.output, dict) else {}
    if "planner" in out or "pipeline" in out:
        lines.append(f"_{'planner: ' + out['planner'] if 'planner' in out else 'pipeline: ' + out['pipeline']}_")
        lines.append("")
        for it in out.get("interpretations", []):
            lines.append(f"- **{it['step_id']}** — {it['headline']}")
            lines += [f"  - {f}" for f in it["findings"]]
            lines += [f"  - ⚠ {c}" for c in it["caveats"]]
        for step, fb in out.get("failures", {}).items():
            lines.append(f"- **{step}** failed: `{fb.splitlines()[2].strip() if len(fb.splitlines()) > 2 else fb}`")
        lines.append("")
    answer = out.get("answer")
    if isinstance(answer, dict):
        text = answer.get("text")
        lines += [text, ""] if text else [f"```json\n{answer}\n```", ""]
    if r.error and r.status != "ok":
        lines.append(f"Error ({r.error.category.value}): {r.error.message}")
        lines += [
            f"- `{'.'.join(map(str, d.loc))}` {d.msg}" + (f" — {d.hint}" if d.hint else "") for d in r.error.details[:6]
        ]
        lines.append("")
    lines += [f"> {n}" for n in r.notes]
    for c in r.children:
        lines += _agent_section(c, level + 1)
    return lines


def render_markdown(report: AgentRunReport, trace: bool = True) -> str:
    lines = [f"# {report.instruction}", "", f"usage: {report.usage}", "", "```", report.result.tree(), "```", ""]
    lines += _agent_section(report.result, 2)
    if trace:
        lines += ["## Trace", "", "| t (s) | agent | event | detail |", "|---|---|---|---|"]
        lines += [f"| {e.at:.3f} | {e.path} | {e.event} | {e.detail.replace('|', '/')} |" for e in report.trace]
    return "\n".join(lines)
