"""Every failure is a typed ``FabricError``: a bad plan reports all its errors at once, each with ``loc`` and ``hint``."""

from __future__ import annotations

from agent_fabric import build_registry
from agent_fabric.errors import PlanValidationError
from agent_fabric.pipeline import parse_plan
from text_pack import register

registry = build_registry([register])
spec = registry.pipeline("document_digest")

try:
    parse_plan(spec.instantiate({"top_k": "three"}), registry)  # top_k must be an integer
except PlanValidationError as exc:
    print(exc.category, "recoverable" if exc.recoverable else "fatal")
    for detail in exc.details:  # all errors are collected before raising
        print(".".join(map(str, detail.loc)), detail.type, "->", detail.msg)
else:
    raise AssertionError("expected a PlanValidationError")
