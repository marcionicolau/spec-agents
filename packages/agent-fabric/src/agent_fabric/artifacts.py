"""Artifact types: what flows through component ports.

An ``ArtifactType`` knows how to
* recognise a value (``accepts``),
* summarise it for prompts and plan-time checks (``profile`` -> pydantic model),
* validate it against a port's declarative ``constraints`` (static on the profile, runtime on the value).

Domains register new types (e.g. ``dataframe`` in :mod:`agent_fabric.tabular`, an ``image``
type, a ``geojson`` type). Specs refer to types by name only.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .errors import ErrorDetail, SpecError, details_from_pydantic, suggest


class NoConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArtifactType:
    name: ClassVar[str] = "any"
    Constraints: ClassVar[type[BaseModel]] = NoConstraints
    python_types: ClassVar[tuple[type, ...]] = (object,)
    specificity: ClassVar[int] = 0  # higher wins when inferring the type of a raw value

    def accepts(self, value: Any) -> bool:
        return isinstance(value, self.python_types)

    def profile(self, value: Any) -> BaseModel | None:
        return None

    def describe(self, profile: BaseModel | None, value: Any = None) -> str:
        to_prompt = getattr(profile, "to_prompt", None)
        if callable(to_prompt):
            return to_prompt()
        return f"{self.name}" if value is None else f"{self.name}: {str(value)[:200]}"

    def parse_constraints(self, raw: dict[str, Any], loc: tuple[str | int, ...]) -> BaseModel:
        try:
            return self.Constraints.model_validate(raw or {})
        except ValidationError as exc:
            raise SpecError(f"Invalid constraints for type '{self.name}'", details_from_pydantic(exc, loc)) from exc

    def static_check(
        self, profile: BaseModel, constraints: BaseModel, params: BaseModel, loc: tuple[str | int, ...]
    ) -> list[ErrorDetail]:
        """Checks that only need the profile (plan time, before any data is touched)."""
        return []

    def runtime_check(
        self, value: Any, constraints: BaseModel, params: BaseModel, loc: tuple[str | int, ...]
    ) -> list[ErrorDetail]:
        """Checks that need the real value (after static checks passed)."""
        return []

    def compatible(self, target: str) -> bool:
        return target in ("any", self.name)


class JsonType(ArtifactType):
    name = "json"
    python_types = (dict, list)
    specificity = 1


class TextConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_chars: int = Field(1, ge=0)
    max_chars: int | None = None


class TextProfile(BaseModel):
    n_chars: int
    n_words: int
    preview: str

    def to_prompt(self) -> str:
        return f"text: {self.n_words} words, {self.n_chars} chars; starts: {self.preview!r}"


class TextType(ArtifactType):
    name = "text"
    Constraints = TextConstraints
    python_types = (str,)
    specificity = 1

    def profile(self, value: str) -> TextProfile:
        return TextProfile(n_chars=len(value), n_words=len(value.split()), preview=value[:80])

    def static_check(self, profile, constraints, params, loc):
        errs = []
        if profile.n_chars < constraints.min_chars:
            errs.append(
                ErrorDetail(loc=loc, type="text_too_short", msg=f"{profile.n_chars} chars < {constraints.min_chars}")
            )
        if constraints.max_chars and profile.n_chars > constraints.max_chars:
            errs.append(
                ErrorDetail(
                    loc=loc,
                    type="text_too_long",
                    msg=f"{profile.n_chars} chars > {constraints.max_chars}",
                    hint="split the text or raise max_chars",
                )
            )
        return errs


class NumberType(ArtifactType):
    name = "number"
    python_types = (int, float)
    specificity = 1

    def accepts(self, value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)


class TypeRegistry:
    def __init__(self) -> None:
        self._types: dict[str, ArtifactType] = {}
        for t in (ArtifactType(), JsonType(), TextType(), NumberType()):
            self.register(t)

    def register(self, t: ArtifactType) -> None:
        self._types[t.name] = t

    def get(self, name: str) -> ArtifactType:
        try:
            return self._types[name]
        except KeyError:
            raise SpecError(
                f"Unknown artifact type '{name}'",
                [
                    ErrorDetail(
                        type="unknown_type",
                        msg=f"'{name}' is not registered",
                        input=name,
                        hint=suggest(name, self._types) or f"available: {sorted(self._types)}",
                    )
                ],
            ) from None

    def has(self, name: str) -> bool:
        return name in self._types

    def names(self) -> list[str]:
        return sorted(self._types)

    def infer(self, value: Any) -> ArtifactType:
        matches = [t for t in self._types.values() if t.accepts(value)]
        return max(matches, key=lambda t: t.specificity)


__all__ = [
    "ArtifactType",
    "JsonType",
    "NoConstraints",
    "NumberType",
    "TextConstraints",
    "TextProfile",
    "TextType",
    "TypeRegistry",
]
