"""Legal domain: ingest, verification, symbolic consistency rules, argument map, authorities and rebuttal gate."""

import textwrap
from pathlib import Path

import pytest

from agent_fabric import build_registry
from agent_fabric.executor import PipelineExecutor
from agent_fabric.pipeline import PipelineInputs, parse_plan
from legal_fabric.domain import register

CORPUS = Path(__file__).resolve().parents[1] / "data" / "authorities.sample.jsonl"

DOCS = {
    "EVENTO1_DENUNCIA1.txt": """
        O MINISTÉRIO PÚBLICO oferece denúncia contra JOÃO DA SILVA
        como incurso nas sanções do art. 157, caput, do Código Penal,
        pelos fatos ocorridos na Rua das Flores.
    """,
    "EVENTO2_DEPOIM1.txt": """
        Termo de declarações prestadas perante o Delegado de Polícia.
        Vítima MARIA SOUZA declarou que por volta das 22h foi abordada
        por um homem que usava uma faca e vestia camiseta vermelha,
        que levou sua bolsa com o celular.
    """,
    "EVENTO3_DEPOIM2.txt": """
        Termo de declarações perante a autoridade policial.
        Policial JOSÉ LIMA declarou que abordou o suspeito às 23h30
        e que ele vestia camiseta azul e portava o celular da vítima.
    """,
    "EVENTO20_TERMOAUD1.txt": """
        Audiência de instrução, presente a Juíza de Direito.
        A vítima MARIA SOUZA disse que o homem estava com um revólver
        e que não tem certeza de que o réu é o autor.
    """,
    "EVENTO21_INTERROG1.txt": """
        Interrogatório em audiência de instrução perante a Juíza.
        O réu JOÃO DA SILVA disse que estava em casa com a mãe naquela noite.
    """,
}

CLAIMS = [
    {
        "id": "c1",
        "loc": "ev2/DEPOIM1 p.1 l.2-3",
        "quote": "por volta das 22h foi abordada por um homem que usava uma faca",
        "speaker": "Maria Souza",
        "role": "vitima",
        "party": "acusacao",
        "facts": {"time": "22h", "weapon": "faca", "clothing": "camiseta vermelha"},
        "supports": ["subtracao", "violencia_grave_ameaca", "autoria"],
    },
    {
        "id": "c2",
        "loc": "ev3/DEPOIM2 p.1 l.2-3",
        "quote": "abordou o suspeito às 23h30 e que ele vestia camiseta azul",
        "speaker": "José Lima",
        "role": "policial",
        "party": "acusacao",
        "facts": {"time": "23h30", "clothing": "camiseta azul"},
        "supports": ["autoria"],
    },
    {
        "id": "c3",
        "loc": "ev20/TERMOAUD1 p.1 l.2",
        "quote": "o homem estava com um revólver",
        "speaker": "Maria Souza",
        "role": "vitima",
        "party": "acusacao",
        "facts": {"weapon": "revólver"},
        "supports": ["violencia_grave_ameaca"],
    },
    {
        "id": "c4",
        "loc": "ev21/INTERROG1 p.1 l.2",
        "quote": "estava em casa com a mãe naquela noite",
        "speaker": "João da Silva",
        "role": "reu",
        "party": "defesa",
        "facts": {"place": "casa"},
        "supports": [],
    },
    {
        "id": "c5",
        "loc": "ev3/DEPOIM2 p.1 l.1",
        "quote": "o réu confessou o roubo na viatura",
        "speaker": "José Lima",
        "role": "policial",
        "party": "acusacao",
        "facts": {},
        "supports": ["autoria"],
    },
]


@pytest.fixture
def lg():
    return build_registry([register])


@pytest.fixture
def case_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LEGAL_ALLOWED_ROOTS", str(tmp_path))
    for name, body in DOCS.items():
        (tmp_path / name).write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")
    return tmp_path


def analyse(lg, case_dir):
    """`analyse_case` with the LLM extraction replaced by fixed claims (offline)."""
    pin = PipelineInputs.from_values({"claims": CLAIMS}, lg.types)
    plan = lg.pipeline("analyse_case").instantiate({"root": str(case_dir), "corpus_path": str(CORPUS), "case_id": "T1"})
    plan["steps"] = [s for s in plan["steps"] if s["id"] != "extract"]
    for s in plan["steps"]:
        if s["id"] == "verify":
            s["inputs"]["claims"] = "$inputs.claims"
    rep = PipelineExecutor(lg).run(parse_plan(plan, lg, pin), pin)
    assert rep.ok, [o.error for o in rep.outcomes if o.error]
    return rep.output_values()


def test_analysis_finds_the_expected_anomalies(lg, case_dir):
    out = analyse(lg, case_dir)
    d = out["dossier"]
    assert [c["charge_id"] for c in d["charges"]] == ["CP:157"]
    assert {r["reason"] for r in out["rejected"]} == {"quote_not_found"}  # c5 is not in the record
    rules = {a["rule"] for a in d["anomalies"]}
    assert {"retraction", "slot_conflict", "inquiry_only"} <= rules
    clothing = [a for a in d["anomalies"] if a["rule"] == "slot_conflict" and "'clothing'" in a["rationale"]]
    assert clothing and clothing[0]["severity"] == "high"  # red vs blue shirt bears on identification
    assert all(len(a["rationale"]) > 100 for a in d["anomalies"])
    assert any(p["side"] == "acusacao" and p["strength"] == "weak" for p in d["points"])
    assert any(a["id"] == "cpp-155" for v in d["authorities"].values() for a in v)


def test_rebuttal_gate(lg, case_dir):
    d = analyse(lg, case_dir)["dossier"]
    pid, _ = next((k, v) for k, v in d["authorities"].items() if any(a["id"] == "cpp-155" for a in v))
    why = (
        "Chose to attack this point because its only support comes from the inquiry phase and the victim changed "
        "the weapon in court, so the conviction would rest on material not confirmed under adversarial proceedings, "
        "which the selected authority excludes as an exclusive basis."
    )
    good = {
        "target_point_id": pid,
        "weakness": "only inquiry evidence",
        "counterargument": "x" * 30,
        "evidence": ["ev2/DEPOIM1 p.1 l.2-3"],
        "authorities": ["cpp-155"],
        "confidence": "high",
        "rationale": why,
    }
    bad = {**good, "evidence": ["ev2/DEPOIM1 p.9 l.1"], "authorities": ["stf-made-up"]}
    reb = {"case_id": "T1", "summary": "Draft rebuttal for review.", "points": [good, bad], "needs_research": []}
    pin = PipelineInputs.from_values({"rebuttal": reb, "dossier": d}, lg.types)
    plan = lg.pipeline("check_rebuttal").instantiate({})
    rep = PipelineExecutor(lg).run(parse_plan(plan, lg, pin), pin)
    assert rep.ok
    report = rep.output_values()["report"]
    assert len(report["accepted"]) == 1
    assert {r.split(":")[0] for r in report["rejected"][0]["reasons"]} == {"bad_locator", "authority_not_selected"}


@pytest.mark.parametrize(
    ("a", "b", "conflict"),
    [
        ("camiseta vermelha", "camiseta azul", True),
        ("faca", "revólver", True),
        ("camiseta", "camiseta azul", False),
        ("camisa vermelha", "camiseta vermelha", False),
    ],
)
def test_slot_conflict_words(a, b, conflict):
    from legal_fabric.ontology import slot_conflict

    assert slot_conflict("clothing", a, b, 30) is conflict
