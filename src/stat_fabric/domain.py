"""Statistics domain pack: components, specs and pipeline specs."""

from __future__ import annotations

from pathlib import Path

from agent_fabric.registry import Registry, declared_components

SPEC_DIR = Path(__file__).resolve().parent / "skills"
DOMAIN = "statistics"


def register(registry: Registry) -> list[str]:
    """Entry point ``agent_fabric.domains: statistics = stat_fabric.domain:register``."""
    from . import components  # noqa: F401  (declares @component classes)
    from .rules import register_planner_backend

    register_planner_backend()

    classes = [c for c in declared_components() if c.__module__.startswith("stat_fabric.")]
    return registry.load_domain(SPEC_DIR, classes)
