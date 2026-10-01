"""Live run view: spinner + agent/step status + event feed, driven by RunContext hooks.

``RunContext.on_event`` fires on agent start/end/llm_call/delegate/fallback and
``RunContext.on_step`` on each pipeline step outcome - the CLI feeds both into a
``RunView`` rendered inside a ``rich.live.Live`` (spinners animate on refresh).
"""

from __future__ import annotations

from collections import deque
from typing import Any

from rich.columns import Columns
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from .render import status_text

_EVENT_STYLE = {
    "start": "cyan",
    "end": "green",
    "llm_call": "magenta",
    "delegate": "blue",
    "fallback": "yellow",
    "skip": "dim",
    "error": "red",
}


class RunView:
    """Accumulates agent events and step outcomes; ``renderable()`` draws the live board."""

    def __init__(self, instruction: str, max_events: int = 8) -> None:
        self.instruction = instruction
        self.agents: dict[str, str] = {}  # path -> "running" or final status
        self.steps: dict[str, Any] = {}  # step_id -> StepOutcome
        self.events: deque = deque(maxlen=max_events)
        self.current = "starting"

    # ------------------------------------------------------------------ hooks
    def on_event(self, e: Any) -> RenderableType:
        self.events.append(e)
        if e.event == "start":
            self.agents[e.path] = "running"
        elif e.event == "end":
            self.agents[e.path] = e.detail
        if e.event != "end":
            name = e.path.split("/")[-1]
            self.current = f"{e.event} {name}" + (f" ({e.detail})" if e.detail else "")
        return self.renderable()

    def on_step(self, o: Any) -> RenderableType:
        self.steps[o.step_id] = o
        return self.renderable()

    # ------------------------------------------------------------------ render
    def renderable(self) -> RenderableType:
        head = Columns([Spinner("dots"), Text(f" {self.current}", style="cyan"), Text(self.instruction, style="bold")])
        parts: list[RenderableType] = [head]
        if self.agents:
            grid = Table.grid(pad=(0, 2))
            for path, st in self.agents.items():
                indent = "  " * path.count("/")
                marker = Spinner("line") if st == "running" else status_text(st)
                grid.add_row(Text(indent + path.split("/")[-1], style="bold"), marker)
            parts.append(Panel(grid, title="agents", border_style="dim"))
        if self.steps:
            t = Table("step", "component", "status", "time", box=None, pad_edge=False)
            for o in self.steps.values():
                t.add_row(o.step_id, o.component, status_text(o.status), f"{o.duration_s:.2f}s")
            parts.append(Panel(t, title="pipeline steps", border_style="dim"))
        if self.events:
            feed = Table.grid(pad=(0, 1))
            for e in self.events:
                feed.add_row(
                    Text(e.event, style=_EVENT_STYLE.get(e.event, "white")),
                    Text(f"{e.path} {e.detail}", style="dim", overflow="ellipsis", no_wrap=True),
                )
            parts.append(Panel(feed, title="events", border_style="dim"))
        return Group(*parts)
