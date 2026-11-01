"""Legal domain: ingest, verification, symbolic consistency rules, argument map, authorities and rebuttal gate."""

import json
import textwrap
from pathlib import Path

import pytest

from agent_fabric import build_registry
from agent_fabric.agents import AgentFabric, AgentsConfig
from agent_fabric.executor import PipelineExecutor
from agent_fabric.llm import ScriptedBackend
from agent_fabric.pipeline import PipelineInputs, parse_plan
from legal_fabric.domain import register
from legal_fabric.schemas import SCHEMAS

CORPUS = Path(__file__).resolve().parents[1] / "data" / "authorities.sample.jsonl"
CONFIG = Path(__file__).resolve().parents[1] / "config"

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


def test_full_tree_quality_controller_receives_dossier_and_rebuttal(lg, case_dir):
    """Two real wiring bugs, both in how case_counsel's router hands sub-agent results to each other, not in any
    pipeline tested directly elsewhere - only a full agent-tree run exercises them.

    1. ``@d1``/``@d2`` always resolve to the *wrapper* result of a delegation (its own per-step status summary),
       never to one of its declared pipeline outputs - which, for a planner or pipeline agent, lives separately at
       ``<path>.<name>``. ``rebuttal_writer`` was never actually seeing analyse_case's dossier through ``@d1``, only
       case_analyst's step-status summary - it drafted blind, which is why it kept inventing authority ids and
       numbers the grounding check then rejected. Fixed with a static `inputs` on rebuttal_writer's AGENT.md
       pointing at ``case_counsel/case_analyst.dossier`` directly, bypassing ``@d1`` for this agent entirely.
    2. quality_controller's two json inputs (dossier, rebuttal) are ambiguous by both name and type once neither
       sub-agent's bare wrapper matches either declared name - fixed with ``options.input_map`` pointing each one
       at the exact key that holds it (case_analyst's needs the ``.dossier`` suffix for the reason above;
       rebuttal_writer's does not, since a plain llm agent's one artifact already is its output).

    Runs the whole tree with a ScriptedBackend to catch a regression in either mapping, or in the shape
    case_analyst's own plan or rebuttal_writer's own output must have, end to end.
    """
    full_plan = lg.pipeline("analyse_case").instantiate(
        {"root": str(case_dir), "corpus_path": str(CORPUS), "case_id": "T1"}
    )
    dossier = analyse(lg, case_dir)["dossier"]
    pid, _ = next((k, v) for k, v in dossier["authorities"].items() if any(a["id"] == "cpp-155" for a in v))

    delegation_plan = json.dumps(
        {
            "rationale": "analyse, then draft, then check",
            "delegations": [
                {"id": "d1", "agent": "case_analyst", "instruction": "Analise o caso.", "inputs": [], "depends_on": []},
                {
                    "id": "d2",
                    "agent": "rebuttal_writer",
                    "instruction": "Redija a réplica.",
                    "inputs": [],
                    "depends_on": ["d1"],
                },
                {
                    "id": "d3",
                    "agent": "quality_controller",
                    "instruction": "Verifique a réplica.",
                    "inputs": ["@d1", "@d2"],
                    "depends_on": ["d1", "d2"],
                },
            ],
        }
    )
    rebuttal = json.dumps(
        {
            "case_id": "T1",
            "summary": "Rebuttal draft for the lawyer to review.",
            "points": [
                {
                    "target_point_id": pid,
                    "weakness": "x" * 15,
                    "counterargument": "x" * 30,
                    "evidence": ["ev2/DEPOIM1 p.1 l.2-3"],
                    "authorities": ["cpp-155"],
                    "confidence": "high",
                    "rationale": "y" * 210,
                }
            ],
            "needs_research": [],
        }
    )
    backend = ScriptedBackend(
        [
            delegation_plan,  # case_counsel's own plan
            json.dumps(full_plan),  # case_analyst's plan: analyse_case, claim_extract included
            json.dumps({"claims": CLAIMS}),  # claim_extract
            rebuttal,  # rebuttal_writer
            "Draft para revisão do advogado. Nada foi protocolado.",  # case_counsel's final synthesis
        ]
    )
    fabric = AgentFabric(build_registry([register]), AgentsConfig.load(CONFIG), backend=backend)
    for name, model in SCHEMAS.items():
        fabric.register_schema(name, model)

    report = fabric.run(f"Defesa: analise o caso em {case_dir}. Corpus em {CORPUS}.", {})
    tree = report.result.tree()
    assert report.result.status == "ok", tree
    assert "quality_controller [pipeline] ok" in tree, tree


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


def test_argument_map_anomaly_matching_no_point(lg):
    """A second anomaly that matches no accusation point (e.g. outlier_speaker, which targets no element) must
    not KeyError once a defence point from an earlier anomaly already exists in `points` - defence points have no
    "anomalies" key (only "anomaly", singular), and the lookup searches the whole list built so far, defence
    points included. Direct, minimal repro: two anomalies are enough, no need to coax consistency_check into a
    real outlier_speaker (it needs 3+ conflicting speakers) just to exercise this code path.
    """
    charges = [
        {"charge_id": "CP:157", "name": "Roubo", "elements": [{"id": "subtracao", "label": "x", "proof_hint": "y"}]}
    ]
    claims = [
        {
            "id": "c1",
            "loc": "ev1/X p.1 l.1",
            "speaker": "A",
            "role": "testemunha",
            "party": "acusacao",
            "phase": "judicial",
            "about": "fato",
            "facts": {},
            "supports": ["subtracao"],
        }
    ]
    anomalies = [
        {
            "id": "a1",
            "rule": "missing_element",
            "severity": "high",
            "element": "subtracao",
            "claims": [],
            "locators": [],
            "rationale": "r" * 210,
        },
        {
            "id": "a2",
            "rule": "outlier_speaker",
            "severity": "medium",
            "element": None,
            "claims": [],
            "locators": [],
            "rationale": "r" * 210,
        },
    ]
    pin = PipelineInputs.from_values({"claims": claims, "charges": charges, "anomalies": anomalies}, lg.types)
    plan = {
        "objective": "test argument_map with an unmatched anomaly",
        "steps": [
            {
                "id": "map",
                "component": "argument_map",
                "inputs": {"claims": "$inputs.claims", "charges": "$inputs.charges", "anomalies": "$inputs.anomalies"},
            }
        ],
        "outputs": {"points": "map.points"},
    }
    report = PipelineExecutor(lg).run(parse_plan(plan, lg, pin), pin)
    assert report.ok, [o.error for o in report.outcomes if o.error]
    points = report.output_values()["points"]
    by_anomaly = {p["anomaly"]: p["attacks"] for p in points if p["side"] == "defesa"}
    assert by_anomaly["a1"] == "P1"  # matched the accusation point for 'subtracao'
    assert by_anomaly["a2"] is None  # outlier_speaker-like anomaly: no element, matches nothing - not an error


# synthetic page text mirroring the real eproc separator-page format (fictional content, not a real case)
SYNTHETIC_VOLUME = [
    "Capa: Parte 1",
    "PÁGINA DE SEPARAÇÃO\n(Gerada automaticamente pelo sistema.)\nEvento 1\nDISTRIBUIDO POR DEPENDENCIA",
    "MINISTÉRIO PÚBLICO\nDENÚNCIA\nO Ministério Público denuncia o réu fictício por furto.",
    "PÁGINA DE SEPARAÇÃO\n(Gerada automaticamente pelo sistema.)\nEvento 2\nALTERADA A SITUACAO DA PARTE",
    "PÁGINA DE SEPARAÇÃO\n(Gerada automaticamente pelo sistema.)\nEvento 3\nRECEBIDA A DENUNCIA",
    "Poder Judiciário\nDESPACHO/DECISÃO\nVistos, etc. A denúncia atende aos requisitos formais.",
    "PÁGINA DE SEPARAÇÃO\n(Gerada automaticamente pelo sistema.)\nEvento 4\nARQUIVOS NAO CONVERTIDOS",
    "",
]


def test_split_eproc_pages():
    from legal_fabric.ontology import split_eproc_pages

    result = split_eproc_pages(SYNTHETIC_VOLUME)
    assert [(e.event, e.code) for e in result.events] == [(1, "DENUNCIA"), (3, "DESPACHO")]
    assert result.n_no_document == 1  # evento 2: a pure docket movement, no attached document
    assert result.n_no_text == 1  # evento 4: a page with nothing extractable (e.g. a media placeholder)


def test_eproc_split_component(monkeypatch, tmp_path):
    pytest.importorskip("pypdf")
    import pypdf

    class _FakePage:
        def __init__(self, text):
            self._text = text

        def extract_text(self):
            return self._text

    class _FakeReader:
        def __init__(self, _path):
            self.pages = [_FakePage(t) for t in SYNTHETIC_VOLUME]

    monkeypatch.setattr(pypdf, "PdfReader", _FakeReader)
    monkeypatch.setenv("LEGAL_ALLOWED_ROOTS", str(tmp_path))
    (tmp_path / "download").mkdir()
    (tmp_path / "download" / "PARTE_1.pdf").write_bytes(b"")  # content is irrelevant: PdfReader is faked above
    out_dir = tmp_path / "split"

    registry = build_registry([register])
    pin = PipelineInputs.from_values({}, registry.types)
    plan = {
        "objective": "split a combined eproc download",
        "steps": [
            {
                "id": "split",
                "component": "eproc_split",
                "params": {"root": str(tmp_path / "download"), "out_dir": str(out_dir)},
            }
        ],
        "outputs": {},
    }
    report = PipelineExecutor(registry).run(parse_plan(plan, registry, pin), pin)
    assert report.ok, [o.error for o in report.outcomes if o.error]
    result = report.outcomes[0].result
    assert result["n_written"] == 2
    assert result["by_code"] == {"DENUNCIA": 1, "DESPACHO": 1}
    assert result["n_no_document"] == 1
    assert result["n_no_text"] == 1
    assert sorted(p.name for p in out_dir.iterdir()) == ["EVENTO1_DENUNCIA.txt", "EVENTO3_DESPACHO.txt"]

    # process_ingest reads eproc_split's output unchanged, with no code changes
    plan2 = {
        "objective": "ingest the split folder",
        "steps": [{"id": "ingest", "component": "process_ingest", "params": {"root": str(out_dir), "case_id": "T2"}}],
        "outputs": {"case": "ingest.case"},
    }
    report2 = PipelineExecutor(registry).run(parse_plan(plan2, registry, pin), pin)
    assert report2.ok, [o.error for o in report2.outcomes if o.error]
    docs = {d["doc_id"]: d for d in report2.output_values()["case"]["docs"]}
    assert docs["ev1/DENUNCIA"]["kind"] == "denuncia"
    assert docs["ev3/DESPACHO"]["kind"] == "despacho"
    assert docs["ev3/DESPACHO"]["phase"] == "judicial"
