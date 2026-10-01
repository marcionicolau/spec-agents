"""End-to-end demo of the hierarchical agent tree in examples/research_team/ (fabric.md + agents/*/AGENT.md).

    python examples/run_demo.py --mode scripted   # simulated small-model mistakes -> self-correction at every level
    python examples/run_demo.py --mode offline    # proxy "down": router -> rules, planner -> stats_rules
    python examples/run_demo.py --mode live       # LiteLLM proxy :4000 -> Ollama
    python examples/run_demo.py --mode crew       # same tree mapped onto a hierarchical CrewAI crew

For day-to-day runs prefer the CLI (live view on a terminal):

    agent-fabric run examples/research_team "How do nitrogen treatments affect yield?" --input notes=notes.txt
    agent-fabric run examples/notes "Digest this meeting" --input transcript=meeting.txt   # code-free domain
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_fabric import build_registry  # noqa: E402
from agent_fabric.agents import AgentFabric, AgentsConfig  # noqa: E402
from agent_fabric.errors import DependencyError, ErrorDetail  # noqa: E402
from agent_fabric.llm import ScriptedBackend  # noqa: E402
from agent_fabric.report import render_markdown  # noqa: E402
from stat_fabric.domain import register as register_stats  # noqa: E402
from stat_fabric.schemas import SCHEMAS  # noqa: E402
from text_pack import register as register_text  # noqa: E402

QUESTION = (
    "How do nitrogen treatments, soil nutrients and rainfall affect wheat yield, and what do the field notes add?"
)
NOTES = (
    "Field notes 2026. Plots under the N120 nitrogen treatment tillered earlier and kept greener canopies. "
    "October rainfall delayed phosphorus uptake in low-pH plots. Wheat grain filling looked uniform across blocks."
)


def make_data(n: int = 120, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    d = pd.DataFrame(
        {
            "date": pd.date_range("2016-01-01", periods=n, freq="MS").strftime("%Y-%m-%d"),
            "treatment": rng.choice(["control", "N60", "N120"], n),
            "nitrogen": rng.normal(40, 8, n),
            "phosphorus": rng.normal(20, 4, n),
            "potassium": rng.normal(60, 10, n),
            "ph": rng.normal(5.8, 0.3, n),
            "rainfall": rng.gamma(4, 40, n),
        }
    )
    d["phosphorus"] += 0.3 * d["nitrogen"]
    eff = d["treatment"].map({"control": 0, "N60": 0.4, "N120": 0.8})
    d["yield_t_ha"] = (
        2
        + 0.02 * d["nitrogen"]
        + 0.002 * d["rainfall"]
        + eff
        + 0.3 * np.sin(np.arange(n) / 12 * 2 * np.pi)
        + rng.normal(0, 0.25, n)
    )
    return d


GOOD_PLAN = {
    "objective": "yield drivers",
    "steps": [
        {"id": "summary", "component": "summary"},
        {"id": "anova", "component": "anova", "params": {"response": "yield_t_ha", "factors": ["treatment"]}},
        {
            "id": "model",
            "component": "linear_model",
            "params": {"response": "yield_t_ha", "predictors": ["nitrogen", "rainfall", "treatment"]},
        },
        {
            "id": "trend",
            "component": "time_series",
            "params": {"time_col": "date", "value_col": "yield_t_ha", "horizon": 6},
        },
    ],
}


def scripted_backend() -> ScriptedBackend:
    """Typical 7-8B mistakes at each level of the tree, then the fixes."""
    route_bad = {"delegations": [{"id": "d1", "agent": "statistics", "instruction": "analyse", "inputs": ["dataset"]}]}
    route_ok = {
        "rationale": "tabular question for the stats team, profile in parallel, notes to the digester",
        "delegations": [
            {
                "id": "stats",
                "agent": "stats_team",
                "instruction": "Quantify treatment, nutrient and rainfall effects on yield",
                "inputs": ["data"],
            },
            {
                "id": "profile",
                "agent": "profile_runner",
                "instruction": "Profile plots by soil variables",
                "inputs": ["data"],
            },
            {"id": "notes", "agent": "notes_digest", "instruction": "Digest the field notes", "inputs": ["notes"]},
        ],
    }
    plan_bad = json.loads(json.dumps(GOOD_PLAN))
    plan_bad["steps"][1]["params"]["factors"] = ["nitrogen"]  # numeric used as factor
    plan_bad["steps"][2]["params"]["response"] = "yield"  # hallucinated column
    review_bad = {"verdict": "sound", "summary": "R2 = 0.9876, an excellent fit", "issues": []}  # ungrounded number
    review_ok = {
        "verdict": "caveats",
        "summary": "Effects are credible but residuals show autocorrelation",
        "issues": ["residual autocorrelation in the linear model", "check seasonality before forecasting"],
    }
    return ScriptedBackend(
        [
            "I will ask the statistics team.",  # router: prose
            json.dumps(route_bad),
            json.dumps(route_ok),  # router: bad names -> fixed
            "```json\n" + json.dumps(plan_bad) + "\n```",
            json.dumps(GOOD_PLAN),  # planner: fixed
            json.dumps(review_bad),
            json.dumps(review_ok),  # reviewer: grounding fix
            "Nitrogen treatment is the dominant driver of yield; rainfall adds a smaller effect. "
            "Field notes agree (earlier tillering under N120). Residual autocorrelation calls for caution.",
        ]
    )


class DownBackend:
    def complete(self, *a, **k):
        raise DependencyError("LiteLLM proxy is unreachable", [ErrorDetail(type="connection_error", msg="refused")])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["scripted", "offline", "live", "crew"], default="scripted")
    ap.add_argument("--out", default=str(ROOT / "examples" / "output"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    registry = build_registry([register_stats, register_text])
    config = AgentsConfig.load(ROOT / "examples" / "research_team")
    backend = {"scripted": scripted_backend(), "offline": DownBackend()}.get(args.mode)
    fabric = AgentFabric(registry, config, backend=backend)
    for name, model in SCHEMAS.items():
        fabric.register_schema(name, model)
    inputs = {"data": make_data(), "notes": NOTES}

    if args.mode == "crew":
        from agent_fabric.integrations.crewai import build_crew

        crew, _ctx = build_crew(fabric, QUESTION, inputs)
        print(crew.kickoff())
        return

    report = fabric.run(QUESTION, inputs, session_id="demo")
    md = render_markdown(report)
    (out / f"report_{args.mode}.md").write_text(md, encoding="utf-8")
    (out / f"report_{args.mode}.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(report.result.tree())
    print("usage:", report.usage)


if __name__ == "__main__":
    main()
