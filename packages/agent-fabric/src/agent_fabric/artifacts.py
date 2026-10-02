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
    """Base class of artifact types: what a value is, how it is profiled and which constraints a port can declare.

    The base type (``any``) accepts every Python object. Subclasses set ``name``, ``python_types`` and ``specificity`` (higher wins when the
    type of a raw value is inferred), define a ``Constraints`` model and override `profile`, ``static_check`` (plan time, profile only) and
    ``runtime_check`` (execution time, real value). Register instances in a `TypeRegistry`.
    """

    name: ClassVar[str] = "any"
    Constraints: ClassVar[type[BaseModel]] = NoConstraints
    python_types: ClassVar[tuple[type, ...]] = (object,)
    specificity: ClassVar[int] = 0  # higher wins when inferring the type of a raw value

    def accepts(self, value: Any) -> bool:
        """Whether ``value`` is an instance of this type's Python types."""
        return isinstance(value, self.python_types)

    def profile(self, value: Any) -> BaseModel | None:
        """Summarise a value for planners and static checks without sending the data itself; ``None`` when the type has no profile."""
        return None

    def describe(self, profile: BaseModel | None, value: Any = None) -> str:
        """Short text for prompts: the profile's own description when it has one, else the type name and a preview (at most 200 characters) of the value."""
        to_prompt = getattr(profile, "to_prompt", None)
        if callable(to_prompt):
            return to_prompt()
        return f"{self.name}" if value is None else f"{self.name}: {str(value)[:200]}"

    def parse_constraints(self, raw: dict[str, Any], loc: tuple[str | int, ...]) -> BaseModel:
        """Validate raw port constraints against this type's ``Constraints`` model.

        Raises a `SpecError` located at ``loc`` listing every invalid field.
        """
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
        """Whether an artifact of this type can feed a port of type ``target`` (the same type, or ``any``)."""
        return target in ("any", self.name)


class JsonType(ArtifactType):
    """Artifact type ``json``: a ``dict`` or ``list`` of JSON-like data."""

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
        """One-line description for prompts: word and character counts and the start of the text."""
        return f"text: {self.n_words} words, {self.n_chars} chars; starts: {self.preview!r}"


class TextType(ArtifactType):
    """Artifact type ``text``: a ``str``, profiled by character and word counts.

    Port constraints (`TextConstraints`): ``min_chars`` (default 1) and ``max_chars``; violations are reported as ``text_too_short`` and
    ``text_too_long`` at plan time.
    """

    name = "text"
    Constraints = TextConstraints
    python_types = (str,)
    specificity = 1

    def profile(self, value: str) -> TextProfile:
        """Profile a string: character count, word count and the first 80 characters."""
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
    """Artifact type ``number``: an ``int`` or ``float`` (booleans are rejected)."""

    name = "number"
    python_types = (int, float)
    specificity = 1

    def accepts(self, value: Any) -> bool:
        """``int`` or ``float``; booleans are not numbers here."""
        return isinstance(value, (int, float)) and not isinstance(value, bool)


class TypeRegistry:
    """Registry of artifact types by name; starts with ``any``, ``json``, ``text`` and ``number``.

    `register` adds or replaces a type (domain packs add theirs, e.g. ``dataframe``); ``get`` raises a `SpecError` with a suggestion for unknown
    names; the registry can also infer the type of a raw value (most specific match wins).
    """

    def __init__(self) -> None:
        self._types: dict[str, ArtifactType] = {}
        for t in (ArtifactType(), JsonType(), TextType(), NumberType()):
            self.register(t)

    def register(self, t: ArtifactType) -> None:
        """Register a type under its ``name``, replacing any type with the same name."""
        self._types[t.name] = t

    def get(self, name: str) -> ArtifactType:
        """The artifact type registered under ``name``; raises a `SpecError` with a spelling suggestion for an unknown name."""
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
        """Whether a type with this name is registered."""
        return name in self._types

    def names(self) -> list[str]:
        """Sorted names of the registered types."""
        return sorted(self._types)

    def infer(self, value: Any) -> ArtifactType:
        """The most specific registered type that accepts ``value`` (highest ``specificity``; ``any`` when nothing else matches)."""
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
