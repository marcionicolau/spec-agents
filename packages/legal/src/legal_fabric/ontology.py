"""Small criminal-law ontology and the deterministic helpers that read it.

Everything here is data or pure functions: crime types (tipos penais) with their elements (elementares), document
kinds of an eproc download, procedural phases, locators and slot normalisers used by the consistency rules.
Extend ``KIND_MAP`` for your practice; extend crime types by editing ``data/crimes.yaml`` (or a copy pointed to by
``crime_classify``'s ``crimes_path`` param) — a lawyer can do both without touching this file.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

# ----------------------------------------------------------------------------- crime types
DEFAULT_CRIMES_PATH = Path(__file__).resolve().parent / "data" / "crimes.yaml"


class CrimeElement(BaseModel):
    """One element (elementar) of a crime type, from a crimes YAML's ``elements`` list."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    proof_hint: str = ""


class CrimeType(BaseModel):
    """One crime type (tipo penal), from a crimes YAML entry keyed ``"<LAW>:<ARTICLE>"`` (e.g. ``"CP:157"``)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    elements: list[CrimeElement] = Field(min_length=1)


def load_crimes(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Crime ontology (charge key -> name and elements) from a YAML file; the packaged ``data/crimes.yaml`` when ``path`` is ``None``.

    See ``data/crimes.yaml`` for the format and for the only law prefixes (``CP``, ``L11343``) `crime_classify`
    recognises in free text; other laws still work given by hand in its ``articles`` param. Raises ``ValueError``
    listing every malformed entry, so a lawyer's typo is reported all at once rather than crashing mid-analysis.
    """
    raw = yaml.safe_load(Path(path or DEFAULT_CRIMES_PATH).read_text(encoding="utf-8")) or {}
    out: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for key, value in raw.items():
        try:
            out[key] = CrimeType.model_validate(value).model_dump()
        except ValidationError as exc:
            errors.append(f"{key}: {exc}")
    if errors:
        raise ValueError("invalid crimes file " + str(path or DEFAULT_CRIMES_PATH) + ":\n" + "\n".join(errors))
    return out


CRIMES: dict[str, dict[str, Any]] = load_crimes()

_LAW_CODES = (
    (re.compile(r"\bC(?:P\b|[óo]digo\s+Penal)", re.I), "CP"),
    (re.compile(r"Lei\s*(?:n[º°o.]*\s*)?11\.?343", re.I), "L11343"),
)
ARTICLE_RE = re.compile(
    r"art(?:igo)?s?\.?\s*(?P<art>\d{1,3})(?P<tail>[^.;\n]{0,60}?)(?P<law>\bC(?:P\b|[óo]digo\s+Penal)|Lei\s*(?:n[º°o.]*\s*)?11\.?343)",
    re.I,
)

# ----------------------------------------------------------------------------- documents and phases
# eproc document codes (the label after the event number, e.g. EVENTO12_DEPOIM1.pdf). Adjust to your court.
# despacho/decisao/mandado/certidao/oficio/peticao/alvara/recurso were confirmed from a real TJRS eproc download
# (see eproc_split): they are procedural, not evidentiary, but real and common - most "events" in a download are
# docket movements like these, not evidence.
KIND_MAP: dict[str, str] = {
    "DENUNCIA": "denuncia",
    "INQ": "inquerito",
    "IP": "inquerito",
    "BO": "boletim",
    "DEPOIM": "depoimento",
    "TERMOAUD": "audiencia",
    "INTERROG": "interrogatorio",
    "LAUDO": "laudo",
    "AUTOAPREENS": "apreensao",
    "APREENS": "apreensao",
    "RECONH": "reconhecimento",
    "RESPOSTA": "defesa",
    "ALEGFINAIS": "alegacoes",
    "SENT": "sentenca",
    "DESPACHO": "despacho",
    "DECISAO": "despacho",
    "MANDADO": "mandado",
    "CERTIDAO": "certidao",
    "OFICIO": "oficio",
    "PETICAO": "peticao",
    "ALVARA": "alvara",
    "RECURSO": "recurso",
}
# phase of a document kind; None = decide from the text (a depoimento can be police or court testimony)
KIND_PHASE: dict[str, str | None] = {
    "inquerito": "inquerito",
    "boletim": "inquerito",
    "apreensao": "inquerito",
    "reconhecimento": None,
    "depoimento": None,
    "laudo": "pericial",  # cautelar / não repetível: the CPP art. 155 exception
    "denuncia": "judicial",
    "audiencia": "judicial",
    "interrogatorio": None,
    "defesa": "judicial",
    "alegacoes": "judicial",
    "sentenca": "judicial",
    "despacho": "judicial",  # always a judge's act
    "mandado": None,
    "certidao": None,
    "oficio": None,
    "peticao": None,
    "alvara": "judicial",
    "recurso": "judicial",
}
INQUIRY_MARKERS = ("delegad", "inquerito policial", "autoridade policial", "termo de declaracoes")
JUDICIAL_MARKERS = ("audiencia de instrucao", "juiz", "juiza", "magistrad", "contraditorio")

# ----------------------------------------------------------------------------- eproc combined-download splitting
# Format confirmed from a real TJRS download: one PDF per "parte" (volume), events merged together, each preceded
# by an auto-generated separator page. Other eproc courts are expected (not yet confirmed) to share it - the
# separator text is overridable via eproc_split's params if a court phrases it differently.
SEPARATOR_MARKER = "PÁGINA DE SEPARAÇÃO"
EVENT_NUM_RE = re.compile(r"Evento\s+(\d+)", re.I)

# code -> pattern matched against a document's first ~1500 chars of text; order matters, first match wins.
# Unmatched content gets code "OUTRO" (kind "outro"), not an error: the table is meant to grow.
DOC_TYPE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("DENUNCIA", re.compile(r"\bDEN[ÚU]NCIA\b", re.I)),
    ("DESPACHO", re.compile(r"DESPACHO\s*/?\s*DECIS[ÃA]O|\bDESPACHO\b", re.I)),
    ("DECISAO", re.compile(r"\bDECIS[ÃA]O\b", re.I)),
    ("TERMOAUD", re.compile(r"TERMO DE AUDI[ÊE]NCIA|ATA DE AUDI[ÊE]NCIA", re.I)),
    ("INTERROG", re.compile(r"AUTO DE INTERROGAT[ÓO]RIO|\bINTERROGAT[ÓO]RIO\b", re.I)),
    ("DEPOIM", re.compile(r"TERMO DE (DECLARA[ÇC][ÕO]ES|OITIVA)|\bDEPOIMENTO\b", re.I)),
    ("LAUDO", re.compile(r"\bLAUDO\b", re.I)),
    ("MANDADO", re.compile(r"\bMANDADO\b", re.I)),
    ("CERTIDAO", re.compile(r"\bCERTID[ÃA]O\b", re.I)),
    ("OFICIO", re.compile(r"\bOF[ÍI]CIO\b", re.I)),
    ("SENT", re.compile(r"\bSENTEN[ÇC]A\b", re.I)),
    ("ALEGFINAIS", re.compile(r"ALEGA[ÇC][ÕO]ES FINAIS", re.I)),
    ("RESPOSTA", re.compile(r"RESPOSTA [ÀA] ACUSA[ÇC][ÃA]O|CONTESTA[ÇC][ÃA]O|DEFESA PR[ÉE]VIA", re.I)),
    ("PETICAO", re.compile(r"PETI[ÇC][ÃA]O", re.I)),
    ("AUTOAPREENS", re.compile(r"AUTO DE (PRIS[ÃA]O|APREENS[ÃA]O|BUSCA)", re.I)),
    ("ALVARA", re.compile(r"ALVAR[ÁA]", re.I)),
    ("RECURSO", re.compile(r"\bRECURSO\b", re.I)),
]


class SplitEvent(BaseModel):
    """One parsed event from a combined eproc download: its number, inferred code and page text."""

    model_config = ConfigDict(extra="forbid")

    event: int
    code: str
    pages: list[str]


class SplitResult(BaseModel):
    """Outcome of `split_eproc_pages`: parsed events plus what was deliberately skipped, not an error."""

    model_config = ConfigDict(extra="forbid")

    events: list[SplitEvent] = Field(default_factory=list)
    n_no_document: int = 0  # separator immediately followed by another separator or EOF: a pure docket movement
    n_no_text: int = 0  # pages present but empty (e.g. an unconverted audio/video attachment placeholder)


def split_eproc_pages(pages: list[str], separator: str = SEPARATOR_MARKER) -> SplitResult:
    """Split one eproc volume's already-extracted page texts into per-event records.

    Pure and PDF-library-free so it is unit-testable with plain strings. ``pages`` is the volume's text, one string
    per PDF page, in order. A page containing ``separator`` starts a new event (its number comes from ``Evento N``
    on that same page); the event's own pages run until the next separator or the end. An event with no pages
    between its separator and the next is a docket movement with no attached document - not an error, just
    uncommon enough to count rather than silently drop. The event's ``code`` comes from `_doc_type_code` on its
    first page; no match yields ``"OUTRO"``.
    """
    sep_idx = [i for i, p in enumerate(pages) if separator in p]
    result = SplitResult()
    for n, i in enumerate(sep_idx):
        end = sep_idx[n + 1] if n + 1 < len(sep_idx) else len(pages)
        body = pages[i + 1 : end]
        if not body:
            result.n_no_document += 1
            continue
        if not any(p.strip() for p in body):
            result.n_no_text += 1
            continue
        m = EVENT_NUM_RE.search(pages[i])
        event_num = int(m[1]) if m else i
        result.events.append(SplitEvent(event=event_num, code=_doc_type_code(body[0]), pages=body))
    return result


def _doc_type_code(first_page: str, window: int = 2000) -> str:
    """Document-type code from the earliest-occurring pattern in the first ``window`` characters, or ``"OUTRO"``.

    Earliest match wins, not list order or line position: a despacho's body text routinely says "a denúncia
    atende aos requisitos..." well after its own "DESPACHO/DECISÃO" heading, so picking whichever pattern's first
    hit comes first in the text favours the document's own declared type over an incidental mention of another.
    Line position is not used (PDF text extraction does not reliably isolate a heading onto its own line).
    """
    head = first_page[:window]
    best: tuple[str, int] | None = None
    for code, rx in DOC_TYPE_PATTERNS:
        m = rx.search(head)
        if m and (best is None or m.start() < best[1]):
            best = (code, m.start())
    return best[0] if best else "OUTRO"


# ----------------------------------------------------------------------------- locators
# "Evento <n>, <code> p.<page> l.<line>": event is its own labelled part rather than folded into doc_id's "ev<n>/"
# prefix, so a reader (or a small model) does not have to parse it back out of a slash-joined id. doc_id itself
# (e.g. "ev12/DEPOIM1") is unchanged - fmt_loc/parse_loc only convert at the locator string's edge.
LOC_RE = re.compile(r"^Evento (?P<ev>\d+), (?P<code>[\w.-]+) p\.(?P<page>\d+) l\.(?P<a>\d+)(?:-(?P<b>\d+))?$")


def fmt_loc(doc_id: str, page: int, a: int, b: int | None = None) -> str:
    """Canonical locator, e.g. ``Evento 12, DEPOIM1 p.3 l.10-14`` (pages and lines are 1-based)."""
    ev, _, code = doc_id.partition("/")
    return f"Evento {ev.removeprefix('ev')}, {code} p.{page} l.{a}" + (f"-{b}" if b and b != a else "")


def parse_loc(loc: str) -> tuple[str, int, int, int] | None:
    """``(doc_id, page, first_line, last_line)`` or ``None`` when ``loc`` is not a canonical locator."""
    m = LOC_RE.match(loc.strip())
    if not m:
        return None
    a = int(m["a"])
    return f"ev{m['ev']}/{m['code']}", int(m["page"]), a, int(m["b"] or a)


# ----------------------------------------------------------------------------- normalisation
_STOP = {"a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "na", "no", "um", "uma", "com", "por", "para"}
_WORD = re.compile(r"[a-z0-9]+")
_TIME = re.compile(r"(\d{1,2})\s*(?:h|:|horas?)\s*(\d{2})?")
_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def norm(text: str) -> str:
    """Lower-case, accent-free, single-spaced text (for matching quotes and markers)."""
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return " ".join(t.split())


def tokens(text: str) -> set[str]:
    """Content words of ``text`` (normalised, stopwords dropped)."""
    return {w for w in _WORD.findall(norm(text)) if w not in _STOP}


def slot_conflict(slot: str, a: Any, b: Any, time_tolerance_min: int) -> bool:
    """Whether two values of the same fact slot contradict each other.

    ``time`` compares clock minutes with a tolerance, ``quantity`` compares the first number, every other slot
    compares content words: it is a conflict only when each side has a word the other lacks ("camiseta vermelha" vs
    "camiseta azul", "faca" vs "revólver"), not when one is just less precise ("camiseta" vs "camiseta azul").
    """
    sa, sb = str(a), str(b)
    if slot == "time":
        ma, mb = _TIME.search(norm(sa)), _TIME.search(norm(sb))
        if not (ma and mb):
            return False
        ta = int(ma[1]) * 60 + int(ma[2] or 0)
        tb = int(mb[1]) * 60 + int(mb[2] or 0)
        diff = abs(ta - tb)
        return min(diff, 1440 - diff) > time_tolerance_min
    if slot == "quantity":
        na, nb = _NUM.search(sa), _NUM.search(sb)
        return bool(na and nb) and float(na[0].replace(",", ".")) != float(nb[0].replace(",", "."))
    ta, tb = tokens(sa), tokens(sb)
    if not ta or not tb:
        return False

    def lacks(x: set[str], y: set[str]) -> bool:  # x says something y does not (fuzzy: camisa ~ camiseta)
        return any(all(SequenceMatcher(None, w, v).ratio() < 0.75 for v in y) for w in x)

    # a contradiction needs new detail on BOTH sides; "camiseta" vs "camiseta azul" is only less precise
    return lacks(ta, tb) and lacks(tb, ta)
