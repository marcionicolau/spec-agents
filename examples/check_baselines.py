"""Regression gate for the deterministic eval suites (no LLM, no proxy).

    python examples/check_baselines.py            # fail if a score dropped below baseline - tolerance
    python examples/check_baselines.py --update   # rewrite examples/evals/baselines.json (review the diff!)

Suites: ``planner_rules`` (the statistics rules planner, per-case scores: it is repo independent) and ``context``
(coworker context selection run on this repository, so only the means are tracked and the tolerance absorbs drift).
Live LLM evals stay manual: ``python examples/run_evals.py --mode live`` for PRs labelled ``stage:needs-eval``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # lets `examples.run_evals` be imported

from agent_fabric.evals import compare_baseline, load_baselines, save_baselines  # noqa: E402
from coworker_fabric.evals import load_cases as load_context_cases  # noqa: E402
from coworker_fabric.evals import run_cases  # noqa: E402
from examples.run_evals import evaluate  # noqa: E402

BASELINES = ROOT / "examples" / "evals" / "baselines.json"


def planner_rules() -> dict[str, float]:
    report = evaluate("statistics", "rules")
    return {"mean_score": report.mean_score, **{f"case:{r.name}": round(r.score, 4) for r in report.results}}


def context() -> dict[str, float]:
    cases = load_context_cases(ROOT / "examples" / "evals" / "context_cases.yaml")
    scores = run_cases(ROOT, cases, token_budget=6000, max_files=8, hops=1, relative_cutoff=0.5)
    n = len(scores)
    return {
        "mean_score": round(sum(s.score for s in scores) / n, 4),
        "mean_recall": round(sum(s.recall for s in scores) / n, 4),
    }


SUITES = {"planner_rules": planner_rules, "context": context}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--update", action="store_true", help="write the current scores as the new baseline")
    args = ap.parse_args()
    baselines = load_baselines(BASELINES)
    current = {name: fn() for name, fn in SUITES.items()}
    if args.update:
        baselines["suites"] = current
        baselines.setdefault("tolerance", 0.02)
        save_baselines(BASELINES, baselines)
        print(f"baselines written to {BASELINES.relative_to(ROOT)}")
        return
    failed = False
    for name, metrics in current.items():
        issues = compare_baseline(name, metrics, baselines)
        head = ", ".join(f"{k}={v:.3f}" for k, v in metrics.items() if not k.startswith("case:"))
        print(f"{name}: {head}")
        for i in issues:
            print(f"  {i}")
        failed |= any(i.severity in ("regression", "missing", "new") for i in issues)
    if failed:
        print(
            "eval baseline check FAILED (run with --update only if the change is intended; the diff is reviewed in the PR)"
        )
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
