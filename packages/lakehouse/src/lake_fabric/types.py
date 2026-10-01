"""``python_source`` artifact: generated code that must at least parse."""

from __future__ import annotations

import ast
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_fabric.artifacts import ArtifactType
from agent_fabric.errors import ErrorDetail


class PythonSourceConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_lines: int = Field(2000, ge=1)


class PythonSourceProfile(BaseModel):
    n_lines: int
    preview: str

    def to_prompt(self) -> str:
        return f"python source: {self.n_lines} lines; starts: {self.preview!r}"


class PythonSourceType(ArtifactType):
    name = "python_source"
    Constraints = PythonSourceConstraints
    python_types = (str,)
    specificity = 0  # a plain str is inferred as 'text'; this type is only reached through declared ports

    def profile(self, value: str) -> PythonSourceProfile:
        return PythonSourceProfile(n_lines=value.count("\n") + 1, preview=value.strip()[:60])

    def static_check(self, profile: Any, constraints: Any, params: Any, loc: tuple[str | int, ...]) -> list[ErrorDetail]:
        if profile.n_lines > constraints.max_lines:
            return [ErrorDetail(loc=loc, type="source_too_long", msg=f"{profile.n_lines} lines > {constraints.max_lines}")]
        return []

    def runtime_check(self, value: str, constraints: Any, params: Any, loc: tuple[str | int, ...]) -> list[ErrorDetail]:
        try:
            ast.parse(value)
        except SyntaxError as exc:
            return [ErrorDetail(loc=loc, type="python_syntax_error", msg=f"line {exc.lineno}: {exc.msg}",
                                hint="regenerate the code from the spec; never patch generated code by hand")]
        return []
