"""Run-trace export: JSON-lines sink with a stable schema, plus an optional OpenTelemetry bridge.

The JSONL schema is the `TraceEvent` model verbatim - one object per line, stable field names:

    {"seq": 0, "at": 0.0012, "path": "research_lead", "event": "start", "detail": "..."}

`seq` is the total order of the run (delegations can run in parallel), `at` the offset in seconds since
run start, `path` the agent path in the tree, `event` one of ``start``, ``end``, ``llm_call``,
``delegate``, ``fallback``, ``skip``, ``error``, and `detail` free text cut at 200 characters.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .errors import DependencyError, ErrorDetail

if TYPE_CHECKING:  # pragma: no cover
    from .agents.runtime import TraceEvent


def _event_line(e: TraceEvent) -> str:
    return json.dumps(e.model_dump(mode="json"), separators=(",", ":"))


class JsonlTraceSink:
    """``on_event`` listener writing every trace event as one JSON line (flushed per event, crash-safe).

    Attach with ``fabric.run(..., on_event=sink)`` or the CLI's ``--trace-out``; close when the run ends.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._fh = self.path.open("w", encoding="utf-8")

    def __call__(self, e: TraceEvent) -> None:
        """Append ``e`` as a JSON line."""
        self._fh.write(_event_line(e) + "\n")
        self._fh.flush()

    def close(self) -> None:
        """Flush and close the file."""
        self._fh.close()

    def __enter__(self) -> JsonlTraceSink:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def write_jsonl(trace: list[TraceEvent], path: str | Path) -> Path:
    """Write a finished run's ``report.trace`` as JSON lines; returns ``path``."""
    p = Path(path)
    with JsonlTraceSink(p) as sink:
        for e in trace:
            sink(e)
    return p


def default_otel_tracer() -> Any:
    """Return the OpenTelemetry tracer for ``agent_fabric``.

    Requires the ``otel`` extra (``pip install 'spec-agents-core[otel]'``). When the process has no
    tracer provider configured (no opentelemetry-instrument wrapper, no app setup), a console provider
    printing each finished span is installed so ``--otel`` alone produces visible output.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
    except ImportError as exc:
        raise DependencyError(
            "OpenTelemetry export needs the 'otel' extra",
            [
                ErrorDetail(
                    type="missing_dependency",
                    msg="opentelemetry-sdk is not installed",
                    hint="pip install 'spec-agents-core[otel]'",
                )
            ],
        ) from exc
    if isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider | trace.NoOpTracerProvider):
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
    return trace.get_tracer("agent_fabric")


class OtelTraceSink:
    """``on_event`` listener mapping a run to OpenTelemetry spans.

    An agent run is a span (``start`` opens it, ``end`` closes it with an ERROR status when the run
    failed); ``llm_call`` opens a child span closed by the next event at the same path (the call is
    synchronous, so the gap is the call latency); ``delegate``/``fallback``/``skip``/``error`` become
    span events on the nearest ancestor span. Spans are named after the path's last segment and carry
    ``agent_fabric.path`` / ``agent_fabric.detail`` attributes. An open-instrumented or app-configured
    tracer provider is used when present; otherwise a console provider is installed.
    """

    def __init__(self, tracer: Any = None) -> None:
        self._tracer = tracer
        self._spans: dict[str, Any] = {}  # path -> open agent span
        self._llm: dict[str, Any] = {}  # path -> open llm_call child span

    def _t(self) -> Any:
        if self._tracer is None:
            self._tracer = default_otel_tracer()
        return self._tracer

    def _agent_span(self, path: str) -> Any:
        """Nearest open ancestor span for ``path`` (skip events name a child that never started)."""
        while path and path not in self._spans:
            path = path.rpartition("/")[0]
        return self._spans.get(path)

    def __call__(self, e: TraceEvent) -> None:
        """Map ``e`` to span lifecycle/events."""
        tracer = self._t()  # raises DependencyError when the 'otel' extra is missing
        from opentelemetry import trace

        if e.event == "start":
            parent = self._spans.get(e.path.rpartition("/")[0])
            ctx = trace.set_span_in_context(parent) if parent is not None else None
            self._spans[e.path] = tracer.start_span(
                e.path.rpartition("/")[-1], context=ctx, attributes={"agent_fabric.path": e.path}
            )
            return
        if e.event == "llm_call":
            agent = self._spans.get(e.path)
            if agent is not None:
                ctx = trace.set_span_in_context(agent)
                self._llm[e.path] = tracer.start_span("llm_call", context=ctx, attributes={"model": e.detail})
            return
        if (llm := self._llm.pop(e.path, None)) is not None:
            llm.end()  # the event after llm_call at the same path marks the call's return
        if e.event == "end":
            span = self._spans.pop(e.path, None)
            if span is None:
                return  # 'end' for a path that never 'start'ed
            span.set_status(trace.StatusCode.ERROR if e.detail == "failed" else trace.StatusCode.OK)
            span.end()
            return
        agent = self._agent_span(e.path)
        if agent is None:
            return
        if e.event == "error":
            agent.set_status(trace.StatusCode.ERROR)
        agent.add_event(e.event, {"agent_fabric.detail": e.detail})

    def close(self) -> None:
        """End any spans still open (e.g. after a crash mid-run)."""
        for span in [*self._llm.values(), *self._spans.values()]:
            span.end()
        self._llm.clear()
        self._spans.clear()


__all__ = [
    "JsonlTraceSink",
    "OtelTraceSink",
    "default_otel_tracer",
    "write_jsonl",
]
