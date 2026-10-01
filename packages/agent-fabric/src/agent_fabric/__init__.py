"""agent_fabric - spec-driven pipelines and hierarchical agents over a LiteLLM proxy."""

from __future__ import annotations

from collections.abc import Callable, Iterable

__version__ = "0.2.0"


def domain_loader(ref: str) -> Callable:
    """Resolve a domain reference: 'module:register' callable, or an existing directory
    loaded as a code-free spec pack (skills/<name>/SKILL.md, no Python required)."""
    from pathlib import Path

    p = Path(ref)
    if ":" not in ref and p.is_dir():
        return lambda reg: reg.load_domain(p)
    import importlib

    mod, _, attr = ref.partition(":")
    return getattr(importlib.import_module(mod), attr or "register")


def build_registry(domains: Iterable[Callable | str] = (), discover: bool = False):
    """Create a Registry and load domain packs (callables ``register(registry)`` or
    references resolved by :func:`domain_loader`)."""
    from .registry import Registry

    reg = Registry()
    for d in domains:
        (d if callable(d) else domain_loader(d))(reg)
    if discover:
        reg.discover_domains()
    return reg
