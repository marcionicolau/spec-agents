"""Trace export: JSONL sink (stable schema) and the OpenTelemetry bridge."""

from __future__ import annotations

import importlib.util
import json
import sys
import types

import pytest
from test_cli import NOTES, TRANSCRIPT, args, cap

from agent_fabric.agents.runtime import TraceEvent
from agent_fabric.cli.commands import cmd_run
from agent_fabric.errors import DependencyError
from agent_fabric.llm.backends import ScriptedBackend
from agent_fabric.trace import JsonlTraceSink, OtelTraceSink, write_jsonl

EVENT = {
    "seq": 0,
    "at": 0.0,
    "path": "lead",
    "event": "start",
    "detail": "digest",
}


def ev(seq: int, path: str, event: str, detail: str = "") -> TraceEvent:
    return TraceEvent(seq=seq, at=seq / 10, path=path, event=event, detail=detail)


def test_jsonl_sink_schema_and_order(tmp_path):
    sink = JsonlTraceSink(tmp_path / "t.jsonl")
    for e in [
        ev(0, "lead", "start", "x"),
        ev(1, "lead", "llm_call", "local-fast"),
        ev(2, "lead/stats", "skip", "budget"),
        ev(3, "lead", "end", "ok"),
    ]:
        sink(e)
    sink.close()
    lines = [json.loads(ln) for ln in (tmp_path / "t.jsonl").read_text().splitlines()]
    assert [sorted(line) for line in lines] == [["at", "detail", "event", "path", "seq"]] * 4  # stable fields
    assert [line["seq"] for line in lines] == [0, 1, 2, 3]
    assert lines[1]["event"] == "llm_call" and lines[1]["detail"] == "local-fast"


def test_write_jsonl_matches_streaming(tmp_path):
    events = [ev(0, "lead", "start"), ev(1, "lead", "end", "ok")]
    streamed = tmp_path / "s.jsonl"
    with JsonlTraceSink(streamed) as sink:
        for e in events:
            sink(e)
    assert write_jsonl(events, tmp_path / "d.jsonl").read_text() == streamed.read_text()


def test_cli_run_writes_trace(tmp_path):
    txt = tmp_path / "meeting.txt"
    txt.write_text(TRANSCRIPT, encoding="utf-8")
    trace = tmp_path / "run.jsonl"
    plan = '{"objective": "digest", "steps": [{"id": "s", "component": "summarize_notes"}]}'
    be = ScriptedBackend([plan, '{"summary": "Ship Friday agreed."}'])
    console = cap()
    a = args("run", NOTES, "Digest this", "--plain", "--input", f"transcript={txt}", "--trace-out", str(trace))
    assert cmd_run(a, console, backend=be) == 0
    lines = [json.loads(ln) for ln in trace.read_text().splitlines()]
    assert lines[0]["event"] == "start" and lines[-1]["event"] == "end"
    assert [line["seq"] for line in lines] == sorted(line["seq"] for line in lines)
    assert {line["event"] for line in lines} >= {"start", "end", "llm_call"}
    assert {line["path"] for line in lines} == {"note_taker"}


class _Span:
    def __init__(self, name: str, parent: _Span | None) -> None:
        self.name, self.parent = name, parent
        self.events: list[tuple[str, dict]] = []
        self.status = None
        self.ended = False

    def set_status(self, s) -> None:
        self.status = s

    def add_event(self, name: str, attrs: dict) -> None:
        self.events.append((name, attrs))

    def end(self) -> None:
        self.ended = True


class _Tracer:
    def __init__(self) -> None:
        self.spans: list[_Span] = []

    def start_span(self, name: str, context=None, attributes=None) -> _Span:
        span = _Span(name, parent=context)
        span.attributes = attributes or {}
        self.spans.append(span)
        return span


def _fake_otel() -> types.ModuleType:
    """A minimal ``opentelemetry`` stand-in: set_span_in_context returns the span itself."""
    otel = types.ModuleType("opentelemetry")
    trace = types.ModuleType("opentelemetry.trace")
    trace.set_span_in_context = lambda span: span
    trace.StatusCode = types.SimpleNamespace(OK="OK", ERROR="ERROR")
    otel.trace = trace
    return otel


def test_otel_sink_maps_events_to_spans(monkeypatch):
    monkeypatch.setitem(sys.modules, "opentelemetry", _fake_otel())
    tracer = _Tracer()
    sink = OtelTraceSink(tracer=tracer)
    for e in [
        ev(0, "lead", "start", "digest"),
        ev(1, "lead", "llm_call", "local-fast"),
        ev(2, "lead", "delegate", "d1 -> stats"),
        ev(3, "lead/stats", "start", "analyse"),
        ev(4, "lead/stats", "end", "ok"),
        ev(5, "lead", "end", "ok"),
    ]:
        sink(e)
    sink.close()
    lead, llm, stats = tracer.spans[0], tracer.spans[1], tracer.spans[2]
    assert lead.name == "lead" and lead.parent is None and lead.attributes == {"agent_fabric.path": "lead"}
    assert llm.name == "llm_call" and llm.parent is lead and llm.ended
    assert stats.parent is lead and stats.ended
    assert lead.ended and lead.status == "OK"
    # 'delegate' was the event after 'llm_call' at path 'lead': it closed the llm span, then was recorded
    assert ("delegate", {"agent_fabric.detail": "d1 -> stats"}) in lead.events


def test_otel_sink_marks_failed_runs_and_close_drains(monkeypatch):
    monkeypatch.setitem(sys.modules, "opentelemetry", _fake_otel())
    tracer = _Tracer()
    sink = OtelTraceSink(tracer=tracer)
    for e in [ev(0, "lead", "start"), ev(1, "lead", "error", "budget: exceeded")]:
        sink(e)
    sink.close()  # no 'end' event: close() drains the open span
    assert tracer.spans[0].status == "ERROR" and tracer.spans[0].ended
    assert tracer.spans[0].events == [("error", {"agent_fabric.detail": "budget: exceeded"})]


def test_otel_tracer_resolution():
    """Without the 'otel' extra the sink raises a typed error; with it, the default tracer resolves."""
    if importlib.util.find_spec("opentelemetry") is None:
        with pytest.raises(DependencyError):
            OtelTraceSink()(ev(0, "lead", "start"))
    else:
        from agent_fabric.trace import default_otel_tracer

        assert default_otel_tracer() is not None


def test_every_public_name_documented():
    from agent_fabric import trace

    assert trace.__all__
    for name in trace.__all__:
        assert getattr(trace, name).__doc__
