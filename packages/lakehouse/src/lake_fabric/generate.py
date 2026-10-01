"""Programmatic entry point: run the ``ingest_to_lakehouse`` pipeline and write the DAG file (no LLM involved)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agent_fabric import build_registry
from agent_fabric.errors import FabricError
from agent_fabric.executor import PipelineExecutor
from agent_fabric.pipeline import PipelineInputs, parse_plan

from .domain import register


def generate_dag(
    params: dict[str, Any], sample: Any = None, out_dir: str | Path | None = None, overwrite: bool = False
) -> dict[str, Any]:
    """Return ``{"dag_code", "layout", "schema", "path"}``; raise the first step error if any step failed.

    The file ``<out_dir>/<dag_id>.py`` is written only after ``dag_check`` passed, and an existing file is never
    replaced unless ``overwrite`` is true.
    """
    registry = build_registry([register])
    pin = PipelineInputs.from_values({"sample": sample} if sample is not None else {}, registry.types)
    plan = parse_plan(registry.pipeline("ingest_to_lakehouse").instantiate(params), registry, pin)
    report = PipelineExecutor(registry).run(plan, pin)
    failed = next((o.error for o in report.outcomes if o.error is not None), None)
    if failed is not None:
        raise FabricError(failed.message, failed.details)
    out = report.output_values()
    path = None
    if out_dir is not None:
        target = Path(out_dir) / f"{params['dag_id']}.py"
        if target.exists() and not overwrite:
            raise FileExistsError(f"{target} exists; pass overwrite=True to replace it")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(out["dag_code"], encoding="utf-8")
        path = str(target)
    return {**out, "path": path}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m lake_fabric.generate", description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "params",
        help="JSON file with the pipeline parameters: source {type, path|url, ...}, dag_id, catalog, table, business_keys, ...",
    )
    ap.add_argument("--sample", help="JSON file with example records (required for api and mcp sources)")
    ap.add_argument("--out", default="dags", help="directory for the generated DAG file")
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args(argv)
    sample = json.loads(Path(a.sample).read_text()) if a.sample else None
    try:
        res = generate_dag(json.loads(Path(a.params).read_text()), sample, a.out, a.overwrite)
    except FabricError as exc:
        print(f"ERROR {exc.message}", file=sys.stderr)
        for d in exc.details:
            print(f"  {'.'.join(map(str, d.loc))}: {d.msg}" + (f" ({d.hint})" if d.hint else ""), file=sys.stderr)
        sys.exit(1)
    print(res["path"])


if __name__ == "__main__":
    main()
