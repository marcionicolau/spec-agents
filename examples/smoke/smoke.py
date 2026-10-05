"""Live smoke tests against Ollama through the LiteLLM proxy — one per domain pack.

Prerequisites (local workstation, CPU only):
    ollama pull qwen2.5:7b-instruct
    export OLLAMA_API_BASE=http://localhost:11434 LITELLM_MASTER_KEY=sk-local-dev
    litellm --config examples/smoke/litellm_qwen25.yaml --port 4000   # all aliases -> qwen2.5:7b-instruct

Usage:
    uv run python examples/smoke/smoke.py anova       # statistics pack: ANOVA on anova_trial.csv
    uv run python examples/smoke/smoke.py coworker    # coworker pack: patch a bug in tiny_repo/
    uv run python examples/smoke/smoke.py whatsapp    # text pack: digest a WhatsApp group export

Every run writes build/smoke/<case>.{md,json,jsonl} (report, machine dump, event trace).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "examples" / "smoke"
sys.path.insert(0, str(ROOT))

from agent_fabric import build_registry  # noqa: E402
from agent_fabric.agents import AgentFabric, AgentsConfig  # noqa: E402
from agent_fabric.report import render_markdown  # noqa: E402
from agent_fabric.trace import write_jsonl  # noqa: E402


def _schemas(fabric: AgentFabric, schemas: dict) -> AgentFabric:
    for name, model in schemas.items():
        fabric.register_schema(name, model)
    return fabric


def _write(report, name: str) -> None:
    out = ROOT / "build" / "smoke"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.md").write_text(render_markdown(report), encoding="utf-8")
    (out / f"{name}.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    write_jsonl(report.trace, out / f"{name}.jsonl")
    print(report.result.tree())
    print("usage:", report.usage)


def anova() -> None:
    """statistics: statistician plans summary + anova + time_series over the trial CSV."""
    import pandas as pd

    from stat_fabric.domain import register as register_stats
    from stat_fabric.schemas import SCHEMAS
    from text_pack import register as register_text

    df = pd.read_csv(SMOKE / "anova_trial.csv", parse_dates=["date"])
    fabric = _schemas(
        AgentFabric(
            build_registry([register_stats, register_text]),
            AgentsConfig.load(ROOT / "examples" / "research_team"),
        ),
        SCHEMAS,
    )
    report = fabric.run(
        "Does the nitrogen treatment change wheat yield? Run a two-way ANOVA (treatment x cultivar) "
        "and summarise the trial first.",
        {"data": df},
        session_id="smoke-anova",
    )
    _write(report, "anova")


def coworker() -> None:
    """coworker: pair_programmer indexes tiny_repo, selects context and proposes a validated patch.

    Watch `patch_propose`'s validation closely — a malformed `context` input must produce a located
    FabricError, never a bare KeyError/TypeError (golden rule 4).
    """
    from coworker_fabric.domain import register as register_coworker
    from coworker_fabric.schemas import SCHEMAS

    fabric = _schemas(
        AgentFabric(
            build_registry([register_coworker]),
            AgentsConfig.load(ROOT / "packages" / "coworker" / "config"),
        ),
        SCHEMAS,
    )
    report = fabric.run(
        f"In {SMOKE / 'tiny_repo'}, mean([]) crashes with ZeroDivisionError. "
        "Find the file, propose the smallest fix (raise ValueError with a clear message) and validate the patch.",
        {},
        session_id="smoke-coworker",
    )
    _write(report, "coworker")


def whatsapp() -> None:
    """text pack: notes_digest (document_digest pipeline) over a WhatsApp group export."""
    from stat_fabric.domain import register as register_stats
    from stat_fabric.schemas import SCHEMAS
    from text_pack import register as register_text

    fabric = _schemas(
        AgentFabric(
            build_registry([register_stats, register_text]),
            AgentsConfig.load(ROOT / "examples" / "research_team"),
        ),
        SCHEMAS,
    )
    report = fabric.run(
        "Digest this WhatsApp group conversation: what was decided and who owns what?",
        {"text": (SMOKE / "whatsapp_group.txt").read_text(encoding="utf-8")},
        session_id="smoke-whatsapp",
    )
    _write(report, "whatsapp")


CASES = {"anova": anova, "coworker": coworker, "whatsapp": whatsapp}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case", choices=CASES)
    args = ap.parse_args()
    CASES[args.case]()


if __name__ == "__main__":
    main()
