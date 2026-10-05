"""Markdown documents with YAML frontmatter (``SKILL.md``, ``AGENT.md``, ``fabric.md``).

    ---                      <- frontmatter: the machine-checked contract (validated by pydantic)
    name: pca
    ...
    ---
    # PCA                    <- body: natural-language guidance, injected into prompts on demand
    ## When to use
    ...

Only the frontmatter is authoritative. The body is guidance: it can never widen what the
contract allows (params, ports, sub-agents are validated from the frontmatter alone).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from .errors import ErrorDetail, SpecError

_FM = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z", re.S)
_H2 = re.compile(r"^##[ \t]+(.+?)[ \t]*#*[ \t]*$", re.M)
_H1 = re.compile(r"^#[ \t]+(.+?)[ \t]*$", re.M)

# Canonical section names (matched case-insensitively). Consumers:
WHEN_TO_USE = "when to use"  # planner catalogue (first paragraph)
WHEN_NOT_TO_USE = "when not to use"  # planner catalogue
INTERPRETING = "interpreting"  # step interpreter
COMMON_MISTAKES = "common mistakes"  # parameter repair + planner feedback
PROCEDURE = "procedure"  # pipelines: why the steps are ordered this way
INSTRUCTIONS = "instructions"  # runtime: prompt - the prompt template ({params.x}, {inputs.x}, {objective})
SECTION_ALIASES = {
    "avoid when": WHEN_NOT_TO_USE,
    "interpretation": INTERPRETING,
    "pitfalls": COMMON_MISTAKES,
    "task": INSTRUCTIONS,
}


@dataclass
class MarkdownDoc:
    path: Path
    meta: dict[str, Any]
    body: str
    sections: dict[str, str] = field(default_factory=dict)

    @property
    def title(self) -> str | None:
        """Text of the first level-1 heading of the body, or ``None``."""
        m = _H1.search(self.body)
        return m.group(1).strip() if m else None


def split_sections(body: str) -> dict[str, str]:
    """``## Heading`` -> text until the next ``##`` (lower-cased keys, aliases normalised)."""
    out: dict[str, str] = {}
    matches = list(_H2.finditer(body))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        key = m.group(1).strip().lower()
        out[SECTION_ALIASES.get(key, key)] = body[m.end() : end].strip()
    return out


def read_markdown(path: str | Path) -> MarkdownDoc:
    """Parse a Markdown file with YAML frontmatter into a `MarkdownDoc`.

    A missing or invalid frontmatter block raises a `SpecError` that names the file.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    m = _FM.match(text)
    if not m:
        raise SpecError(
            f"{path} has no YAML frontmatter",
            [
                ErrorDetail(
                    loc=(str(path),),
                    type="missing_frontmatter",
                    msg="file must start with a '---' fenced YAML block",
                    hint="add the contract (name, kind, ...) between two '---' lines",
                )
            ],
        )
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SpecError(
            f"{path}: invalid YAML frontmatter",
            [ErrorDetail(loc=(str(path), "frontmatter"), type="yaml_error", msg=str(exc)[:300])],
        ) from exc
    if not isinstance(meta, dict):
        raise SpecError(
            f"{path}: frontmatter must be a mapping",
            [ErrorDetail(loc=(str(path), "frontmatter"), type="not_a_mapping", msg=type(meta).__name__)],
        )
    body = m.group(2).strip()
    return MarkdownDoc(path=path, meta=meta, body=body, sections=split_sections(body))


def first_paragraph(text: str, max_chars: int = 300) -> str:
    """Return the first paragraph of ``text`` on one line, truncated to ``max_chars`` with an ellipsis."""
    para = next((p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()), "")
    para = re.sub(r"\s+", " ", para)
    return para if len(para) <= max_chars else para[: max_chars - 1].rsplit(" ", 1)[0] + "…"


class Guidance(BaseModel):
    """Natural-language guidance attached to a spec (from the Markdown body)."""

    body: str = ""
    sections: dict[str, str] = Field(default_factory=dict)
    source: str | None = None
    references: list[str] = Field(default_factory=list, description="files under references/, loaded on demand")

    def section(self, name: str, max_chars: int | None = None) -> str:
        """Text of a canonical body section (e.g. ``"when to use"``), looked up case-insensitively through the section aliases.

        Returns ``""`` when absent. With ``max_chars`` the text is cut at a word boundary and ends with an ellipsis.
        """
        text = self.sections.get(SECTION_ALIASES.get(name.lower(), name.lower()), "")
        if max_chars and len(text) > max_chars:
            return text[: max_chars - 1].rsplit(" ", 1)[0] + "…"
        return text

    def reference(self, name: str) -> str:
        """Read one reference file (progressive disclosure: only when a caller asks for it)."""
        if self.source is None:
            raise FileNotFoundError(name)
        base = Path(self.source).parent / "references"
        match = next((r for r in self.references if r == name or Path(r).name == name), None)
        if match is None:
            raise FileNotFoundError(f"{name} (available: {self.references})")
        return (base / Path(match).name).read_text(encoding="utf-8")


def guidance_from(doc: MarkdownDoc) -> Guidance:
    """Build the `Guidance` of a spec from its Markdown body, canonical sections and ``references/*.md`` file names."""
    refs_dir = doc.path.parent / "references"
    refs = sorted(p.name for p in refs_dir.glob("*.md")) if refs_dir.is_dir() else []
    return Guidance(body=doc.body, sections=doc.sections, source=doc.path.as_posix(), references=refs)


__all__ = [
    "COMMON_MISTAKES",
    "INSTRUCTIONS",
    "INTERPRETING",
    "PROCEDURE",
    "WHEN_NOT_TO_USE",
    "WHEN_TO_USE",
    "Guidance",
    "MarkdownDoc",
    "first_paragraph",
    "guidance_from",
    "read_markdown",
    "split_sections",
]
