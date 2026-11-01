"""Analyse a criminal case with the legal pack: verified claims, a symbolic consistency check, a dossier.

``claim_extract`` is the only LLM step in ``analyse_case``; this script runs the rest of the pipeline for real and
substitutes fixed claims for it, so the example stays offline (see ``how-to/real-model`` to run it against a proxy).
"""

from __future__ import annotations

import os
import tempfile
import textwrap
from pathlib import Path

from agent_fabric import build_registry
from agent_fabric.executor import PipelineExecutor
from agent_fabric.pipeline import PipelineInputs, parse_plan
from legal_fabric.domain import register

CORPUS = Path(__file__).resolve().parent.parent.parent / "packages" / "legal" / "data" / "authorities.sample.jsonl"

DOCS = {
    "EVENTO1_DENUNCIA1.txt": """
        O MINISTÉRIO PÚBLICO oferece denúncia contra JOÃO DA SILVA
        como incurso nas sanções do art. 157, caput, do Código Penal.
    """,
    "EVENTO2_DEPOIM1.txt": """
        Termo de declarações perante o Delegado de Polícia.
        Vítima MARIA SOUZA declarou que o homem vestia camiseta vermelha.
    """,
    "EVENTO3_DEPOIM2.txt": """
        Termo de declarações perante o Delegado de Polícia.
        Policial JOSÉ LIMA declarou que o homem vestia camiseta azul.
    """,
}

# what the LLM step would extract, cited by document, page and line; the last quote is not in the record
CLAIMS = [
    {
        "id": "c1",
        "loc": "ev2/DEPOIM1 p.1 l.2",
        "quote": "o homem vestia camiseta vermelha",
        "speaker": "Maria Souza",
        "role": "vitima",
        "party": "acusacao",
        "facts": {"clothing": "camiseta vermelha"},
        "supports": ["autoria"],
    },
    {
        "id": "c2",
        "loc": "ev3/DEPOIM2 p.1 l.2",
        "quote": "o homem vestia camiseta azul",
        "speaker": "José Lima",
        "role": "policial",
        "party": "acusacao",
        "facts": {"clothing": "camiseta azul"},
        "supports": ["autoria"],
    },
    {
        "id": "c3",
        "loc": "ev2/DEPOIM1 p.1 l.1",
        "quote": "o réu confessou o roubo",
        "speaker": "Maria Souza",
        "role": "vitima",
        "party": "acusacao",
        "facts": {},
        "supports": ["autoria"],
    },
]

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    for name, body in DOCS.items():
        (root / name).write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")
    os.environ["LEGAL_ALLOWED_ROOTS"] = str(root)  # the pack only reads allowlisted roots

    registry = build_registry([register])
    pin = PipelineInputs.from_values({"claims": CLAIMS}, registry.types)
    plan = registry.pipeline("analyse_case").instantiate(
        {"root": str(root), "corpus_path": str(CORPUS), "case_id": "T1"}
    )
    plan["steps"] = [s for s in plan["steps"] if s["id"] != "extract"]  # drop claim_extract (the LLM step)
    for s in plan["steps"]:
        if s["id"] == "verify":
            s["inputs"]["claims"] = "$inputs.claims"  # feed the fixed claims straight into claim_verify
    report = PipelineExecutor(registry).run(parse_plan(plan, registry, pin), pin)

assert report.ok, [o.error for o in report.outcomes if o.error]
out = report.output_values()
print({r["reason"] for r in out["rejected"]})  # {'quote_not_found'}: c3's quote is nowhere in the record
anomalies = {a["rule"]: a["severity"] for a in out["dossier"]["anomalies"]}
print(anomalies)  # {'slot_conflict': 'high'}: the victim's two accounts of the clothing disagree
assert anomalies.get("slot_conflict") == "high"
