"""Prompt templates. Short and explicit for 7-14B local models; JSON-only answers."""

from __future__ import annotations

import json
from typing import Any

PLANNER_SYSTEM = """You design data-processing pipelines. You never compute results yourself:
you choose components from a fixed catalogue, fill their parameters and wire their ports.

Rules:
- Use ONLY components, parameter names and port names from the catalogue. Unknown fields are rejected.
- Refer to data with references: "$inputs.<name>" for pipeline inputs, "<step_id>.<output>" for outputs of earlier steps.
- An input port with the same name as a pipeline input is bound automatically; you may omit it.
- Use ONLY column names that exist in the input descriptions, with the right kind.
- Step ids are short, unique snake_case. At most {max_steps} steps.
- Reply with ONE JSON object and nothing else:
{{"objective": "...", "steps": [{{"id": "...", "component": "...", "params": {{}}, "inputs": {{}}, "rationale": "..."}}], "outputs": {{}}}}"""

PLANNER_USER = """Objective: {objective}

Pipeline inputs:
{inputs}

Component catalogue (JSON):
{catalog}
{memory}"""

INTERPRETER_SYSTEM = """You interpret the result of one pipeline step for a domain expert.
Rules:
- Use only numbers that appear in the result JSON (rounding and % are fine).
- Put every warning that affects conclusions in 'caveats'.
- headline <= 25 words; 1-6 findings, one sentence each.
- Reply with ONE JSON object:
{"step_id": "...", "headline": "...", "findings": ["..."], "caveats": ["..."], "confidence": "high|medium|low"}"""

INTERPRETER_USER = """Objective: {objective}
Step id: {step_id}
Component: {component} - {title}
How to interpret this component:
{focus}
Parameters: {params}
Result JSON:
{result}"""

REPAIR_SYSTEM = """You fix the parameters of ONE pipeline step that failed validation.
Use only parameter names from the schema and only values consistent with the inputs.
Reply with ONE JSON object: {"params": {...}} containing the complete corrected parameters."""

REPAIR_USER = """Component: {component}
Parameter schema: {schema}
Inputs:
{inputs}
Current params: {params}
Error report:
{error}
{pitfalls}"""

PROMPT_STEP_SYSTEM = """You are one step inside a deterministic pipeline. Do the task in the user message,
nothing else. Rules:
- Use only the information given in the message; do not invent facts, files, paths or numbers.
- {output_rule}"""

PROMPT_STEP_OUTPUT_TEXT = "Reply with the answer text only, no JSON, no preamble."
PROMPT_STEP_OUTPUT_JSON = (
    "Reply with ONE JSON object and nothing else. It must contain exactly these keys (extra keys are ignored): {ports}"
)

# ------------------------------------------------------------------ agents

AGENT_SYSTEM = """You are {role}.
Goal: {goal}
{backstory}"""

WORKER_JSON_RULES = """Reply with ONE JSON object that matches this JSON schema (no prose):
{schema}"""

ROUTER_RULES = """You coordinate a team of sub-agents. Break the task into delegations.
Sub-agents available (use these names exactly):
{team}

Blackboard keys you may pass as inputs: {keys}
A delegation may also use the output of an earlier delegation by putting "@<delegation_id>" in its inputs.
Use at most {max_delegations} delegations. Reply with ONE JSON object:
{{"rationale": "...", "delegations": [{{"id": "d1", "agent": "<name>", "instruction": "...", "inputs": [], "depends_on": []}}]}}"""

SYNTHESIS_RULES = """Combine the sub-agent results below into the final answer for the task.
Use only facts and numbers present in the results. Mention failures explicitly."""


def compact(obj: Any, max_items: int = 12, max_chars: int = 6000) -> str:
    """Truncate long lists/dicts so content fits a small context window."""

    def trim(o: Any) -> Any:
        if isinstance(o, dict):
            items = list(o.items())
            out = {str(k): trim(v) for k, v in items[:max_items]}
            if len(items) > max_items:
                out["..."] = f"{len(items) - max_items} more"
            return out
        if isinstance(o, (list, tuple)):
            out = [trim(v) for v in list(o)[:max_items]]
            if len(o) > max_items:
                out.append(f"... {len(o) - max_items} more")
            return out
        if isinstance(o, float):
            return float(f"{o:.6g}")
        if isinstance(o, (str, int, bool)) or o is None:
            return o
        return f"<{type(o).__name__}>"

    text = json.dumps(trim(obj), ensure_ascii=False)
    return text if len(text) <= max_chars else text[: max_chars - 20] + ' ..."[truncated]"'
