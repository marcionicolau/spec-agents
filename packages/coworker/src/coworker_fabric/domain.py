"""Coworker domain pack: components and pipelines."""

from __future__ import annotations

from pathlib import Path

from agent_fabric.compat import requires_api
from agent_fabric.registry import Registry, declared_components

SPEC_DIR = Path(__file__).resolve().parent / "skills"
DOMAIN = "coworker"


@requires_api(1)
def register(registry: Registry) -> list[str]:
    """Entry point ``agent_fabric.domains: coworker = coworker_fabric.domain:register``."""
    from . import components  # noqa: F401  (declares @component classes)

    classes = [c for c in declared_components() if c.__module__.startswith("coworker_fabric.")]
    return registry.load_domain(SPEC_DIR, classes)


__all__ = [
    "SPEC_DIR",
    "register",
]
