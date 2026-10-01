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
        st = ", ".join(f"{k}={v}" for k, v in self.status.items())
        heads = " | ".join(self.headlines[:4])
        who = f"{self.agent}: " if self.agent else ""
        return f"[{self.created_at}] {who}objective='{self.objective}' inputs={self.inputs_signature} {st}. {heads}".strip()


class MemoryPort(Protocol):
    def add_message(self, session_id: str, role: Role, content: str) -> None: ...
    def history(self, session_id: str, last_n: int = 10) -> list[tuple[Role, str]]: ...
    def remember_run(self, session_id: str, summary: RunSummary) -> None: ...
    def recent_runs(self, session_id: str, last_n: int = 3) -> list[RunSummary]: ...
    def clear(self, session_id: str) -> None: ...


class InMemoryMemory:
    def __init__(self) -> None:
        self._msgs: dict[str, list[tuple[Role, str]]] = defaultdict(list)
        self._runs: dict[str, list[RunSummary]] = defaultdict(list)

    def add_message(self, session_id: str, role: Role, content: str) -> None:
        self._msgs[session_id].append((role, content))

    def history(self, session_id: str, last_n: int = 10) -> list[tuple[Role, str]]:
        return self._msgs[session_id][-last_n:]

    def remember_run(self, session_id: str, summary: RunSummary) -> None:
        self._runs[session_id].append(summary)

    def recent_runs(self, session_id: str, last_n: int = 3) -> list[RunSummary]:
        return self._runs[session_id][-last_n:]

    def clear(self, session_id: str) -> None:
        self._msgs.pop(session_id, None)
        self._runs.pop(session_id, None)

    def sessions(self) -> list[str]:
        return sorted(set(self._msgs) | set(self._runs))


def memory_context(memory: MemoryPort | None, session_id: str, last_n: int = 3, max_chars: int = 1500) -> str:
    if memory is None:
        return ""
    return "\n".join(r.to_text() for r in memory.recent_runs(session_id, last_n))[-max_chars:]


def namespaced(session_id: str, path: str) -> str:
    return f"{session_id}/{path}" if path else session_id


__all__ = [
    "InMemoryMemory",
    "MemoryPort",
    "Role",
    "RunSummary",
    "memory_context",
    "namespaced",
]
