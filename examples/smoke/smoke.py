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


def _run(fabric: AgentFabric, instruction: str, inputs: dict, session_id: str):
    """Run with the CLI's live view (agent board, step table, streamed model text).

    On a non-TTY (logs, CI) falls back to printing one line per event plus raw streamed text.
    """
    from rich.console import Console
    from rich.live import Live

    from agent_fabric.cli.live import RunView

    console = Console()
    if not console.is_terminal:
        return fabric.run(
            instruction,
            inputs,
            session_id=session_id,
            on_event=lambda e: print(f"[{e.event}] {e.path} {e.detail or ''}", flush=True),
            on_step=lambda o: print(
                f"[step] {o.step_id} {o.component} -> {o.status} ({o.duration_s:.2f}s)", flush=True
            ),
            on_delta=lambda p, t: print(t, end="", flush=True),
        )
    view = RunView(instruction)
    with Live(view.renderable(), console=console, refresh_per_second=10, transient=True) as live:
        return fabric.run(
            instruction,
            inputs,
            session_id=session_id,
            on_event=lambda e: live.update(view.on_event(e)),
            on_step=lambda o: live.update(view.on_step(o)),
            on_delta=lambda p, t: live.update(view.on_delta(p, t)),
        )


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
    report = _run(
        fabric,
        "Does the nitrogen treatment change wheat yield? Run a two-way ANOVA (treatment x cultivar) "
        "and summarise the trial first.",
        {"data": df},
        "smoke-anova",
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
    report = _run(
        fabric,
        f"In {SMOKE / 'tiny_repo'}, mean([]) crashes with ZeroDivisionError. "
        "Find the file, propose the smallest fix (raise ValueError with a clear message) and validate the patch.",
        {},
        "smoke-coworker",
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
    report = _run(
        fabric,
        "Digest this WhatsApp group conversation: what was decided and who owns what?",
        {"text": (SMOKE / "whatsapp_group.txt").read_text(encoding="utf-8")},
        "smoke-whatsapp",
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
