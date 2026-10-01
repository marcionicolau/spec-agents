"""Lakehouse domain pack: components, pipelines and the ``python_source`` type."""

from __future__ import annotations

from pathlib import Path

from agent_fabric.registry import Registry, declared_components

SPEC_DIR = Path(__file__).resolve().parent / "skills"
DOMAIN = "lakehouse"


def register(registry: Registry) -> list[str]:
    """Entry point ``agent_fabric.domains: lakehouse = lake_fabric.domain:register``."""
    from . import components  # noqa: F401  (declares @component classes)
    from .types import PythonSourceType

    registry.types.register(PythonSourceType())
    classes = [c for c in declared_components() if c.__module__.startswith("lake_fabric.")]
    return registry.load_domain(SPEC_DIR, classes)
