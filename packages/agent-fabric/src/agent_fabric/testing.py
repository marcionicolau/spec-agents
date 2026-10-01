"""Test helpers for component tests (offline, no LLM)."""

from __future__ import annotations

from .component import ArtifactStore, StepContext


def run_component(registry, name, params=None, **inputs):
    """Execute one registered component with the given inputs; returns ``(result, artifact_store)``."""
    comp = registry.get(name)
    store = ArtifactStore()
    result = comp.execute(inputs, params or {}, StepContext(store, "t", comp.spec, registry.types))
    return result, store
