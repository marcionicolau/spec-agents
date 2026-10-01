"""Lakehouse domain pack: generate and verify Airflow DAGs that land sources in Trino (medallion layers)."""

from __future__ import annotations

from typing import Any

__all__ = ["register"]


def __getattr__(name: str) -> Any:
    """Lazy export: ``register`` (the ``agent_fabric.domains`` entry point) without importing the pack's heavy dependencies."""
    if name == "register":
        from .domain import register

        return register
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
