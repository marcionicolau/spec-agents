"""Async and streaming LLM backends: scripted, sync adapter, metering and the proxy client (local fake server)."""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agent_fabric.agents.runtime import Budget, BudgetSettings, RunContext
from agent_fabric.errors import BudgetExceeded, DependencyError
from agent_fabric.llm import LiteLLMProxyBackend, LLMSettings, ScriptedBackend, SyncToAsyncBackend

MSG = [{"role": "user", "content": "hi"}]


async def collect(stream) -> list[str]:
    return [d async for d in stream]


def test_scripted_async_matches_sync_and_records_calls():
    b = ScriptedBackend(["one", "second answer that is long"])
    assert asyncio.run(b.acomplete(MSG)) == "one"
    chunks = asyncio.run(collect(b.astream(MSG, model="m")))
    assert "".join(chunks) == "second answer that is long"
    assert len(chunks) > 1
    assert [c["model"] for c in b.calls] == [None, "m"]


def test_sync_adapter_runs_complete_in_thread_and_streams_one_delta():
    b = SyncToAsyncBackend(ScriptedBackend(["a", "b"]))
    assert asyncio.run(b.acomplete(MSG)) == "a"
    assert asyncio.run(collect(b.astream(MSG))) == ["b"]


def test_metered_async_charges_once_per_call_and_traces():
    ctx = RunContext(session_id="s", budget=Budget(BudgetSettings(max_llm_calls=2)))
    m = ctx.metered(ScriptedBackend(["x", "yyyy", "z"]), "root/a")
    assert asyncio.run(m.acomplete(MSG)) == "x"
    assert "".join(asyncio.run(collect(m.astream(MSG)))) == "yyyy"
    assert ctx.budget.llm_calls == 2 and ctx.llm_calls_by_path["root/a"] == 2
    assert [e.event for e in ctx.trace] == ["llm_call", "llm_call"]
    with pytest.raises(BudgetExceeded):
        asyncio.run(m.acomplete(MSG))


def test_metered_wraps_plain_sync_backend():
    class Plain:
        def complete(self, messages, **kw):
            return "plain"

    ctx = RunContext(session_id="s", budget=Budget(BudgetSettings()))
    m = ctx.metered(Plain(), "p")
    assert asyncio.run(m.acomplete(MSG)) == "plain"
    assert asyncio.run(collect(m.astream(MSG))) == ["plain"]


def test_metered_concurrent_calls_do_not_race_on_budget():
    ctx = RunContext(session_id="s", budget=Budget(BudgetSettings(max_llm_calls=60)))

    async def go() -> list[str]:
        ms = [ctx.metered(ScriptedBackend([f"r{i}"]), f"p{i}") for i in range(10)]
        return await asyncio.gather(*(m.acomplete(MSG) for m in ms))

    assert asyncio.run(go()) == [f"r{i}" for i in range(10)]
    assert ctx.budget.llm_calls == 10


class _Handler(BaseHTTPRequestHandler):
    mode = "ok"

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.mode == "http500":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"boom")
            return
        self.send_response(200)
        if body.get("stream"):
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            events = ["Hel", "lo ", "world"] if self.mode == "ok" else None
            for part in events or []:
                self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {"content": part}}]}).encode() + b"\n\n")
            if events is None:
                self.wfile.write(b"data: not-json\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"choices": [{"message": {"content": "Hello world"}}]}).encode())


@pytest.fixture
def proxy():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _Handler.mode = "ok"
    yield LiteLLMProxyBackend(LLMSettings(base_url=f"http://127.0.0.1:{srv.server_port}/v1", timeout_s=5))
    srv.shutdown()
    srv.server_close()


def test_proxy_acomplete_and_astream(proxy):
    assert asyncio.run(proxy.acomplete(MSG)) == "Hello world"
    assert asyncio.run(collect(proxy.astream(MSG))) == ["Hel", "lo ", "world"]


def test_proxy_astream_errors_are_dependency_errors(proxy):
    _Handler.mode = "http500"
    with pytest.raises(DependencyError) as e:
        asyncio.run(collect(proxy.astream(MSG)))
    assert e.value.report.details[0].type == "http_error"
    _Handler.mode = "garbage"
    with pytest.raises(DependencyError) as e:
        asyncio.run(collect(proxy.astream(MSG)))
    assert e.value.report.details[0].type == "bad_response"


def test_proxy_astream_unreachable():
    b = LiteLLMProxyBackend(LLMSettings(base_url="http://127.0.0.1:1/v1", timeout_s=2))
    with pytest.raises(DependencyError) as e:
        asyncio.run(collect(b.astream(MSG)))
    assert e.value.report.details[0].type == "connection_error"


def test_proxy_sync_stream(proxy):
    assert list(proxy.stream(MSG)) == ["Hel", "lo ", "world"]


def test_metered_complete_streams_to_on_delta_and_returns_same_text():
    seen: list[tuple[str, str]] = []
    ctx = RunContext(session_id="s", budget=Budget(BudgetSettings()), on_delta=lambda p, t: seen.append((p, t)))
    text = "a fairly long scripted answer"
    assert ctx.metered(ScriptedBackend([text]), "root/w").complete(MSG) == text
    assert len(seen) > 1 and {p for p, _ in seen} == {"root/w"} and "".join(t for _, t in seen) == text
    assert ctx.budget.llm_calls == 1


def test_metered_without_listener_or_stream_support_does_not_stream():
    class Plain:
        def complete(self, messages, **kw):
            return "plain"

    seen: list[str] = []
    ctx = RunContext(session_id="s", budget=Budget(BudgetSettings()), on_delta=lambda p, t: seen.append(t))
    assert ctx.metered(Plain(), "p").complete(MSG) == "plain" and seen == []
    quiet = RunContext(session_id="s", budget=Budget(BudgetSettings()))
    assert quiet.metered(ScriptedBackend(["x"]), "p").complete(MSG) == "x"
