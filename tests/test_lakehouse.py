"""Lakehouse domain: schema inference, medallion design, DAG rendering, static check and an execution smoke test."""

import csv
import json
import sys
import types

import pytest

from agent_fabric import build_registry
from agent_fabric.errors import DataValidationError, PlanValidationError
from agent_fabric.executor import PipelineExecutor
from agent_fabric.pipeline import PipelineInputs, parse_plan
from lake_fabric.domain import register as register_lake

ROWS = [
    {
        "Order ID": str(i),
        "Order Date": f"2026-01-{i % 28 + 1:02d}",
        "Region": ["north", "south"][i % 2],
        "Amount": f"{10 + i}.5",
        "Paid": ["true", "false"][i % 3 == 0],
        "Zip": f"0{i:04d}",
    }
    for i in range(1, 41)
]


@pytest.fixture(scope="module")
def lake():
    return build_registry([register_lake])


@pytest.fixture
def csv_file(tmp_path):
    p = tmp_path / "orders.csv"
    with p.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(ROWS[0]))
        w.writeheader()
        w.writerows(ROWS)
    return p


SOURCE_KEYS = {
    "source_type": "type",
    "path": "path",
    "sheet": "sheet",
    "records_path": "records_path",
    "url": "url",
    "auth_conn_id": "auth_conn_id",
    "mcp_tool": "tool",
    "mcp_arguments": "arguments",
    "delimiter": "delimiter",
}


def params_for(_path=None, **over):
    """Flat keyword arguments -> pipeline params with the shared ``source`` object."""
    base = {
        "source_type": "csv",
        "path": str(_path) if _path else None,
        "dag_id": "ingest_orders",
        "catalog": "lake",
        "table": "orders",
        "business_keys": ["order_id"],
        "partition_column": "order_date",
        "gold_group_by": ["region"],
        "gold_measures": ["amount"],
    }
    base.update(over)
    popped = {k: base.pop(k) for k in list(base) if k in SOURCE_KEYS}
    source = {SOURCE_KEYS[k]: v for k, v in popped.items() if v is not None}
    return {**base, "source": source}


def run_pipeline(lake, params, sample=None):
    spec = lake.pipeline("ingest_to_lakehouse")
    pin = PipelineInputs.from_values({"sample": sample} if sample is not None else {}, lake.types)
    plan = parse_plan(spec.instantiate(params), lake, pin)
    return PipelineExecutor(lake).run(plan, pin)


def test_domain_is_registered(lake):
    assert {"source_inspect", "medallion_plan", "airflow_dag_render", "dag_check"} <= set(lake.names())
    assert {"ingest_to_lakehouse", "medallion_design"} <= set(lake.pipelines())
    assert lake.types.has("python_source")


def test_csv_pipeline_generates_checked_dag(lake, csv_file):
    rep = run_pipeline(lake, params_for(csv_file))
    assert rep.ok, [o.error for o in rep.outcomes if o.error]
    out = rep.output_values()
    types_ = {c["name"]: c["type"] for c in out["schema"]["columns"]}
    assert types_ == {
        "order_id": "bigint",
        "order_date": "date",
        "region": "varchar",
        "amount": "double",
        "paid": "boolean",
        "zip": "varchar",
    }  # leading zeros stay text
    sql = out["layout"]["sql"]
    assert sql["silver_load"][0].startswith('MERGE INTO "lake"."silver"."orders"')
    assert "partitioning = ARRAY['day(order_date)']" in sql["ddl"][4]
    assert sql["gold_refresh"].startswith('CREATE OR REPLACE TABLE "lake"."gold"."orders_summary"')
    compile(out["dag_code"], "dag.py", "exec")
    json.dumps(rep.model_dump(mode="json"))


def test_xlsx_json_api_and_mcp_sources(lake, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(list(ROWS[0]))
    for r in ROWS:
        ws.append(list(r.values()))
    wb.save(tmp_path / "o.xlsx")
    js = tmp_path / "o.json"
    js.write_text(
        json.dumps({"data": {"items": [{"id": i, "when": "2026-01-01T10:00:00Z", "v": i * 1.5} for i in range(30)]}})
    )
    records = [{"id": i, "when": "2026-01-01T10:00:00Z", "v": i * 1.5} for i in range(30)]
    cases = [
        (dict(source_type="xlsx", path=str(tmp_path / "o.xlsx")), None, "load_workbook"),
        (
            dict(
                source_type="json",
                path=str(js),
                records_path="data.items",
                business_keys=["id"],
                partition_column=None,
                gold_group_by=[],
                gold_measures=["v"],
            ),
            None,
            "json.load",
        ),
        (
            dict(
                source_type="api",
                url="https://api.example.com/v1/x",
                auth_conn_id="x_api",
                records_path="data.items",
                business_keys=["id"],
                partition_column=None,
                gold_group_by=[],
                gold_measures=["v"],
            ),
            records,
            "requests.request",
        ),
        (
            dict(
                source_type="mcp",
                url="https://mcp.example.com/mcp",
                mcp_tool="list_items",
                mcp_arguments={"limit": 10},
                business_keys=["id"],
                partition_column=None,
                gold_group_by=[],
                gold_measures=["v"],
            ),
            records,
            "tools/call",
        ),
    ]
    for over, sample, marker in cases:
        rep = run_pipeline(lake, params_for(**over), sample)
        assert rep.ok, (over["source_type"], [o.error for o in rep.outcomes if o.error])
        assert marker in rep.output_values()["dag_code"]


def test_api_source_needs_sample(lake):
    rep = run_pipeline(lake, params_for(source_type="api", url="https://a.example.com/x"))
    assert not rep.ok
    err = next(o.error for o in rep.outcomes if o.error)
    assert "sample_required" in json.dumps(err.model_dump(mode="json"))


def test_design_errors_are_located_with_hints(lake, csv_file):
    rep = run_pipeline(
        lake, params_for(csv_file, business_keys=["ordr_id"], gold_measures=["region"], partition_column="region")
    )
    err = next(o.error for o in rep.outcomes if o.error)
    d = {(".".join(map(str, e.loc)), e.type): e for e in err.details}
    assert "order_id" in d[("params.business_keys.0", "column_not_found")].hint
    assert ("params.gold_measures.0", "not_numeric") in d
    assert ("params.partition_column", "not_temporal") in d


def test_merge_requires_keys_and_identifiers_are_validated(lake, csv_file):
    rep = run_pipeline(lake, params_for(csv_file, business_keys=[]))
    assert any("keys_required" in json.dumps(o.error.model_dump(mode="json")) for o in rep.outcomes if o.error)
    with pytest.raises(PlanValidationError):
        parse_plan(
            lake.pipeline("ingest_to_lakehouse").instantiate(params_for(csv_file, table='orders"; DROP TABLE x;--')),
            lake,
            PipelineInputs.from_values({}, lake.types),
        )


def test_render_rejects_credentials_in_url(lake):
    rep = run_pipeline(
        lake,
        params_for(
            source_type="api",
            url="https://u:p@a.example.com/x?token=abc",
            business_keys=["id"],
            partition_column=None,
            gold_group_by=[],
            gold_measures=[],
        ),
        [{"id": i} for i in range(25)],
    )
    assert "credentials_in_url" in json.dumps([o.error.model_dump(mode="json") for o in rep.outcomes if o.error])


def test_dag_check_finds_every_problem(lake):
    bad = (
        "import subprocess\nimport pandas\npassword = 'hunter2hunter2'\n"
        "def f():\n    eval('1')\n    subprocess.run(['ls'])\n    return 'DROP SCHEMA x'\n"
    )
    comp = lake.get("dag_check")
    from agent_fabric.component import ArtifactStore, StepContext

    with pytest.raises(DataValidationError) as ei:
        comp.execute({"code": bad}, {}, StepContext(ArtifactStore(), "c", comp.spec, lake.types))
    kinds = {d.type for d in ei.value.details}
    assert {"import_not_allowed", "forbidden_call", "hardcoded_secret", "destructive_sql", "no_dag"} <= kinds
    with pytest.raises(DataValidationError) as ei:
        comp.execute({"code": "def broken(:\n"}, {}, StepContext(ArtifactStore(), "c", comp.spec, lake.types))
    assert ei.value.details[0].type == "python_syntax_error"


# --------------------------------------------------------------------------- execute the generated DAG with stubs
RUN = {"id": "scheduled__2026-01-01"}


class FakeTrino:
    calls: list = []
    count_answers: dict = {}

    def __init__(self, trino_conn_id):
        assert trino_conn_id == "trino_default"

    def run(self, sql, parameters=None):
        FakeTrino.calls.append((sql, parameters))

    def get_records(self, sql, parameters=None):
        FakeTrino.calls.append((sql, parameters))
        if "max(" in sql:
            return [(FakeTrino.count_answers.get("watermark"),)]
        return [(FakeTrino.count_answers.get("nulls" if "IS NULL" in sql else "rows", 0),)]


@pytest.fixture
def airflow_stub(monkeypatch):
    def passthrough_dag(**kw):
        return lambda fn: fn

    class AirflowFailException(Exception):
        pass

    sdk = types.ModuleType("airflow.sdk")
    sdk.get_current_context = lambda: {"run_id": RUN["id"]}
    sdk.dag, sdk.task, sdk.BaseHook = (
        passthrough_dag,
        (lambda fn: fn),
        types.SimpleNamespace(get_connection=lambda cid: types.SimpleNamespace(password="tkn")),
    )
    mods = {
        "airflow": types.ModuleType("airflow"),
        "airflow.sdk": sdk,
        "airflow.exceptions": types.SimpleNamespace(AirflowFailException=AirflowFailException),
        "airflow.providers": types.ModuleType("airflow.providers"),
        "airflow.providers.trino": types.ModuleType("airflow.providers.trino"),
        "airflow.providers.trino.hooks": types.ModuleType("airflow.providers.trino.hooks"),
        "airflow.providers.trino.hooks.trino": types.SimpleNamespace(TrinoHook=FakeTrino),
    }
    for k, v in mods.items():
        monkeypatch.setitem(sys.modules, k, v)
    FakeTrino.calls, FakeTrino.count_answers = [], {"rows": 40, "nulls": 0}
    return AirflowFailException


def load_dag(code):
    ns: dict = {"__name__": "generated_dag"}
    exec(compile(code, "generated_dag.py", "exec"), ns)  # test-only: runs code produced by our own renderer
    return ns


def test_generated_csv_dag_runs_end_to_end(lake, csv_file, airflow_stub):
    code = run_pipeline(lake, params_for(csv_file)).output_values()["dag_code"]
    load_dag(code)  # the module-level @dag call runs every task in order (stubs are pass-through)
    sqls = [c[0] for c in FakeTrino.calls]
    assert sqls[0].startswith('CREATE SCHEMA IF NOT EXISTS "lake"."bronze"')
    inserts = [c for c in FakeTrino.calls if c[0].startswith('INSERT INTO "lake"."bronze"."orders"')]
    assert len(inserts) == 1 and len(inserts[0][1]) == 40 * (6 + 3)
    batch = inserts[0][1][6]
    resets = [c for c in FakeTrino.calls if c[0].startswith('DELETE FROM "lake"."bronze"."orders"')]
    assert resets == [(resets[0][0], [batch])]  # the batch is cleared before it is loaded
    assert inserts[0][1][0] == "1" and inserts[0][1][1] == "2026-01-02" and inserts[0][1][4] == "true"
    assert any(s.startswith("MERGE INTO") and p == [batch] for s, p in FakeTrino.calls)
    assert sqls[-1].startswith("CREATE OR REPLACE TABLE")


def test_quality_gate_stops_empty_and_null_key_loads(lake, csv_file, airflow_stub):
    code = run_pipeline(lake, params_for(csv_file)).output_values()["dag_code"]
    FakeTrino.count_answers = {"rows": 0}
    with pytest.raises(airflow_stub, match="no rows"):
        load_dag(code)
    FakeTrino.calls, FakeTrino.count_answers = [], {"rows": 5, "nulls": 2}
    with pytest.raises(airflow_stub, match="null business key"):
        load_dag(code)
    assert not any(s.startswith("MERGE") for s, _ in FakeTrino.calls)


def test_generated_api_dag_reads_records_with_bearer_token(lake, airflow_stub, monkeypatch):
    records = [{"id": i, "v": i * 1.5} for i in range(25)]
    seen = {}

    def fake_request(method, url, params=None, headers=None, timeout=None):
        seen.update(method=method, url=url, headers=headers)
        return types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"data": {"items": records}})

    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(request=fake_request))
    code = run_pipeline(
        lake,
        params_for(
            source_type="api",
            url="https://api.example.com/v1/x",
            auth_conn_id="x_api",
            records_path="data.items",
            business_keys=["id"],
            partition_column=None,
            gold_group_by=[],
            gold_measures=["v"],
        ),
        records,
    ).output_values()["dag_code"]
    load_dag(code)
    assert seen["headers"]["Authorization"] == "Bearer tkn" and seen["method"] == "GET"
    assert "tkn" not in code


# --------------------------------------------------------------------------- agents
def test_lakehouse_team_runs_engineer_then_reviewer(lake, csv_file):
    from pathlib import Path

    from agent_fabric.agents import AgentFabric, AgentsConfig
    from agent_fabric.llm import ScriptedBackend
    from lake_fabric.schemas import DagReview

    plan = lake.pipeline("ingest_to_lakehouse").instantiate(params_for(csv_file))
    plan["objective"] = "Ingest the orders CSV into the lakehouse"
    review = {
        "verdict": "approved",
        "summary": "Keys are defined and the design keeps raw data in bronze.",
        "issues": [],
    }
    backend = ScriptedBackend([json.dumps(plan), json.dumps(review)])
    cfg = AgentsConfig.load(Path(__file__).resolve().parents[1] / "config" / "lakehouse")
    fabric = AgentFabric(lake, cfg, backend=backend)
    fabric.register_schema("DagReview", DagReview)
    assert not fabric.validate()
    report = fabric.run("Ingest orders.csv into lake.orders with order_id as key")
    assert report.result.status == "ok", report.result
    assert [c.status for c in report.result.children] == ["ok", "ok"]
    assert "dag_code" in json.dumps(report.result.children[0].output)


def test_retry_of_the_same_run_reuses_the_batch_id(lake, csv_file, airflow_stub):
    code = run_pipeline(lake, params_for(csv_file, load_mode="append")).output_values()["dag_code"]

    def batch_of_run(run_id):
        RUN["id"] = run_id
        FakeTrino.calls = []
        load_dag(code)
        return next(c[1][0] for c in FakeTrino.calls if c[0].startswith('DELETE FROM "lake"."bronze"'))

    first, retry, other = batch_of_run("r1"), batch_of_run("r1"), batch_of_run("r2")
    assert first == retry and first != other
    silver = [c for c in FakeTrino.calls if c[0].startswith('DELETE FROM "lake"."silver"')]
    assert silver and silver[0][1] == [other]  # append mode clears its own batch before inserting


def test_generated_select_matches_the_component_helper(lake, csv_file, airflow_stub):
    from lake_fabric.components import _select

    ns = load_dag(run_pipeline(lake, params_for(csv_file)).output_values()["dag_code"])
    good = [
        ({"data": {"items": [{"a": 1}]}}, "data.items"),
        ({"a": 1}, None),
        ([{"a": 1}, {"a": 2}], ""),
        ({"x": {"y": [{"a": 1}]}}, "x.y"),
    ]
    for payload, path in good:
        assert ns["_select"](payload, path) == _select(payload, path)
    for payload, path in [({"a": 1}, "missing"), ({"data": 5}, "data"), ([1, 2], "x")]:
        with pytest.raises(Exception):
            ns["_select"](payload, path)
        with pytest.raises(ValueError):
            _select(payload, path)


# --------------------------------------------------------------------------- pagination and incremental loads
API = {
    "source_type": "api",
    "url": "https://api.example.com/v1/items",
    "records_path": "items",
    "business_keys": ["id"],
    "partition_column": None,
    "gold_group_by": [],
    "gold_measures": ["v"],
}
SAMPLE = [{"id": i, "v": i * 1.5, "updated_at": f"2026-02-{i % 27 + 1:02d}T10:00:00Z"} for i in range(25)]


def api_params(pagination=None, **over):
    p = params_for(**{**API, **over})
    if pagination:
        p["source"]["pagination"] = pagination
    return p


class FakeApi:
    """Serves ``pages`` in order and records every request."""

    def __init__(self, pages):
        self.pages, self.requests = pages, []

    def request(self, method, url, params=None, headers=None, timeout=None):
        self.requests.append((url, dict(params or {})))
        body = (
            self.pages[min(len(self.requests) - 1, len(self.pages) - 1)]
            if callable(self.pages) is False
            else self.pages(url, params)
        )
        return types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: body)


def render_api(lake, params):
    return run_pipeline(lake, params, SAMPLE).output_values()["dag_code"]


def run_api_dag(lake, monkeypatch, params, pages):
    api = FakeApi(pages)
    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(request=api.request))
    load_dag(render_api(lake, params))
    return api


def test_cursor_pagination_collects_every_page(lake, airflow_stub, monkeypatch):
    pages = [
        {"items": SAMPLE[:10], "meta": {"next": "c2"}},
        {"items": SAMPLE[10:20], "meta": {"next": "c3"}},
        {"items": SAMPLE[20:], "meta": {"next": None}},
    ]
    api = run_api_dag(
        lake, monkeypatch, api_params({"mode": "cursor", "next_path": "meta.next", "cursor_param": "cursor"}), pages
    )
    assert [r[1].get("cursor") for r in api.requests] == [None, "c2", "c3"]
    inserts = [c for c in FakeTrino.calls if c[0].startswith('INSERT INTO "lake"."bronze"')]
    assert len(inserts[0][1]) == 25 * 6  # id, v, updated_at + 3 metadata columns, twenty-five rows


def test_page_number_pagination_stops_on_empty_page(lake, airflow_stub, monkeypatch):
    pages = [{"items": SAMPLE[:15]}, {"items": SAMPLE[15:]}, {"items": []}]
    api = run_api_dag(
        lake,
        monkeypatch,
        api_params({"mode": "page", "page_param": "page", "page_size_param": "per_page", "page_size": 15}),
        pages,
    )
    assert [(r[1]["page"], r[1]["per_page"]) for r in api.requests] == [(1, 15), (2, 15), (3, 15)]


def test_next_link_stays_on_the_same_host(lake, airflow_stub, monkeypatch):
    good = lambda url, params: (
        {"items": SAMPLE[:12], "links": {"next": "https://api.example.com/v1/items?page=2"}}
        if "page=2" not in url
        else {"items": SAMPLE[12:], "links": {"next": None}}
    )
    api = run_api_dag(lake, monkeypatch, api_params({"mode": "next_link", "next_path": "links.next"}), good)
    assert [r[0] for r in api.requests] == [
        "https://api.example.com/v1/items",
        "https://api.example.com/v1/items?page=2",
    ]
    assert api.requests[1][1] == {}  # the link carries its own query
    evil = lambda url, params: {"items": SAMPLE[:12], "links": {"next": "https://evil.example.net/steal"}}
    with pytest.raises(airflow_stub, match="another host"):
        run_api_dag(lake, monkeypatch, api_params({"mode": "next_link", "next_path": "links.next"}), evil)


def test_running_out_of_pages_fails_instead_of_loading_partial_data(lake, airflow_stub, monkeypatch):
    endless = lambda url, params: {"items": SAMPLE[:5], "meta": {"next": "again"}}
    with pytest.raises(airflow_stub, match="did not finish"):
        run_api_dag(
            lake,
            monkeypatch,
            api_params({"mode": "cursor", "next_path": "meta.next", "cursor_param": "c", "max_pages": 3}),
            endless,
        )
    assert not any(c[0].startswith("MERGE") for c in FakeTrino.calls)


def test_incremental_load_filters_and_passes_the_watermark(lake, airflow_stub, monkeypatch):
    from datetime import datetime

    FakeTrino.count_answers = {"rows": 5, "nulls": 0, "watermark": datetime(2026, 2, 10, 10, 0, 0)}
    params = api_params(watermark_column="updated_at", watermark_param="updated_since")
    api = run_api_dag(lake, monkeypatch, params, [{"items": SAMPLE}])
    assert api.requests[0][1]["updated_since"] == "2026-02-10 10:00:00.000000"
    inserts = [c for c in FakeTrino.calls if c[0].startswith('INSERT INTO "lake"."bronze"')]
    kept = len(inserts[0][1]) // 6
    assert kept == sum(int(r["updated_at"][8:10]) >= 10 for r in SAMPLE) and 0 < kept < 25  # boundary day is kept (>=)


def test_incremental_first_run_reads_everything_and_empty_increment_is_ok(lake, airflow_stub, monkeypatch):
    params = api_params(watermark_column="updated_at")
    FakeTrino.count_answers = {"rows": 25, "nulls": 0, "watermark": None}
    api = run_api_dag(lake, monkeypatch, params, [{"items": SAMPLE}])
    assert "updated_since" not in api.requests[0][1]
    assert len([c for c in FakeTrino.calls if c[0].startswith('INSERT INTO "lake"."bronze"')][0][1]) == 25 * 6
    from datetime import datetime

    FakeTrino.calls, FakeTrino.count_answers = [], {"rows": 0, "nulls": 0, "watermark": datetime(2030, 1, 1)}
    load_dag(render_api(lake, params))  # nothing newer than 2030: the gate must not fail the run
    assert any(c[0].startswith("MERGE") for c in FakeTrino.calls)


def test_pagination_and_watermark_misconfiguration_is_reported(lake):
    def kinds(params, sample=SAMPLE):
        rep = run_pipeline(lake, params, sample)
        return {d.type: d for o in rep.outcomes if o.error for d in o.error.details}

    k = kinds(api_params({"mode": "cursor", "next_path": "meta.next"}))
    assert "pagination_field_required" in k and k["pagination_field_required"].loc[-1] == "cursor_param"
    assert "pagination_not_supported" in kinds(
        params_for(
            source_type="mcp",
            url="https://m.example.com/x",
            mcp_tool="t",
            business_keys=["id"],
            partition_column=None,
            gold_group_by=[],
            gold_measures=[],
        )
        | {
            "source": {
                "type": "mcp",
                "url": "https://m.example.com/x",
                "tool": "t",
                "pagination": {"mode": "page", "page_param": "p"},
            }
        }
    )
    bad_col = kinds(api_params(watermark_column="updatd_at"))
    assert "updated_at" in bad_col["column_not_found"].hint
    text_ids = [{"id": f"x{i}"} for i in range(25)]
    assert "watermark_not_orderable" in kinds(api_params(watermark_column="id", gold_measures=[]), text_ids)
    assert "incremental_needs_merge" in kinds(api_params(watermark_column="updated_at", load_mode="append"))
    assert "watermark_column_required" in kinds(api_params(watermark_param="since"))
