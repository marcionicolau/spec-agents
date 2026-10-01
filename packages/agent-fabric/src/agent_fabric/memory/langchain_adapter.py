"""LangChain memory wrapper implementing ``MemoryPort``.

Any ``BaseChatMessageHistory`` works (in-memory, Redis, SQL, Postgres, ...):

    from langchain_community.chat_message_histories import RedisChatMessageHistory
    mem = LangChainMemory(lambda sid: RedisChatMessageHistory(sid, url="redis://localhost:6379/0"))

Run summaries are stored as ``AIMessage`` with ``additional_kwargs['kind'] = 'run_summary'``
so they travel with the same backend and can be filtered out of chat history.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..errors import MissingOptionalDependency
from .base import Role, RunSummary

KIND = "run_summary"


class LangChainMemory:
    def __init__(self, history_factory: Callable[[str], Any] | None = None, window: int = 50) -> None:
        try:
            from langchain_core import messages as lc_messages
            from langchain_core.chat_history import InMemoryChatMessageHistory
        except ImportError as exc:  # pragma: no cover
            raise MissingOptionalDependency("langchain-core", "langchain") from exc
        self._lc = lc_messages
        self._factory = history_factory or (lambda _sid: InMemoryChatMessageHistory())
        self._stores: dict[str, Any] = {}
        self.window = window

    def _store(self, session_id: str) -> Any:
        if session_id not in self._stores:
            self._stores[session_id] = self._factory(session_id)
        return self._stores[session_id]

    # ---- MemoryPort
    def add_message(self, session_id: str, role: Role, content: str) -> None:
        cls = {"user": self._lc.HumanMessage, "assistant": self._lc.AIMessage, "system": self._lc.SystemMessage}[role]
        self._store(session_id).add_message(cls(content=content))

    def history(self, session_id: str, last_n: int = 10) -> list[tuple[Role, str]]:
        role_of = {"human": "user", "ai": "assistant", "system": "system"}
        msgs = [m for m in self._store(session_id).messages if m.additional_kwargs.get("kind") != KIND]
        return [(role_of.get(m.type, "assistant"), str(m.content)) for m in msgs[-min(last_n, self.window):]]

    def remember_run(self, session_id: str, summary: RunSummary) -> None:
        self._store(session_id).add_message(
            self._lc.AIMessage(content=summary.to_text(),
                               additional_kwargs={"kind": KIND, "payload": summary.model_dump()}))

    def recent_runs(self, session_id: str, last_n: int = 3) -> list[RunSummary]:
        runs = [RunSummary.model_validate(m.additional_kwargs["payload"])
                for m in self._store(session_id).messages if m.additional_kwargs.get("kind") == KIND]
        return runs[-last_n:]

    def clear(self, session_id: str) -> None:
        self._store(session_id).clear()

    # ---- LangChain interop
    def as_langchain_history(self, session_id: str) -> Any:
        """Raw ``BaseChatMessageHistory`` - e.g. for ``RunnableWithMessageHistory``."""
        return self._store(session_id)
