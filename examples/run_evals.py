"""Planner regression evals (see agent_fabric.evals).

python examples/run_evals.py --mode rules   # deterministic baseline (stats_rules), no LLM
python examples/run_evals.py --mode live    # the 'statistician' agent's planner via the LiteLLM proxy
python examples/run_evals.py --domain lakehouse --mode live   # 'dag_engineer' (packages/lakehouse/config)
python examples/run_evals.py --domain coworker --mode live    # 'context_scout' (packages/coworker/config)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # lets `examples.run_demo` be imported

from agent_fabric import build_registry  # noqa: E402
from agent_fabric.agents import AgentsConfig  # noqa: E402
from agent_fabric.evals import evaluate_planner, load_cases  # noqa: E402
from agent_fabric.llm import LiteLLMProxyBackend, LLMPlanner  # noqa: E402
from agent_fabric.pipeline import PipelineInputs  # noqa: E402
from examples.run_demo import make_data  # noqa: E402
from stat_fabric.rules import StatsRulePlanner  # noqa: E402

DOMAINS = {  # name -> (register callable path, agents dir, planner agent, cases file)
    "statistics": ("stat_fabric.domain", "examples/research_team", "statistician", "planner_cases.yaml"),
    "lakehouse": ("lake_fabric.domain", "packages/lakehouse/config", "dag_engineer", "lakehouse_cases.yaml"),
    "coworker": ("coworker_fabric.domain", "packages/coworker/config", "context_scout", "coworker_cases.yaml"),
}


def evaluate(domain: str = "statistics", mode: str = "rules"):
    """Run one planner eval suite; ``rules`` needs no LLM (statistics only)."""
    import importlib

    module, agents_dir, agent, cases_file = DOMAINS[domain]
    if domain != "statistics" and mode != "live":
        sys.exit(f"the {domain} domain has no rules planner; use --mode live")
    registry = build_registry([importlib.import_module(module).register])
    cases = load_cases(ROOT / "examples" / "evals" / cases_file)
    for c in cases:
        c.objective = c.objective.replace("{root}", str(ROOT))
    types = registry.types
    if domain == "statistics":
        inputs = {"trial": PipelineInputs.from_values({"data": make_data()}, types)}
    else:
        inputs = {
            "none": PipelineInputs.from_values({}, types),
            "records": PipelineInputs.from_values({"sample": [{"id": i, "name": f"n{i}"} for i in range(25)]}, types),
        }
    if mode == "live":
        cfg = AgentsConfig.load(ROOT / agents_dir)
        planner = LLMPlanner(LiteLLMProxyBackend(cfg.llm), registry, cfg.llm, cfg.agents[agent].domains)
    else:
        planner = StatsRulePlanner(registry)
    return evaluate_planner(planner, cases, inputs)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["rules", "live"], default="rules")
    ap.add_argument("--domain", choices=list(DOMAINS), default="statistics")
    args = ap.parse_args()
    report = evaluate(args.domain, args.mode)
    print(report.table())
    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
