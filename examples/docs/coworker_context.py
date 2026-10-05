"""Pick the code context for a task inside a token budget with the coworker pack (read-only, writes nothing)."""

from __future__ import annotations

import os
import tempfile
import textwrap
from pathlib import Path

from agent_fabric import build_registry
from agent_fabric.executor import PipelineExecutor
from agent_fabric.pipeline import PipelineInputs, parse_plan
from coworker_fabric.domain import register

FILES = {
    "src/shop/__init__.py": "",
    "src/shop/orders.py": """
        from . import pricing


        def total(items):
            return pricing.apply(sum(i.price for i in items))
    """,
    "src/shop/pricing.py": """
        def apply(amount, rate=0.2):
            return amount * (1 + rate)
    """,
    "src/shop/unrelated.py": """
        class Weather:
            def forecast(self):
                return "sunny"
    """,
    "tests/test_orders.py": """
        from shop.orders import total

        def test_total():
            assert total([]) == 0
    """,
}

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    for rel, body in FILES.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(body).lstrip("\n"))
    os.environ["COWORKER_ALLOWED_ROOTS"] = str(root)  # the pack only reads allowlisted roots

    registry = build_registry([register])
    params = {"root": str(root), "task": "fix order totals", "focus_files": ["src/shop/orders.py"]}
    inputs = PipelineInputs.from_values({}, registry.types)
    plan = parse_plan(registry.pipeline("improve_code").instantiate(params), registry, inputs)
    report = PipelineExecutor(registry).run(plan, inputs)

assert report.ok, [o.error for o in report.outcomes if o.error]
selected = {s["path"]: s["reasons"] for s in report.by_id("pick").result["selected"]}
print(selected)  # focus file, its imports and its tests; "unrelated.py" is left out
assert "src/shop/unrelated.py" not in selected
