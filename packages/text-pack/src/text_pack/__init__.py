"""Text domain pack - proves the fabric is domain-agnostic (no pandas involved).

Components: text_stats, keywords, summarize_text (``runtime: prompt``).  Pipelines: document_digest, document_summary.
Load with ``build_registry([text_pack.register])`` or entry point ``agent_fabric.domains``.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field

from agent_fabric.compat import requires_api
from agent_fabric.component import Component, ComponentParams, ComponentResult, Num, StepContext
from agent_fabric.errors import ErrorDetail
from agent_fabric.registry import Registry, component

SPEC_DIR = Path(__file__).parent / "skills"
_WORD = re.compile(r"[A-Za-zÀ-ÿ]+(?:-[A-Za-zÀ-ÿ]+)*")
STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "for",
    "is",
    "are",
    "was",
    "were",
    "with",
    "by",
    "de",
    "da",
    "do",
    "das",
    "dos",
    "e",
    "o",
    "os",
    "as",
    "em",
    "no",
    "na",
    "para",
    "com",
    "que",
    "um",
    "uma",
}


class TextStatsParams(ComponentParams):
    lowercase: bool = True


class TextStatsResult(ComponentResult):
    n_words: int
    n_sentences: int
    avg_word_length: Num
    lexical_diversity: Num


@component("text_stats")
class TextStats(Component[TextStatsParams, TextStatsResult]):
    Params = TextStatsParams
    Result = TextStatsResult

    def compute(self, inputs: dict, params: TextStatsParams, ctx: StepContext) -> TextStatsResult:
        """Count words and sentences and compute the average word length and lexical diversity (distinct words over all words).

        Warns when the text has fewer than 50 words, where the statistics are unstable.
        """
        text = inputs["text"]
        words = [w.lower() if params.lowercase else w for w in _WORD.findall(text)]
        sentences = [s for s in re.split(r"[.!?]+\s", text) if s.strip()]
        warns = ["very short text; statistics are unstable"] if len(words) < 50 else []
        return TextStatsResult(
            n_words=len(words),
            n_sentences=len(sentences),
            avg_word_length=sum(map(len, words)) / len(words) if words else None,
            lexical_diversity=len(set(words)) / len(words) if words else None,
            warnings=warns,
        )

    def summarize(self, r: dict) -> tuple[str, list[str]]:
        return (
            f"{r['n_words']} words in {r['n_sentences']} sentences.",
            [f"lexical diversity {r['lexical_diversity']:.2f}", f"average word length {r['avg_word_length']:.2f}"],
        )


class KeywordsParams(ComponentParams):
    top_k: int = Field(10, ge=1, le=50)
    min_length: int = Field(4, ge=1)
    extra_stopwords: list[str] = Field(default_factory=list)


class Keyword(BaseModel):
    term: str
    count: int


class KeywordsResult(ComponentResult):
    keywords: list[Keyword]


@component("keywords")
class Keywords(Component[KeywordsParams, KeywordsResult]):
    Params = KeywordsParams
    Result = KeywordsResult

    def extra_checks(self, inputs: dict, params: KeywordsParams) -> list[ErrorDetail]:
        n = len([w for w in _WORD.findall(inputs["text"]) if len(w) >= params.min_length])
        if n == 0:
            return [
                ErrorDetail(
                    loc=("params", "min_length"),
                    type="no_candidates",
                    msg=f"no words with >= {params.min_length} letters",
                    hint="lower min_length",
                )
            ]
        return []

    def compute(self, inputs: dict, params: KeywordsParams, ctx: StepContext) -> KeywordsResult:
        """Most frequent content words: lowercased words of at least ``min_length`` letters minus stop words and ``extra_stopwords``.

        Emits the ranked ``terms`` list; the result carries each term with its count.
        """
        stop = STOPWORDS | {w.lower() for w in params.extra_stopwords}
        words = [
            w.lower() for w in _WORD.findall(inputs["text"]) if len(w) >= params.min_length and w.lower() not in stop
        ]
        top = Counter(words).most_common(params.top_k)
        ctx.emit("terms", [t for t, _ in top])
        return KeywordsResult(keywords=[Keyword(term=t, count=c) for t, c in top])

    def summarize(self, r: dict) -> tuple[str, list[str]]:
        kws = r["keywords"]
        return f"Top terms: {', '.join(k['term'] for k in kws[:5])}.", [f"{k['term']}: {k['count']}" for k in kws[:6]]


@requires_api(1)
def register(registry: Registry) -> list[str]:
    """Register the text domain (``text_stats``, ``keywords``, ``summarize_text`` and the ``document_digest`` / ``document_summary`` pipelines); returns the names registered."""
    return registry.load_domain(SPEC_DIR, [TextStats, Keywords])


__all__ = [
    "SPEC_DIR",
    "Keyword",
    "Keywords",
    "KeywordsParams",
    "KeywordsResult",
    "TextStats",
    "TextStatsParams",
    "TextStatsResult",
    "register",
]
