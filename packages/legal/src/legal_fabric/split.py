"""Command line entry point: split a combined eproc download into one file per event (no LLM involved).

Usage: ``python -m legal_fabric.split <root> <out_dir> [--separator TEXT] [--lang pt-BR|en-US]``
"""

from __future__ import annotations

import argparse
import json
import sys

from agent_fabric import build_registry
from agent_fabric.errors import FabricError
from agent_fabric.executor import PipelineExecutor
from agent_fabric.pipeline import PipelineInputs, parse_plan

from .domain import register

__all__ = ["main", "split_eproc"]


def split_eproc(root: str, out_dir: str, *, separator: str | None = None, lang: str = "pt-BR") -> dict:
    """Run ``eproc_split`` as a one-step plan and return its result dict; raise the step error if it failed."""
    params = {"root": root, "out_dir": out_dir, "lang": lang}
    if separator is not None:
        params["separator"] = separator
    registry = build_registry([register])
    pin = PipelineInputs.from_values({}, registry.types)
    raw = {
        "objective": "split the eproc download",
        "steps": [{"id": "split", "component": "eproc_split", "params": params}],
        "outputs": {},
    }
    report = PipelineExecutor(registry).run(parse_plan(raw, registry, pin), pin)
    failed = next((o.error for o in report.outcomes if o.error is not None), None)
    if failed is not None:
        raise FabricError(failed.message, failed.details)
    result = report.outcomes[0].result
    return result.model_dump(mode="json") if hasattr(result, "model_dump") else dict(result)


def main() -> None:
    """Parse argv, run the split and print the result as JSON (exit 1 on failure)."""
    ap = argparse.ArgumentParser(prog="python -m legal_fabric.split", description=__doc__)
    ap.add_argument("root", help="folder holding the combined eproc download PDF(s)")
    ap.add_argument("out_dir", help="folder to write one EVENTO<n>_<CODE>.txt per event")
    ap.add_argument("--separator", default=None, help="marker text on eproc separator pages")
    ap.add_argument("--lang", default="pt-BR", choices=["pt-BR", "en-US"], help="language of warning text")
    args = ap.parse_args()
    try:
        result = split_eproc(args.root, args.out_dir, separator=args.separator, lang=args.lang)
    except FabricError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
