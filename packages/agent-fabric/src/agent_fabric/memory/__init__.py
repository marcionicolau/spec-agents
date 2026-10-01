from .base import InMemoryMemory, MemoryPort, RunSummary, memory_context, namespaced

__all__ = ["InMemoryMemory", "LangChainMemory", "MemoryPort", "RunSummary", "memory_context", "namespaced"]


def __getattr__(name):
    if name == "LangChainMemory":
        from .langchain_adapter import LangChainMemory

        return LangChainMemory
    raise AttributeError(name)
