"""agent_fabric - spec-driven pipelines and hierarchical agents over a LiteLLM proxy."""

from __future__ import annotations

from typing import Callable, Iterable

__version__ = "0.2.0"


def build_registry(domains: Iterable[Callable] = (), discover: bool = False):
    """Create a Registry and load domain packs (callables ``register(registry)``)."""
    from .registry import Registry

    reg = Registry()
    for register in domains:
        register(reg)
    if discover:
        reg.discover_domains()
    return reg
