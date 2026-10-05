"""Generate a checked Airflow DAG that loads a CSV into bronze/silver/gold Iceberg tables (no model, no Airflow)."""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

from agent_fabric import build_registry
from agent_fabric.executor import PipelineExecutor
from agent_fabric.pipeline import PipelineInputs, parse_plan
from lake_fabric.domain import register

rows = [
    {"order_id": i, "order_date": f"2026-01-{i % 28 + 1:02d}", "region": ["north", "south"][i % 2], "amount": 10 + i}
    for i in range(1, 21)
]
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "orders.csv"
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    registry = build_registry([register])
    params = {
        "source": {"type": "csv", "path": str(path)},
        "dag_id": "ingest_orders",
        "catalog": "lake",
        "table": "orders",
        "business_keys": ["order_id"],
        "partition_column": "order_date",
        "gold_group_by": ["region"],
        "gold_measures": ["amount"],
    }
    inputs = PipelineInputs.from_values({}, registry.types)
    plan = parse_plan(registry.pipeline("ingest_to_lakehouse").instantiate(params), registry, inputs)
    report = PipelineExecutor(registry).run(plan, inputs)

assert report.ok, [o.error for o in report.outcomes if o.error]
out = report.output_values()
print({c["name"]: c["type"] for c in out["schema"]["columns"]})  # inferred column types
print(out["layout"]["sql"]["silver_load"][0][:60])  # MERGE INTO "lake"."silver"."orders" ...
compile(out["dag_code"], "ingest_orders.py", "exec")  # the generated DAG is valid Python
