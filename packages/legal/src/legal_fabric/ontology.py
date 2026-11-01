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
}
INQUIRY_MARKERS = ("delegad", "inquerito policial", "autoridade policial", "termo de declaracoes")
JUDICIAL_MARKERS = ("audiencia de instrucao", "juiz", "juiza", "magistrad", "contraditorio")

# ----------------------------------------------------------------------------- locators
LOC_RE = re.compile(r"^(?P<doc>[\w/.-]+) p\.(?P<page>\d+) l\.(?P<a>\d+)(?:-(?P<b>\d+))?$")


def fmt_loc(doc_id: str, page: int, a: int, b: int | None = None) -> str:
    """Canonical locator, e.g. ``ev12/DEPOIM1 p.3 l.10-14`` (pages and lines are 1-based)."""
    return f"{doc_id} p.{page} l.{a}" + (f"-{b}" if b and b != a else "")


def parse_loc(loc: str) -> tuple[str, int, int, int] | None:
    """``(doc_id, page, first_line, last_line)`` or ``None`` when ``loc`` is not a canonical locator."""
    m = LOC_RE.match(loc.strip())
    if not m:
        return None
    a = int(m["a"])
    return m["doc"], int(m["page"]), a, int(m["b"] or a)


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
