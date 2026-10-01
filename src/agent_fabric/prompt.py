"""Prompt-runtime components: ``runtime: prompt`` skills need no Python.

A SKILL.md with ``runtime: prompt`` is bound to a generic ``PromptComponent`` at
registration. Its ``## Instructions`` body section is the prompt template; the
model's reply becomes the step's artifacts (declared ``outputs`` ports plus the
implicit ``result`` JSON).

Placeholders in the template: ``{params.<name>}``, ``{inputs.<port>}``,
``{objective}`` (the pipeline objective). Literal braces must be escaped as
``{{`` / ``}}``. Placeholders are validated at registration.

Safety: outputs are restricted to ``text`` / ``json`` / ``number`` / ``any``
artifacts - a prompt step can never feed a ``dataframe`` port, so model text
cannot masquerade as computed data. Optional grounding rejects numbers that do
not appear in the inputs/params (same machinery as the interpreters).
"""

from __future__ import annotations

import string
from types import SimpleNamespace
from typing import Any, ClassVar

from pydantic import create_model

from .component import Component, ComponentParams, ComponentResult, StepContext
from .errors import DependencyError, ErrorDetail, LLMOutputError, SpecError, suggest
from .llm.backends import LLMSettings
from .llm.prompts import PROMPT_STEP_OUTPUT_JSON, PROMPT_STEP_OUTPUT_TEXT, PROMPT_STEP_SYSTEM, compact
from .llm.self_correction import extract_text, structured_completion
from .markdown import INSTRUCTIONS
from .spec import ComponentSpec

PROMPT_OUTPUT_TYPES = {"text", "json", "number", "any"}
MAX_INPUT_CHARS = 20000
_FORMATTER = string.Formatter()


class PromptResult(ComponentResult):
    text: str
    outputs: dict[str, Any] = {}


def _template_fields(template: str) -> list[str]:
    """Field names used by the template ('params.tone', 'inputs.draft', 'objective')."""
    return [f for _, f, _, _ in _FORMATTER.parse(template) if f]


def _render_input(spec: ComponentSpec, types: Any, port: str, value: Any) -> str:
    """How an input port is shown inside the prompt (raw text, compact JSON, type description)."""
    if value is None:
        return ""
    t = types.get(spec.inputs[port].type)
    if t.name in ("text", "any"):
        text = value if isinstance(value, str) else compact(value)
    elif t.name in ("json", "number"):
        text = compact(value)
    else:
        text = t.describe(t.profile(value), value)
    return text if len(text) <= MAX_INPUT_CHARS else text[:MAX_INPUT_CHARS] + "\n[truncated]"


class PromptComponent(Component[ComponentParams, PromptResult]):
    """Generic component whose compute is a guided, self-corrected LLM call."""

    Params = ComponentParams
    Result = PromptResult
    template: ClassVar[str] = ""

    @classmethod
    def from_spec(cls, spec: ComponentSpec, types: Any) -> PromptComponent:
        errors: list[ErrorDetail] = []
        template = spec.guidance.section(INSTRUCTIONS)
        if not template:
            errors.append(
                ErrorDetail(
                    loc=("body",),
                    type="missing_instructions",
                    msg="'runtime: prompt' needs a '## Instructions' section with the prompt template",
                    hint="add it to the SKILL.md body; {params.x}, {inputs.x} and {objective} are allowed",
                )
            )
        for name, port in spec.outputs.items():
            if port.type not in PROMPT_OUTPUT_TYPES:
                errors.append(
                    ErrorDetail(
                        loc=("outputs", name, "type"),
                        type="prompt_output_type",
                        input=port.type,
                        msg=f"a prompt step can only produce {sorted(PROMPT_OUTPUT_TYPES)} artifacts",
                        hint="use 'text' or 'json'",
                    )
                )
        for field in _template_fields(template):
            root, _, leaf = field.partition(".")
            if root == "params" and leaf not in spec.params:
                errors.append(
                    ErrorDetail(
                        loc=("body", "instructions"),
                        type="unknown_placeholder",
                        input=field,
                        msg=f"'{field}' is not a declared param",
                        hint=suggest(leaf, spec.params) or f"params: {sorted(spec.params)}",
                    )
                )
            elif root == "inputs" and leaf not in spec.inputs:
                errors.append(
                    ErrorDetail(
                        loc=("body", "instructions"),
                        type="unknown_placeholder",
                        input=field,
                        msg=f"'{field}' is not a declared input port",
                        hint=suggest(leaf, spec.inputs) or f"inputs: {sorted(spec.inputs)}",
                    )
                )
            elif root not in ("params", "inputs", "objective"):
                errors.append(
                    ErrorDetail(
                        loc=("body", "instructions"),
                        type="unknown_placeholder",
                        input=field,
                        msg=f"placeholder '{field}' is not params/inputs/objective",
                        hint="use {params.<name>}, {inputs.<port>}, {objective}; escape literal braces as {{ }}",
                    )
                )
        if errors:
            raise SpecError(f"Prompt spec '{spec.name}' is invalid", errors, component=spec.name)
        fields = {k: (Any, ... if p.required else p.default) for k, p in spec.params.items()}
        params_model = create_model(f"{spec.name}_params", __base__=ComponentParams, **fields)
        sub = type(
            f"Prompt_{spec.name}", (cls,), {"Params": params_model, "spec_name": spec.name, "template": template}
        )
        return sub(spec, types)

    def compute(self, inputs: dict[str, Any], params: ComponentParams, ctx: StepContext) -> PromptResult:
        if ctx.llm is None:
            raise DependencyError(
                f"'{self.spec.name}' is a 'runtime: prompt' step and needs an LLM backend",
                [
                    ErrorDetail(
                        type="no_llm_backend",
                        msg="no backend on the step context",
                        hint="run it through an agent, or pass llm= to PipelineExecutor",
                    )
                ],
            )
        settings = ctx.llm_settings or LLMSettings()
        opts = self.spec.prompt
        ports = ", ".join(f'"{p}": {ps.type}' for p, ps in self.spec.outputs.items())
        rule = PROMPT_STEP_OUTPUT_JSON.format(ports=ports) if self.spec.outputs else PROMPT_STEP_OUTPUT_TEXT
        rendered = {p: _render_input(self.spec, self.types, p, inputs.get(p)) for p in self.spec.inputs}
        user = self.template.format(params=params, inputs=SimpleNamespace(**rendered), objective=ctx.objective)
        system = PROMPT_STEP_SYSTEM.format(output_rule=rule)

        def parse(data: Any) -> tuple[dict[str, Any], list[str]]:
            declared = self.spec.outputs
            if not isinstance(data, dict):
                raise LLMOutputError(
                    "Prompt output must be a JSON object",
                    [ErrorDetail(type="not_an_object", msg=type(data).__name__, hint=f"reply with {{{ports}}}")],
                )
            out: dict[str, Any] = {}
            errors = []
            for name, port in declared.items():
                if name not in data:
                    errors.append(
                        ErrorDetail(
                            loc=("outputs", name),
                            type="missing",
                            msg=f"key '{name}' is required",
                            hint=f"reply with {{{ports}}}",
                        )
                    )
                    continue
                if not self.types.get(port.type).accepts(data[name]):
                    errors.append(
                        ErrorDetail(
                            loc=("outputs", name),
                            type="wrong_artifact_type",
                            input=data[name],
                            msg=f"expected {port.type}, got {type(data[name]).__name__}",
                        )
                    )
                else:
                    out[name] = data[name]
            extra = sorted(set(data) - set(declared))
            if not errors and (opts is None or opts.grounding):
                texts = [(("outputs", n), v) for n, v in out.items() if isinstance(v, str)]
                errors += self._grounding_errors(texts, inputs, params)
            if errors:
                raise LLMOutputError(f"Prompt output has {len(errors)} problem(s)", errors)
            return out, extra

        if not self.spec.outputs:
            res = structured_completion(
                ctx.llm,
                system,
                user,
                _parse_text(self, inputs, params),
                model=(opts.model if opts else None) or settings.interpreter_model,
                max_attempts=settings.max_correction_attempts,
                json_mode=False,
                temperature=(opts.temperature if opts else None) or settings.temperature,
                extract=extract_text,
            )
            return PromptResult(text=res.value)
        res = structured_completion(
            ctx.llm,
            system,
            user,
            parse,
            model=(opts.model if opts else None) or settings.interpreter_model,
            max_attempts=settings.max_correction_attempts,
            json_mode=settings.json_mode,
            temperature=(opts.temperature if opts else None) or settings.temperature,
        )
        outputs, extra = res.value
        warns = [f"extra keys ignored: {extra}"] if extra else []
        for name, value in outputs.items():
            ctx.emit(name, value)
        text = next(
            (v for n, v in outputs.items() if self.spec.outputs[n].type == "text" and isinstance(v, str)),
            compact(outputs, max_chars=4000),
        )
        return PromptResult(text=text, outputs=outputs, warnings=warns)

    def _grounding_errors(
        self, texts: list[tuple[tuple[str | int, ...], str]], inputs: dict[str, Any], params: ComponentParams
    ) -> list[ErrorDetail]:
        from .llm.interpreter import grounding_errors_texts

        return grounding_errors_texts(texts, inputs, params.model_dump(mode="json"))

    def summarize(self, result: dict[str, Any]) -> tuple[str, list[str]]:
        lines = [ln.strip() for ln in str(result.get("text", "")).splitlines() if ln.strip()]
        return ((lines[0] if lines else "prompt step completed.")[:240], lines[1:6])


def _parse_text(comp: PromptComponent, inputs: dict[str, Any], params: ComponentParams):
    """Free-text parse with optional grounding (no declared output ports)."""

    def parse(text: str) -> str:
        opts = comp.spec.prompt
        if opts is None or opts.grounding:
            errs = comp._grounding_errors([(("text",), text)], inputs, params)
            if errs:
                raise LLMOutputError("Prompt output cites numbers not present in the inputs", errs)
        return text

    return parse
