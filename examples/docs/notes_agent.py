"""Run the code-free ``notes`` agent tree with a scripted model: the model plans, a prompt component writes."""

from __future__ import annotations

from pathlib import Path

from agent_fabric import build_registry
from agent_fabric.agents import AgentFabric, AgentsConfig
from agent_fabric.llm import ScriptedBackend
from agent_fabric.report import render_markdown

NOTES = Path(__file__).resolve().parent.parent / "notes"

backend = ScriptedBackend(
    [
        '{"objective": "digest", "steps": [{"id": "s", "component": "summarize_notes"}]}',  # the planner's answer
        '{"summary": "Ship on Friday; Ana owns the release notes."}',  # the prompt step's answer
    ]
)
fabric = AgentFabric(build_registry(), AgentsConfig.load(NOTES), backend=backend)
report = fabric.run("Digest this meeting", {"transcript": "We agreed to ship on Friday. Ana owns the release notes."})
assert report.result.status == "ok"
print(report.usage)  # {'agent_runs': 1, 'delegations': 0, 'llm_calls': 2}
print(render_markdown(report))  # agent tree, per-agent results and the event trace
