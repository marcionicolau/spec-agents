"""Legal components for criminal procedure.

Ingest an eproc download, classify the charge, extract and verify claims, check consistency with symbolic rules, map strong/weak points, pick authorities and check a rebuttal.

Two invariants hold everywhere, enforced by code rather than by prompts:

* **every claim cites the record** - a canonical locator ``ev12/DEPOIM1 p.3 l.10-14`` that ``claim_verify`` and
  ``rebuttal_check`` resolve against the real text; anything that does not resolve is dropped with a reason;
* **every result explains itself** - anomalies, points, authorities and rebuttal points carry a ``rationale``
  paragraph saying why that path was chosen.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_fabric.artifacts import ArtifactType
from agent_fabric.component import Component, ComponentParams, ComponentResult, StepContext
from agent_fabric.errors import ErrorDetail
from agent_fabric.registry import component

from . import i18n
from .i18n import Lang
from .ontology import (
    _LAW_CODES,
    ARTICLE_RE,
    CRIMES,
    INQUIRY_MARKERS,
    JUDICIAL_MARKERS,
    KIND_MAP,
    KIND_PHASE,
    fmt_loc,
    load_crimes,
    norm,
    parse_loc,
    slot_conflict,
    tokens,
)
from .schemas import Rebuttal

ROOTS_ENV = "LEGAL_ALLOWED_ROOTS"
_FNAME = re.compile(r"(?:ev(?:ento)?[_ -]?(?P<ev>\d+))?[_ -]*(?P<code>[A-Za-z]+?)(?P<n>\d*)$", re.I)


# ============================================================================ artifact type: case
class CaseProfile(BaseModel):
    case_id: str
    n_docs: int
    kinds: dict[str, int]

    def to_prompt(self) -> str:
        """One line for planners: case id and documents per kind (never the text itself)."""
        return f"case {self.case_id}: {self.n_docs} documents {self.kinds}"


class CaseArtifact(ArtifactType):
    """Artifact type ``case``: the paginated, line-numbered record emitted by ``process_ingest``.

    Narrower than ``json`` so a plan can only bind a real case into ``case`` ports (plan-time self-correction).
    """

    name = "case"
    python_types = (dict,)
    specificity = 2

    def accepts(self, value: Any) -> bool:
        """Only dicts shaped like a case, so a dossier or rebuttal is never inferred as ``case``."""
        return isinstance(value, dict) and "case_id" in value and isinstance(value.get("docs"), list)

    def profile(self, value: dict) -> CaseProfile:
        """Summarise a case: id and how many documents of each kind it holds."""
        kinds = Counter(d.get("kind", "outro") for d in value.get("docs", []))
        return CaseProfile(case_id=str(value.get("case_id", "")), n_docs=len(value.get("docs", [])), kinds=dict(kinds))

    def runtime_check(self, value: dict, constraints: BaseModel, params: BaseModel, loc: tuple) -> list[ErrorDetail]:
        """A case needs ``case_id`` and at least one document with pages."""
        if not value.get("case_id") or not value.get("docs"):
            return [
                ErrorDetail(loc=loc, type="not_a_case", msg="expected {case_id, docs}", hint="bind process_ingest.case")
            ]
        return []


def _allowed(root: Path) -> bool:
    raw = os.environ.get(ROOTS_ENV)
    roots = [Path(r).resolve() for r in raw.split(os.pathsep) if r] if raw else [Path.cwd().resolve()]
    return any(root.is_relative_to(r) for r in roots)


def _doc_index(case: dict) -> dict[str, dict]:
    return {d["doc_id"]: d for d in case["docs"]}


def _lines(doc: dict, page: int, a: int, b: int, pad: int = 0) -> str | None:
    pages = doc["pages"]
    if not 1 <= page <= len(pages):
        return None
    lines = pages[page - 1]
    if not (1 <= a <= b <= len(lines)):
        return None
    return " ".join(lines[max(0, a - 1 - pad) : min(len(lines), b + pad)])


def _partial_ratio(quote: str, text: str) -> float:
    q, t = norm(quote), norm(text)
    if not q:
        return 0.0
    if q in t:
        return 1.0
    if len(t) <= len(q):
        return SequenceMatcher(None, q, t).ratio()
    step = max(1, len(q) // 4)
    return max(SequenceMatcher(None, q, t[i : i + len(q)]).ratio() for i in range(0, len(t) - len(q) + 1, step))


# ============================================================================ process_ingest
class ProcessIngestParams(ComponentParams):
    root: str
    case_id: str | None = None
    kind_map: dict[str, str] = Field(default_factory=dict, description="extra eproc code -> kind entries")
    phases: dict[str, Literal["inquerito", "judicial", "pericial"]] = Field(default_factory=dict)
    max_docs: int = Field(500, ge=1, le=5000)
    lang: Lang = Field("pt-BR", description="language of warning text")


class ProcessIngestResult(ComponentResult):
    case_id: str
    n_docs: int
    n_pages: int
    kinds: dict[str, int]
    phases: dict[str, int]


@component("process_ingest")
class ProcessIngest(Component[ProcessIngestParams, ProcessIngestResult]):
    Params = ProcessIngestParams
    Result = ProcessIngestResult

    def extra_checks(self, inputs: dict, params: ProcessIngestParams) -> list[ErrorDetail]:
        root = Path(params.root)
        if not root.is_dir():
            return [ErrorDetail(loc=("params", "root"), type="root_not_found", msg=f"{root} is not a directory")]
        if not _allowed(root.resolve()):
            return [
                ErrorDetail(
                    loc=("params", "root"),
                    type="root_not_allowed",
                    msg="outside the allowed roots",
                    hint=f"set {ROOTS_ENV} (os.pathsep-separated) to the folders holding case downloads",
                )
            ]
        return []

    def compute(self, inputs: dict, params: ProcessIngestParams, ctx: StepContext) -> ProcessIngestResult:
        """Read an eproc download (one PDF or TXT per document) into a paginated, line-numbered ``case``.

        File names like ``EVENTO12_DEPOIM1.pdf`` give the event and the document code; the code maps to a kind and the
        kind (or, for testimony, the text) to a phase: ``inquerito``, ``judicial`` or ``pericial``. TXT pages are split
        on form feeds. Emits the ``case`` output.
        """
        root = Path(params.root).resolve()
        kmap = {**KIND_MAP, **{k.upper(): v for k, v in params.kind_map.items()}}
        warns: list[str] = []
        files = sorted(p for p in root.rglob("*") if p.suffix.lower() in {".pdf", ".txt"} and p.is_file())
        if len(files) > params.max_docs:
            warns.append(i18n.too_many_documents(params.lang, len(files), params.max_docs))
            files = files[: params.max_docs]
        docs: list[dict[str, Any]] = []
        for path in files:
            pages = self._pages(path, warns, params.lang)
            if pages is None:
                continue
            m = _FNAME.search(path.stem)
            code = (m["code"] if m else path.stem).upper()
            event = int(m["ev"]) if m and m["ev"] else 0
            doc_id = f"ev{event}/{code}{m['n'] if m else ''}"
            kind = next((v for k, v in sorted(kmap.items(), key=lambda kv: -len(kv[0])) if code.startswith(k)), "outro")
            phase = params.phases.get(doc_id) or KIND_PHASE.get(kind) or self._phase_from_text(pages)
            if phase == "desconhecida":
                warns.append(i18n.phase_not_recognised(params.lang, doc_id))
            docs.append(
                {
                    "doc_id": doc_id,
                    "event": event,
                    "code": code,
                    "kind": kind,
                    "phase": phase,
                    "path": path.relative_to(root).as_posix(),
                    "pages": pages,
                }
            )
        ctx.emit("case", {"case_id": params.case_id or root.name, "docs": docs})
        return ProcessIngestResult(
            case_id=params.case_id or root.name,
            n_docs=len(docs),
            n_pages=sum(len(d["pages"]) for d in docs),
            kinds=dict(Counter(d["kind"] for d in docs)),
            phases=dict(Counter(d["phase"] for d in docs)),
            warnings=warns,
        )

    @staticmethod
    def _pages(path: Path, warns: list[str], lang: Lang) -> list[list[str]] | None:
        if path.suffix.lower() == ".txt":
            raw = path.read_text(encoding="utf-8", errors="replace").split("\f")
        else:
            try:
                from pypdf import PdfReader
            except ImportError:
                warns.append(i18n.pypdf_missing(lang, path.name))
                return None
            raw = [pg.extract_text() or "" for pg in PdfReader(path).pages]
            if not any(r.strip() for r in raw):
                warns.append(i18n.no_text_layer(lang, path.name))
                return None
        return [[ln.rstrip() for ln in page.splitlines()] for page in raw]

    @staticmethod
    def _phase_from_text(pages: list[list[str]]) -> str:
        text = norm(" ".join(" ".join(p) for p in pages[:2]))
        if any(m in text for m in JUDICIAL_MARKERS):
            return "judicial"
        if any(m in text for m in INQUIRY_MARKERS):
            return "inquerito"
        return "desconhecida"


# ============================================================================ crime_classify
class CrimeClassifyParams(ComponentParams):
    source_kinds: list[str] = Field(default_factory=lambda: ["denuncia"], min_length=1)
    articles: list[str] = Field(default_factory=list, description="manual charges, e.g. ['CP:157']")
    crimes_path: str | None = Field(None, description="crimes YAML override; the packaged ontology when unset")
    lang: Lang = Field("pt-BR", description="language of rationale and warning text")


class CrimeClassifyResult(ComponentResult):
    charges: list[str]
    unknown: list[str]


@component("crime_classify")
class CrimeClassify(Component[CrimeClassifyParams, CrimeClassifyResult]):
    Params = CrimeClassifyParams
    Result = CrimeClassifyResult

    def extra_checks(self, inputs: dict, params: CrimeClassifyParams) -> list[ErrorDetail]:
        if params.crimes_path is None:
            return []
        try:
            load_crimes(params.crimes_path)
        except FileNotFoundError:
            return [
                ErrorDetail(
                    loc=("params", "crimes_path"),
                    type="crimes_not_found",
                    msg=f"{params.crimes_path} does not exist",
                    hint="a YAML file of crime types and elements, see data/crimes.yaml for the format",
                )
            ]
        except ValueError as exc:
            return [ErrorDetail(loc=("params", "crimes_path"), type="crimes_invalid", msg=str(exc))]
        return []

    def compute(self, inputs: dict, params: CrimeClassifyParams, ctx: StepContext) -> CrimeClassifyResult:
        """Find the charged articles (tipo penal) in the accusation and expand them into elements to prove.

        Scans documents of ``source_kinds`` for article citations of the Penal Code or Lei 11.343, keeps where each was
        found, and looks every article up in the ontology (the packaged ``data/crimes.yaml``, or ``crimes_path``).
        Emits the ``charges`` output.
        """
        crimes = load_crimes(params.crimes_path) if params.crimes_path else CRIMES
        found: dict[str, list[str]] = defaultdict(list)
        for doc in inputs["case"]["docs"]:
            if doc["kind"] not in params.source_kinds:
                continue
            for p, lines in enumerate(doc["pages"], 1):
                for i in range(1, len(lines) + 1):
                    window = " ".join(lines[i - 1 : i + 1])
                    for m in ARTICLE_RE.finditer(window):
                        law = next(code for rx, code in _LAW_CODES if rx.search(m["law"]))
                        found[f"{law}:{m['art']}"].append(fmt_loc(doc["doc_id"], p, i))
        for art in params.articles:
            found.setdefault(art, [])
        warns: list[str] = []
        if not found:
            warns.append(i18n.no_charges_found(params.lang))
        charges, unknown = [], []
        for key, locs in found.items():
            info = crimes.get(key)
            if info is None:
                unknown.append(key)
                warns.append(i18n.unknown_charge(params.lang, key))
            locs = sorted(set(locs))
            charges.append(
                {
                    "charge_id": key,
                    "name": (info or {}).get("name", key),
                    "elements": (info or {}).get("elements", []),
                    "found_at": locs,
                    "rationale": i18n.charge_rationale(params.lang, key, locs),
                }
            )
        ctx.emit("charges", charges)
        return CrimeClassifyResult(charges=[c["charge_id"] for c in charges], unknown=unknown, warnings=warns)


# ============================================================================ evidence_segment
class EvidenceSegmentParams(ComponentParams):
    kinds: list[str] = Field(
        default_factory=lambda: [
            "depoimento",
            "interrogatorio",
            "audiencia",
            "reconhecimento",
            "laudo",
            "apreensao",
            "boletim",
            "denuncia",
            "defesa",
            "alegacoes",
        ]
    )
    max_chars: int = Field(60000, ge=2000, le=400000)
    lang: Lang = Field("pt-BR", description="language of rationale and warning text")


class EvidenceSegmentResult(ComponentResult):
    n_docs: int
    n_chars: int
    left_out: list[str]


@component("evidence_segment")
class EvidenceSegment(Component[EvidenceSegmentParams, EvidenceSegmentResult]):
    Params = EvidenceSegmentParams
    Result = EvidenceSegmentResult

    def compute(self, inputs: dict, params: EvidenceSegmentParams, ctx: StepContext) -> EvidenceSegmentResult:
        """Render the evidence documents as a line-numbered bundle the extractor can cite from.

        Every line is prefixed with ``[p.N l.M]`` under a ``### <doc_id>`` header, and the element ids of the charges
        are listed first so claims can say which element they support. Emits the ``bundle`` output.
        """
        elements = sorted({e["id"] for c in inputs["charges"] for e in c["elements"]})
        out = ["ELEMENTOS: " + ", ".join(elements), ""]
        size, used, left = sum(map(len, out)), 0, []
        for doc in inputs["case"]["docs"]:
            if doc["kind"] not in params.kinds:
                continue
            block = [f"### {doc['doc_id']} ({doc['kind']}, fase: {doc['phase']})"]
            for p, lines in enumerate(doc["pages"], 1):
                block += [f"[p.{p} l.{i}] {ln}" for i, ln in enumerate(lines, 1) if ln.strip()]
            text = "\n".join(block) + "\n"
            if size + len(text) > params.max_chars:
                left.append(doc["doc_id"])
                continue
            out.append(text)
            size, used = size + len(text), used + 1
        warns = [i18n.evidence_left_out(params.lang, len(left), left[:5])] if left else []
        bundle = "\n".join(out)
        ctx.emit("bundle", bundle)
        return EvidenceSegmentResult(n_docs=used, n_chars=len(bundle), left_out=left, warnings=warns)


# ============================================================================ claim_verify
class ClaimIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    loc: str
    quote: str = Field(min_length=8)
    speaker: str
    role: Literal["vitima", "testemunha", "policial", "reu", "perito", "documento"]
    party: Literal["acusacao", "defesa", "neutro"] = "neutro"
    about: str = "fato"
    facts: dict[str, str] = Field(default_factory=dict)
    supports: list[str] = Field(default_factory=list)


class ClaimVerifyParams(ComponentParams):
    min_similarity: float = Field(0.85, ge=0.5, le=1.0)
    line_slack: int = Field(1, ge=0, le=3)
    lang: Lang = Field("pt-BR", description="language of rationale and warning text")


class ClaimVerifyResult(ComponentResult):
    n_verified: int
    n_rejected: int
    reasons: dict[str, int]


@component("claim_verify")
class ClaimVerify(Component[ClaimVerifyParams, ClaimVerifyResult]):
    Params = ClaimVerifyParams
    Result = ClaimVerifyResult

    def compute(self, inputs: dict, params: ClaimVerifyParams, ctx: StepContext) -> ClaimVerifyResult:
        """Quality control: keep only claims whose quote really is at the cited document, page and lines.

        Resolves each locator against the case, compares the quote with those lines (allowing ``line_slack`` lines of
        drift) and requires ``min_similarity``. Verified claims gain ``kind`` and ``phase`` of their document. Emits
        ``verified`` and ``rejected`` (each rejection with its reason).
        """
        raw = inputs["claims"]
        raw = raw.get("claims", []) if isinstance(raw, dict) else raw
        docs = _doc_index(inputs["case"])
        verified, rejected = [], []
        for item in raw:
            try:
                c = ClaimIn.model_validate(item)
            except ValidationError as exc:
                rejected.append({"claim": item, "reason": "bad_shape", "detail": str(exc.errors()[0]["msg"])})
                continue
            loc = parse_loc(c.loc)
            if loc is None or loc[0] not in docs:
                rejected.append({"claim": item, "reason": "bad_locator", "detail": c.loc})
                continue
            doc_id, page, a, b = loc
            text = _lines(docs[doc_id], page, a, b, pad=params.line_slack)
            if text is None:
                rejected.append({"claim": item, "reason": "out_of_range", "detail": c.loc})
                continue
            score = _partial_ratio(c.quote, text)
            if score < params.min_similarity:
                rejected.append({"claim": item, "reason": "quote_not_found", "detail": f"similarity {score:.2f}"})
                continue
            doc = docs[doc_id]
            verified.append({**c.model_dump(), "kind": doc["kind"], "phase": doc["phase"], "match": round(score, 2)})
        warns = []
        if raw and len(rejected) / len(raw) > 0.3:
            warns.append(i18n.claims_citing_loosely(params.lang, len(rejected), len(raw)))
        ctx.emit("verified", verified)
        ctx.emit("rejected", rejected)
        return ClaimVerifyResult(
            n_verified=len(verified),
            n_rejected=len(rejected),
            reasons=dict(Counter(r["reason"] for r in rejected)),
            warnings=warns,
        )


# ============================================================================ consistency_check
class ConsistencyCheckParams(ComponentParams):
    time_tolerance_min: int = Field(30, ge=0, le=240)
    outlier_z: float = Field(1.5, ge=0.5, le=4.0)
    identity_slots: list[str] = Field(default_factory=lambda: ["actor", "weapon", "clothing"])
    lang: Lang = Field("pt-BR", description="language of rationale and warning text")


class ConsistencyCheckResult(ComponentResult):
    n_anomalies: int
    by_rule: dict[str, int]
    outlier_speakers: list[str]


@component("consistency_check")
class ConsistencyCheck(Component[ConsistencyCheckParams, ConsistencyCheckResult]):
    Params = ConsistencyCheckParams
    Result = ConsistencyCheckResult

    def compute(self, inputs: dict, params: ConsistencyCheckParams, ctx: StepContext) -> ConsistencyCheckResult:
        """Neuro-symbolic consistency check: the LLM extracted the facts, these rules judge them.

        Rules: ``slot_conflict`` (two speakers disagree on a fact), ``retraction`` (one speaker changes version between
        inquiry and court), ``missing_element``, ``inquiry_only`` (an element rests only on inquiry evidence) and
        ``single_source``. Speakers whose conflict count is a z-score outlier are flagged as well. Emits ``anomalies``.
        """
        claims, charges = inputs["claims"], inputs["charges"]
        out: list[dict[str, Any]] = []
        conflicts_by_speaker: Counter[str] = Counter()

        def add(rule: str, severity: str, ids: list[str], locs: list[str], rationale: str, element: str | None = None):
            out.append(
                {
                    "id": f"a{len(out) + 1}",
                    "rule": rule,
                    "severity": severity,
                    "element": element,
                    "claims": ids,
                    "locators": locs,
                    "rationale": rationale,
                }
            )

        by_about: dict[str, list[dict]] = defaultdict(list)
        for c in claims:
            by_about[c["about"]].append(c)
        for about, group in by_about.items():
            for i, x in enumerate(group):
                for y in group[i + 1 :]:
                    for slot in sorted(set(x["facts"]) & set(y["facts"])):
                        if not slot_conflict(slot, x["facts"][slot], y["facts"][slot], params.time_tolerance_min):
                            continue
                        same = norm(x["speaker"]) == norm(y["speaker"])
                        if same and x["phase"] != y["phase"]:
                            add(
                                "retraction",
                                "high",
                                [x["id"], y["id"]],
                                [x["loc"], y["loc"]],
                                i18n.retraction_rationale(
                                    params.lang,
                                    x["speaker"],
                                    slot,
                                    about,
                                    x["facts"][slot],
                                    x["phase"],
                                    x["loc"],
                                    y["facts"][slot],
                                    y["phase"],
                                    y["loc"],
                                ),
                            )
                        elif not same:
                            sev = "high" if slot in params.identity_slots else "medium"
                            conflicts_by_speaker.update([x["speaker"], y["speaker"]])
                            add(
                                "slot_conflict",
                                sev,
                                [x["id"], y["id"]],
                                [x["loc"], y["loc"]],
                                i18n.slot_conflict_rationale(
                                    params.lang,
                                    x["speaker"],
                                    x["role"],
                                    x["loc"],
                                    x["facts"][slot],
                                    y["speaker"],
                                    y["role"],
                                    y["loc"],
                                    y["facts"][slot],
                                    slot,
                                    about,
                                    sev,
                                ),
                            )

        for ch in charges:
            for el in ch["elements"]:
                sup = [c for c in claims if el["id"] in c["supports"] and c["party"] != "defesa"]
                ids, locs = [c["id"] for c in sup], [c["loc"] for c in sup]
                if not sup:
                    add(
                        "missing_element",
                        "high",
                        [],
                        [],
                        element=el["id"],
                        rationale=i18n.missing_element_rationale(
                            params.lang, el["label"], ch["charge_id"], el["proof_hint"]
                        ),
                    )
                    continue
                phases = {c["phase"] for c in sup}
                if phases <= {"inquerito"}:
                    add(
                        "inquiry_only",
                        "high",
                        ids,
                        locs,
                        element=el["id"],
                        rationale=i18n.inquiry_only_rationale(params.lang, el["label"], locs),
                    )
                speakers = {norm(c["speaker"]) for c in sup if c["role"] != "documento"}
                if len(speakers) == 1 and "pericial" not in phases:
                    who = sup[0]
                    add(
                        "single_source",
                        "medium",
                        ids,
                        locs,
                        element=el["id"],
                        rationale=i18n.single_source_rationale(
                            params.lang, el["label"], who["speaker"], who["role"], locs
                        ),
                    )

        outliers: list[str] = []
        if len(conflicts_by_speaker) >= 3:
            vals = list(conflicts_by_speaker.values())
            mu, sd = mean(vals), pstdev(vals) or 1.0
            outliers = [s for s, v in conflicts_by_speaker.items() if (v - mu) / sd >= params.outlier_z]
            for s in outliers:
                add(
                    "outlier_speaker",
                    "medium",
                    [],
                    [],
                    rationale=i18n.outlier_speaker_rationale(params.lang, s, conflicts_by_speaker[s], mu),
                )
        ctx.emit("anomalies", out)
        return ConsistencyCheckResult(
            n_anomalies=len(out), by_rule=dict(Counter(a["rule"] for a in out)), outlier_speakers=outliers
        )


# ============================================================================ argument_map
class ArgumentMapParams(ComponentParams):
    min_speakers_strong: int = Field(2, ge=1, le=5)
    lang: Lang = Field("pt-BR", description="language of rationale and warning text")


class ArgumentMapResult(ComponentResult):
    n_points: int
    strong: int
    weak: int
    refutation_targets: list[str]


@component("argument_map")
class ArgumentMap(Component[ArgumentMapParams, ArgumentMapResult]):
    Params = ArgumentMapParams
    Result = ArgumentMapResult

    def compute(self, inputs: dict, params: ArgumentMapParams, ctx: StepContext) -> ArgumentMapResult:
        """Turn claims and anomalies into strong and weak points for each side.

        One accusation point per charge element (strong when it has judicial evidence from ``min_speakers_strong``
        speakers and no high-severity anomaly), one defence point per anomaly or defence claim. Weak accusation points
        become ``refutation_targets``. Emits ``points``.
        """
        claims, charges, anomalies = inputs["claims"], inputs["charges"], inputs["anomalies"]
        points: list[dict[str, Any]] = []
        targets: list[str] = []
        for ch in charges:
            for el in ch["elements"]:
                sup = [c for c in claims if el["id"] in c["supports"] and c["party"] != "defesa"]
                against = [
                    a for a in anomalies if a["element"] == el["id"] or set(a["claims"]) & {c["id"] for c in sup}
                ]
                judicial = [c for c in sup if c["phase"] in {"judicial", "pericial"}]
                speakers = {norm(c["speaker"]) for c in judicial}
                high = [a for a in against if a["severity"] == "high"]
                strong = len(speakers) >= params.min_speakers_strong and not high
                pid = f"P{len(points) + 1}"
                points.append(
                    {
                        "point_id": pid,
                        "side": "acusacao",
                        "element": el["id"],
                        "charge": ch["charge_id"],
                        "statement": f"{el['label']} ({ch['name']})",
                        "strength": "strong" if strong else "weak",
                        "evidence": [c["loc"] for c in sup],
                        "anomalies": [a["id"] for a in against],
                        "rationale": i18n.accusation_point_rationale(
                            params.lang, strong, len(speakers), params.min_speakers_strong, [a["rule"] for a in high]
                        ),
                    }
                )
                if not strong:
                    targets.append(pid)
        for a in anomalies:
            target = next((p["point_id"] for p in points if a["id"] in p["anomalies"]), None)
            points.append(
                {
                    "point_id": f"P{len(points) + 1}",
                    "side": "defesa",
                    "element": a["element"],
                    "charge": None,
                    "statement": f"{a['rule']}: {a['rationale'][:140]}",
                    "anomaly": a["id"],
                    "attacks": target,
                    "strength": "strong" if a["severity"] == "high" else "weak",
                    "evidence": a["locators"],
                    "rationale": i18n.defence_point_from_anomaly_rationale(
                        params.lang, a["id"], a["rule"], a["severity"], a["rationale"]
                    ),
                }
            )
        for c in (c for c in claims if c["party"] == "defesa"):
            corr = [
                o
                for o in claims
                if o["id"] != c["id"]
                and o["about"] == c["about"]
                and o["party"] == "defesa"
                and norm(o["speaker"]) != norm(c["speaker"])
            ]
            points.append(
                {
                    "point_id": f"P{len(points) + 1}",
                    "side": "defesa",
                    "element": None,
                    "charge": None,
                    "statement": c["quote"][:160],
                    "strength": "strong" if corr else "weak",
                    "evidence": [c["loc"]] + [o["loc"] for o in corr],
                    "rationale": i18n.defence_point_from_claim_rationale(
                        params.lang, c["speaker"], c["loc"], len(corr)
                    ),
                }
            )
        ctx.emit("points", points)
        return ArgumentMapResult(
            n_points=len(points),
            strong=sum(p["strength"] == "strong" for p in points),
            weak=sum(p["strength"] == "weak" for p in points),
            refutation_targets=targets,
        )


# ============================================================================ authority_select
class AuthoritySelectParams(ComponentParams):
    corpus_path: str
    top_k: int = Field(3, ge=1, le=10)
    min_score: float = Field(1.0, ge=0.0)
    lang: Lang = Field("pt-BR", description="language of rationale and warning text")


class AuthoritySelectResult(ComponentResult):
    n_authorities: int
    covered_points: int
    needs_research: list[str]


def _bm25(query: set[str], docs: list[set[str]], k1: float = 1.5, b: float = 0.75) -> list[float]:
    n = len(docs)
    avg = sum(map(len, docs)) / max(n, 1)
    df = Counter(w for d in docs for w in d)
    out = []
    for d in docs:
        s = 0.0
        for w in query & d:
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            s += idf * (k1 + 1) / (1 + k1 * (1 - b + b * len(d) / avg))
        out.append(s)
    return out


@component("authority_select")
class AuthoritySelect(Component[AuthoritySelectParams, AuthoritySelectResult]):
    Params = AuthoritySelectParams
    Result = AuthoritySelectResult

    def extra_checks(self, inputs: dict, params: AuthoritySelectParams) -> list[ErrorDetail]:
        if not Path(params.corpus_path).is_file():
            return [
                ErrorDetail(
                    loc=("params", "corpus_path"),
                    type="corpus_not_found",
                    msg=f"{params.corpus_path} does not exist",
                    hint="a JSONL file of curated authorities",
                )
            ]
        return []

    def compute(self, inputs: dict, params: AuthoritySelectParams, ctx: StepContext) -> AuthoritySelectResult:
        """Pick laws and precedents from a curated local corpus for every defence point and weak accusation point.

        Ranks authorities with BM25 over their text and tags (a tag equal to the point's rule is a strong match).
        Confidence is ``high`` for binding authorities above ``min_score``, ``medium`` above it, otherwise the point is
        listed in ``needs_research``: no counter-argument is allowed without an authority. Emits ``authorities``.
        """
        corpus = [
            json.loads(ln) for ln in Path(params.corpus_path).read_text(encoding="utf-8").splitlines() if ln.strip()
        ]
        bags = [tokens(f"{a['ref']} {a['text']}") | set(a.get("tags", [])) for a in corpus]
        picked: dict[str, list[dict]] = {}
        needs: list[str] = []
        for p in inputs["points"]:
            if p["side"] == "acusacao" and p["strength"] == "strong":
                continue
            rule = p["statement"].split(":")[0] if p["side"] == "defesa" else "elemento"
            q = tokens(p["statement"]) | {rule, p.get("element") or ""}
            scores = _bm25(q, bags)
            ranked = sorted(zip(scores, corpus, strict=True), key=lambda t: -t[0])[: params.top_k]
            keep = []
            for score, a in ranked:
                if score < params.min_score:
                    continue
                conf = "high" if a.get("binding") else "medium"
                keep.append(
                    {
                        "id": a["id"],
                        "ref": a["ref"],
                        "court": a.get("court"),
                        "binding": bool(a.get("binding")),
                        "score": round(score, 2),
                        "confidence": conf,
                        "rationale": i18n.authority_rationale(
                            params.lang,
                            a["ref"],
                            p["point_id"],
                            sorted(q & bags[corpus.index(a)]),
                            score,
                            conf,
                            bool(a.get("binding")),
                        ),
                    }
                )
            if keep:
                picked[p["point_id"]] = keep
            else:
                needs.append(p["point_id"])
        ctx.emit("authorities", picked)
        warns = [i18n.needs_research_warning(params.lang, needs)] if needs else []
        return AuthoritySelectResult(
            n_authorities=len({a["id"] for v in picked.values() for a in v}),
            covered_points=len(picked),
            needs_research=needs,
            warnings=warns,
        )


# ============================================================================ dossier_build
class DossierBuildParams(ComponentParams):
    lang: Lang = Field("pt-BR", description="language the rebuttal writer is instructed to answer in")


class DossierBuildResult(ComponentResult):
    case_id: str
    n_points: int
    n_refutable: int


@component("dossier_build")
class DossierBuild(Component[DossierBuildParams, DossierBuildResult]):
    Params = DossierBuildParams
    Result = DossierBuildResult

    def compute(self, inputs: dict, params: DossierBuildParams, ctx: StepContext) -> DossierBuildResult:
        """Bundle everything the rebuttal writer and the checker need into one ``dossier`` (no document text).

        Holds charges, verified claims, anomalies, points, authorities per point and the page sizes of every
        document, so ``rebuttal_check`` can resolve locators without the case. Emits ``dossier``.
        """
        case = inputs["case"]
        auth = inputs["authorities"]
        dossier = {
            "case_id": case["case_id"],
            # "rules" comes early: prompt serialisation (compact()) truncates long dossiers from the tail, and a
            # truncated-away rule (notably the language directive) is worse than one the model reads out of order.
            "rules": [
                "cite every statement with a locator from the evidence lists",
                "use only authority ids listed for the point you answer",
                "give each point one rationale paragraph saying why this line of argument was chosen",
                i18n.writer_language_directive(params.lang),
            ],
            "charges": inputs["charges"],
            "claims": inputs["claims"],
            "anomalies": inputs["anomalies"],
            "points": inputs["points"],
            "authorities": auth,
            "page_sizes": {d["doc_id"]: [len(p) for p in d["pages"]] for d in case["docs"]},
        }
        ctx.emit("dossier", dossier)
        return DossierBuildResult(
            case_id=case["case_id"],
            n_points=len(inputs["points"]),
            n_refutable=sum(1 for k in auth if any(p["point_id"] == k for p in inputs["points"])),
        )


# ============================================================================ rebuttal_check
class RebuttalCheckParams(ComponentParams):
    min_rationale_chars: int = Field(200, ge=50, le=2000)
    max_rationale_chars: int = Field(1500, ge=200, le=5000)
    lang: Lang = Field("pt-BR", description="language of warning text")


class RebuttalCheckResult(ComponentResult):
    n_accepted: int
    n_rejected: int
    reasons: dict[str, int]


@component("rebuttal_check")
class RebuttalCheck(Component[RebuttalCheckParams, RebuttalCheckResult]):
    Params = RebuttalCheckParams
    Result = RebuttalCheckResult

    def compute(self, inputs: dict, params: RebuttalCheckParams, ctx: StepContext) -> RebuttalCheckResult:
        """Gate the rebuttal: every point must resolve its locators, use only its point's authorities and explain itself.

        Rejects points whose target is unknown, whose locators do not exist in the record, which cite an authority not
        selected for that point, which assert a counter-argument with no authority, or whose rationale is not one
        paragraph of ``min_rationale_chars`` to ``max_rationale_chars``. Emits ``report`` (accepted + rejected).
        """
        dossier = inputs["dossier"]
        try:
            reb = Rebuttal.model_validate(inputs["rebuttal"])
        except ValidationError as exc:
            report = {"accepted": [], "rejected": [{"point": None, "reasons": ["bad_shape: " + str(exc.errors()[0])]}]}
            ctx.emit("report", report)
            return RebuttalCheckResult(n_accepted=0, n_rejected=1, reasons={"bad_shape": 1})
        points = {p["point_id"]: p for p in dossier["points"]}
        sizes = dossier["page_sizes"]
        accepted, rejected = [], []
        for rp in reb.points:
            why: list[str] = []
            if rp.target_point_id not in points:
                why.append("unknown_target")
            for loc in rp.evidence:
                pl = parse_loc(loc)
                ok = (
                    pl is not None
                    and pl[0] in sizes
                    and 1 <= pl[1] <= len(sizes[pl[0]])
                    and pl[3] <= sizes[pl[0]][pl[1] - 1]
                )
                if not ok:
                    why.append(f"bad_locator:{loc}")
            allowed = {a["id"] for a in dossier["authorities"].get(rp.target_point_id, [])}
            if not rp.authorities:
                why.append("no_authority")
            why += [f"authority_not_selected:{a}" for a in rp.authorities if a not in allowed]
            r = rp.rationale.strip()
            if "\n\n" in r or not (params.min_rationale_chars <= len(r) <= params.max_rationale_chars):
                why.append("rationale_not_one_paragraph")
            (rejected.append({"point": rp.model_dump(), "reasons": why}) if why else accepted.append(rp.model_dump()))
        reasons = Counter(w.split(":")[0] for r in rejected for w in r["reasons"])
        warns = [i18n.rebuttal_rejected_warning(params.lang, len(rejected))] if rejected else []
        ctx.emit(
            "report",
            {"case_id": reb.case_id, "accepted": accepted, "rejected": rejected, "needs_research": reb.needs_research},
        )
        return RebuttalCheckResult(
            n_accepted=len(accepted), n_rejected=len(rejected), reasons=dict(reasons), warnings=warns
        )
