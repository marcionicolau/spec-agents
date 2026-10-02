"""Memory port (hexagonal architecture).

The fabric depends only on ``MemoryPort``. LangChain is one adapter; Redis/SQL chat
histories plug in through it without touching the core. Agents use namespaced
session ids (``<session>/<agent path>``) so each agent in a tree has its own memory.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field

type Role = Literal["user", "assistant", "system"]


class RunSummary(BaseModel):
    """What is worth remembering about one run (no raw data, no full results)."""

    objective: str
    agent: str = ""
    inputs_signature: str = ""
    steps: list[str] = Field(default_factory=list)
    status: dict[str, str] = Field(default_factory=dict)
    headlines: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    def to_text(self) -> str:
        """One-line text of the run for prompts: timestamp, agent, objective, input signature, step statuses and the first headlines."""
        st = ", ".join(f"{k}={v}" for k, v in self.status.items())
        heads = " | ".join(self.headlines[:4])
        who = f"{self.agent}: " if self.agent else ""
        return f"[{self.created_at}] {who}objective='{self.objective}' inputs={self.inputs_signature} {st}. {heads}".strip()


class MemoryPort(Protocol):
    def add_message(self, session_id: str, role: Role, content: str) -> None:
        """Append a chat message (``user``, ``assistant`` or ``system``) to the session."""
        ...

    def history(self, session_id: str, last_n: int = 10) -> list[tuple[Role, str]]:
        """The last ``last_n`` chat messages of the session as ``(role, content)`` pairs, oldest first."""
        ...

    def remember_run(self, session_id: str, summary: RunSummary) -> None:
        """Store the summary of a finished run (objective, steps, status, headlines; never raw data)."""
        ...

    def recent_runs(self, session_id: str, last_n: int = 3) -> list[RunSummary]:
        """The last ``last_n`` run summaries of the session, oldest first; routers and planners receive them as context."""
        ...

    def clear(self, session_id: str) -> None:
        """Forget everything stored for the session."""
        ...


class InMemoryMemory:
    """Process-local `MemoryPort`: chat messages and run summaries per session, lost on exit."""

    def __init__(self) -> None:
        self._msgs: dict[str, list[tuple[Role, str]]] = defaultdict(list)
        self._runs: dict[str, list[RunSummary]] = defaultdict(list)

    def add_message(self, session_id: str, role: Role, content: str) -> None:
        """Append a chat message to the session."""
        self._msgs[session_id].append((role, content))

    def history(self, session_id: str, last_n: int = 10) -> list[tuple[Role, str]]:
        """The last ``last_n`` chat messages of the session as ``(role, content)`` pairs, oldest first."""
        return self._msgs[session_id][-last_n:]

    def remember_run(self, session_id: str, summary: RunSummary) -> None:
        """Store the summary of a finished run in the session."""
        self._runs[session_id].append(summary)

    def recent_runs(self, session_id: str, last_n: int = 3) -> list[RunSummary]:
        """The last ``last_n`` run summaries of the session, oldest first."""
        return self._runs[session_id][-last_n:]

    def clear(self, session_id: str) -> None:
        """Forget the messages and run summaries of the session."""
        self._msgs.pop(session_id, None)
        self._runs.pop(session_id, None)

    def sessions(self) -> list[str]:
        """Sorted ids of every session that has messages or runs."""
        return sorted(set(self._msgs) | set(self._runs))


def memory_context(memory: MemoryPort | None, session_id: str, last_n: int = 3, max_chars: int = 1500) -> str:
    """Render the last ``last_n`` run summaries of a session as prompt context, keeping the newest ``max_chars`` characters.

    Returns an empty string when ``memory`` is ``None``.
    """
    if memory is None:
        return ""
    return "\n".join(r.to_text() for r in memory.recent_runs(session_id, last_n))[-max_chars:]


def namespaced(session_id: str, path: str) -> str:
    """Return the per-agent memory key ``<session_id>/<path>`` (just the session id for the root)."""
    return f"{session_id}/{path}" if path else session_id


__all__ = [
    "InMemoryMemory",
    "MemoryPort",
    "Role",
    "RunSummary",
    "memory_context",
    "namespaced",
]
