"""Lakehouse components: inspect a source, design the medallion layers, render the DAG, check the code."""

from __future__ import annotations

import ast
import csv
import json
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_fabric.component import Component, ComponentParams, ComponentResult, Num, StepContext
from agent_fabric.errors import DependencyError, ErrorDetail, suggest
from agent_fabric.registry import component

from .medallion import IDENT, NUMERIC, build_layout, merge_kinds, sanitize, value_kind
from .render import TASKS, render_dag

SourceType = Literal["csv", "json", "xlsx", "api", "mcp"]
FILE_SUFFIXES = {"csv": {".csv", ".tsv", ".txt"}, "json": {".json", ".jsonl"}, "xlsx": {".xlsx", ".xlsm"}}


def _ident(v: str) -> str:
    if not IDENT.match(v):
        raise ValueError(
            f"{v!r} is not a valid identifier (lower-case letters, digits, underscore; starts with a letter)"
        )
    return v


# ============================================================================ shared source description
_DOTTED = r"^[A-Za-z0-9_\-]+(\.[A-Za-z0-9_\-]+)*$"


class Pagination(BaseModel):
    """How an API is paged. ``next_link``: the response holds the URL of the next page; ``cursor``: it holds a token
    sent back as ``cursor_param``; ``page``: page numbers from 1 in ``page_param`` until an empty page."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["next_link", "cursor", "page"]
    next_path: str | None = Field(
        None, pattern=_DOTTED, description="dotted path of the next link or cursor in the response"
    )
    cursor_param: str | None = Field(None, pattern=r"^[A-Za-z0-9_\-.]+$")
    page_param: str | None = Field(None, pattern=r"^[A-Za-z0-9_\-.]+$")
    page_size_param: str | None = Field(None, pattern=r"^[A-Za-z0-9_\-.]+$")
    page_size: int | None = Field(None, ge=1, le=10000)
    max_pages: int = Field(
        100, ge=1, le=1000, description="more pages than this fails the run instead of loading partial data"
    )


class SourceConfig(BaseModel):
    """Where the data comes from. One object shared by ``source_inspect`` and ``airflow_dag_render``."""

    model_config = ConfigDict(extra="forbid")

    type: SourceType
    path: str | None = None
    sheet: str | None = None
    delimiter: str = Field(",", min_length=1, max_length=1)
    encoding: str = "utf-8"
    url: str | None = None
    method: Literal["GET", "POST"] = "GET"
    query: dict[str, str] = Field(default_factory=dict)
    auth_conn_id: str | None = Field(None, pattern=r"^[A-Za-z0-9_\-.]+$")
    timeout: int = Field(60, ge=1, le=600)
    records_path: str | None = Field(None, pattern=r"^[A-Za-z0-9_\-]+(\.[A-Za-z0-9_\-]+)*$")
    pagination: Pagination | None = None
    tool: str | None = Field(None, pattern=r"^[A-Za-z0-9_\-.]+$", description="MCP tool name (mcp sources)")
    arguments: dict[str, Any] = Field(default_factory=dict, description="MCP tool arguments (mcp sources)")


# ============================================================================ source_inspect
class SourceInspectParams(ComponentParams):
    source: SourceConfig
    sample_rows: int = Field(200, ge=1, le=5000)


class ColumnInfo(BaseModel):
    name: str
    source_name: str
    type: str
    null_rate: Num = None


class SourceInspectResult(ComponentResult):
    source_type: str
    n_sampled: int
    columns: list[ColumnInfo]


def _select(data: Any, records_path: str | None) -> list[dict]:
    for key in filter(None, (records_path or "").split(".")):
        try:
            data = data[key]
        except (KeyError, TypeError, IndexError):
            raise ValueError(f"records_path {records_path!r} not found in the payload (stopped at {key!r})") from None
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
        raise ValueError("records must be a list of JSON objects")
    return data


@component("source_inspect")
class SourceInspect(Component[SourceInspectParams, SourceInspectResult]):
    Params = SourceInspectParams
    Result = SourceInspectResult

    def extra_checks(self, inputs: dict, params: SourceInspectParams) -> list[ErrorDetail]:
        src, loc = params.source, ("params", "source")
        if src.type in FILE_SUFFIXES:
            if not src.path:
                return (
                    [
                        ErrorDetail(
                            loc=loc + ("path",),
                            type="path_required",
                            msg=f"{src.type} needs a local path",
                            hint="set source.path, or pass a `sample` of records",
                        )
                    ]
                    if inputs.get("sample") is None
                    else []
                )
            p = Path(src.path)
            if p.suffix.lower() not in FILE_SUFFIXES[src.type]:
                return [
                    ErrorDetail(
                        loc=loc + ("path",),
                        type="wrong_extension",
                        msg=f"{p.suffix or 'no extension'} is not a {src.type} file",
                        hint=f"expected one of {sorted(FILE_SUFFIXES[src.type])}",
                    )
                ]
            if not p.is_file():
                return [
                    ErrorDetail(
                        loc=loc + ("path",),
                        type="file_not_found",
                        msg=f"{src.path} does not exist",
                        hint="use the path as seen by the machine running this step",
                    )
                ]
        elif inputs.get("sample") is None:
            return [
                ErrorDetail(
                    loc=("inputs", "sample"),
                    type="sample_required",
                    msg=f"{src.type} sources cannot be read here; provide a sample of records",
                    hint="bind `sample` to a JSON list of example records",
                )
            ]
        return []

    def _records(self, inputs: dict, params: SourceInspectParams) -> list[dict]:
        src = params.source
        if inputs.get("sample") is not None:
            sample = inputs["sample"]  # a list is already the records; an envelope is unwrapped with records_path
            return _select(sample, src.records_path if isinstance(sample, dict) else None)[: params.sample_rows]
        path = Path(src.path or "")
        if src.type == "csv":
            with path.open(newline="", encoding=src.encoding) as fh:
                reader = csv.DictReader(fh, delimiter=src.delimiter)
                return [row for _, row in zip(range(params.sample_rows), reader)]
        if src.type == "json":
            with path.open(encoding=src.encoding) as fh:
                if path.suffix.lower() == ".jsonl":
                    data = [json.loads(line) for _, line in zip(range(params.sample_rows), fh) if line.strip()]
                else:
                    data = json.load(fh)
            return _select(data, src.records_path)[: params.sample_rows]
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise DependencyError(
                "reading xlsx needs the 'openpyxl' package",
                [ErrorDetail(type="missing_package", msg="openpyxl is not installed", hint="pip install openpyxl")],
            ) from exc
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb[src.sheet] if src.sheet else wb.active
        rows = ws.iter_rows(values_only=True)
        header = [str(h).strip() if h is not None else "" for h in next(rows, ())]
        return [dict(zip(header, r)) for _, r in zip(range(params.sample_rows), rows) if any(v is not None for v in r)]

    def compute(self, inputs: dict, params: SourceInspectParams, ctx: StepContext) -> SourceInspectResult:
        """Infer column names and types of a source from a sample of its records.

        Reads the sample from the declared input or the source itself (CSV, JSON, XLSX, API or MCP tool), merges value kinds per column, sanitises
        column names into safe identifiers and records the null rate. Raises ``ValueError`` when there are no records. Warns about empty columns and
        samples under 20 rows. Emits the ``schema`` output.
        """
        records = self._records(inputs, params)
        if not records:
            raise ValueError("the source has no records to infer a schema from")
        originals: list[str] = []
        for rec in records:
            for k in rec:
                if k not in originals:
                    originals.append(k)
        taken: set[str] = set()
        cols, warns = [], []
        for src in originals:
            vals = [r.get(src) for r in records]
            kind = merge_kinds({value_kind(v) for v in vals})
            nulls = sum(value_kind(v) is None for v in vals)
            if nulls == len(vals):
                warns.append(f"column {src!r} is empty in the sample; typed as varchar")
            cols.append(
                ColumnInfo(name=sanitize(src, taken), source_name=str(src), type=kind, null_rate=nulls / len(vals))
            )
        if len(records) < 20:
            warns.append(f"only {len(records)} sampled rows; inferred types may be wrong")
        ctx.emit("schema", {"columns": [c.model_dump() for c in cols]})
        return SourceInspectResult(source_type=params.source.type, n_sampled=len(records), columns=cols, warnings=warns)

    def summarize(self, r: dict) -> tuple[str, list[str]]:
        return (
            f"{len(r['columns'])} columns inferred from {r['n_sampled']} {r['source_type']} rows.",
            [f"{c['name']}: {c['type']}" for c in r["columns"][:8]],
        )


# ============================================================================ medallion_plan
class MedallionPlanParams(ComponentParams):
    catalog: str
    table: str
    business_keys: list[str] = Field(default_factory=list, max_length=8)
    load_mode: Literal["append", "merge", "overwrite"] = "merge"
    bronze_schema: str = "bronze"
    silver_schema: str = "silver"
    gold_schema: str = "gold"
    partition_column: str | None = None
    gold_group_by: list[str] = Field(default_factory=list, max_length=6)
    gold_measures: list[str] = Field(default_factory=list, max_length=10)

    _idents = field_validator("catalog", "table", "bronze_schema", "silver_schema", "gold_schema")(_ident)


class MedallionPlanResult(ComponentResult):
    tables: dict[str, str]
    load_mode: str
    n_columns: int
    business_keys: list[str]
    gold_group_by: list[str]
    gold_measures: list[str]


@component("medallion_plan")
class MedallionPlan(Component[MedallionPlanParams, MedallionPlanResult]):
    Params = MedallionPlanParams
    Result = MedallionPlanResult

    def extra_checks(self, inputs: dict, params: MedallionPlanParams) -> list[ErrorDetail]:
        cols = {c["name"]: c["type"] for c in inputs["schema"].get("columns", [])}
        errs: list[ErrorDetail] = []

        def known(param: str, values: list[str]) -> None:
            for i, v in enumerate(values):
                if v not in cols:
                    errs.append(
                        ErrorDetail(
                            loc=("params", param, i),
                            type="column_not_found",
                            input=v,
                            msg=f"'{v}' is not a column of the source",
                            hint=suggest(v, cols) or f"columns: {sorted(cols)}",
                        )
                    )

        known("business_keys", params.business_keys)
        known("gold_group_by", params.gold_group_by)
        known("gold_measures", params.gold_measures)
        if params.partition_column is not None:
            known("partition_column", [params.partition_column])
            if cols.get(params.partition_column) not in ("date", "timestamp"):
                errs.append(
                    ErrorDetail(
                        loc=("params", "partition_column"),
                        type="not_temporal",
                        msg="the partition column must be a date or timestamp column",
                        hint="partition on an event date, or leave it null",
                    )
                )
        for i, m in enumerate(params.gold_measures):
            if m in cols and cols[m] not in NUMERIC:
                errs.append(
                    ErrorDetail(
                        loc=("params", "gold_measures", i),
                        type="not_numeric",
                        input=m,
                        msg=f"'{m}' is {cols[m]}, gold measures must be numeric",
                    )
                )
            if m in params.gold_group_by:
                errs.append(
                    ErrorDetail(
                        loc=("params", "gold_measures", i),
                        type="measure_is_group",
                        input=m,
                        msg=f"'{m}' cannot be both a group column and a measure",
                    )
                )
        if params.load_mode == "merge" and not params.business_keys:
            errs.append(
                ErrorDetail(
                    loc=("params", "business_keys"),
                    type="keys_required",
                    msg="merge needs at least one business key",
                    hint="set business_keys or use load_mode 'append'",
                )
            )
        clash = [
            c
            for c in cols
            if c in ("row_count",) or (c.startswith(("avg_", "min_", "max_")) and c[4:] in params.gold_measures)
        ]
        if clash and params.gold_measures:
            errs.append(
                ErrorDetail(
                    loc=("params", "gold_measures"),
                    type="gold_name_clash",
                    msg=f"gold aggregate names clash with source columns {clash}",
                    hint="rename the source columns",
                )
            )
        return errs

    def compute(self, inputs: dict, params: MedallionPlanParams, ctx: StepContext) -> MedallionPlanResult:
        """Design the bronze, silver and gold tables and the SQL that loads them from an inferred schema.

        Delegates to ``build_layout`` with the parameters (catalog, table, schemas, business keys, load mode, partitioning, gold aggregation).
        Emits the ``layout`` output. Warns when there are no business keys, because silver then cannot be de-duplicated and re-runs append duplicates.
        """
        columns = [
            {"name": c["name"], "source_name": c["source_name"], "type": c["type"]} for c in inputs["schema"]["columns"]
        ]
        layout = build_layout(
            catalog=params.catalog,
            table=params.table,
            schemas={"bronze": params.bronze_schema, "silver": params.silver_schema, "gold": params.gold_schema},
            columns=columns,
            business_keys=params.business_keys,
            load_mode=params.load_mode,
            partition_column=params.partition_column,
            gold_group_by=params.gold_group_by,
            gold_measures=params.gold_measures,
        )
        ctx.emit("layout", layout)
        warns = []
        if not params.business_keys:
            warns.append("no business keys: silver cannot be de-duplicated, re-runs will append duplicates")
        return MedallionPlanResult(
            tables=layout["tables"],
            load_mode=params.load_mode,
            n_columns=len(columns),
            business_keys=params.business_keys,
            gold_group_by=params.gold_group_by,
            gold_measures=params.gold_measures,
            warnings=warns,
        )

    def summarize(self, r: dict) -> tuple[str, list[str]]:
        return (
            f"Medallion layers designed for {r['tables']['silver']} ({r['load_mode']}).",
            [f"{layer}: {name}" for layer, name in r["tables"].items()],
        )


# ============================================================================ airflow_dag_render
_CRON = re.compile(r"^(@(hourly|daily|weekly|monthly|yearly)|@once|(\S+\s+){4}\S+)$")


class AirflowDagRenderParams(ComponentParams):
    dag_id: str
    source: SourceConfig
    schedule: str = "@daily"
    start_date: str = Field("2026-01-01", pattern=r"^\d{4}-\d{2}-\d{2}$")
    trino_conn_id: str = Field("trino_default", pattern=r"^[A-Za-z0-9_\-.]+$")
    retries: int = Field(2, ge=0, le=5)
    catchup: bool = False
    tags: list[str] = Field(default_factory=lambda: ["lakehouse", "medallion"], max_length=8)
    watermark_column: str | None = Field(
        None, description="load only records at or after the highest value already in silver"
    )
    watermark_param: str | None = Field(
        None, pattern=r"^[A-Za-z0-9_\-.]+$", description="API query parameter that receives the watermark"
    )

    _dag = field_validator("dag_id")(_ident)


class AirflowDagRenderResult(ComponentResult):
    dag_id: str
    source_type: str
    task_ids: list[str]
    n_lines: int


@component("airflow_dag_render")
class AirflowDagRender(Component[AirflowDagRenderParams, AirflowDagRenderResult]):
    Params = AirflowDagRenderParams
    Result = AirflowDagRenderResult

    def extra_checks(self, inputs: dict, params: AirflowDagRenderParams) -> list[ErrorDetail]:
        errs: list[ErrorDetail] = []
        src, loc = params.source, ("params", "source")
        if not _CRON.match(params.schedule.strip()):
            errs.append(
                ErrorDetail(
                    loc=("params", "schedule"),
                    type="bad_schedule",
                    input=params.schedule,
                    msg="not a preset (@daily, @hourly...) or a 5-field cron expression",
                    hint="e.g. '0 3 * * *'",
                )
            )
        if src.type in FILE_SUFFIXES:
            if not src.path:
                errs.append(
                    ErrorDetail(loc=loc + ("path",), type="path_required", msg=f"{src.type} sources need `path`")
                )
            elif Path(src.path).suffix.lower() not in FILE_SUFFIXES[src.type]:
                errs.append(
                    ErrorDetail(
                        loc=loc + ("path",),
                        type="wrong_extension",
                        msg=f"{src.path} is not a {src.type} file",
                        hint=f"expected {sorted(FILE_SUFFIXES[src.type])}",
                    )
                )
        else:
            u = urlparse(src.url or "")
            if u.scheme not in ("http", "https") or not u.netloc:
                errs.append(
                    ErrorDetail(
                        loc=loc + ("url",),
                        type="bad_url",
                        input=src.url,
                        msg=f"{src.type} sources need an http(s) `url`",
                    )
                )
            elif u.username or u.password or re.search(r"(token|key|secret|password)=", u.query, re.I):
                errs.append(
                    ErrorDetail(
                        loc=loc + ("url",),
                        type="credentials_in_url",
                        msg="credentials must not be embedded in the URL",
                        hint="store them in an Airflow connection and set auth_conn_id",
                    )
                )
            if src.type == "mcp" and not src.tool:
                errs.append(ErrorDetail(loc=loc + ("tool",), type="tool_required", msg="mcp sources need `tool`"))
        pg = src.pagination
        if pg is not None:
            if src.type != "api":
                errs.append(
                    ErrorDetail(
                        loc=loc + ("pagination",),
                        type="pagination_not_supported",
                        msg="pagination applies to api sources only",
                    )
                )
            for need, applies in (
                ("next_path", pg.mode in ("next_link", "cursor")),
                ("cursor_param", pg.mode == "cursor"),
                ("page_param", pg.mode == "page"),
            ):
                if applies and getattr(pg, need) is None:
                    errs.append(
                        ErrorDetail(
                            loc=loc + ("pagination", need),
                            type="pagination_field_required",
                            msg=f"pagination mode '{pg.mode}' needs {need}",
                        )
                    )
            if pg.page_size_param and pg.page_size is None:
                errs.append(
                    ErrorDetail(
                        loc=loc + ("pagination", "page_size"),
                        type="pagination_field_required",
                        msg="page_size_param needs page_size",
                    )
                )
        if params.watermark_param and not params.watermark_column:
            errs.append(
                ErrorDetail(
                    loc=("params", "watermark_param"),
                    type="watermark_column_required",
                    msg="watermark_param needs watermark_column",
                )
            )
        if params.watermark_param and src.type != "api":
            errs.append(
                ErrorDetail(
                    loc=("params", "watermark_param"),
                    type="watermark_param_not_supported",
                    msg="the watermark can only be sent as a query parameter to api sources",
                    hint="other sources are filtered after reading",
                )
            )
        if params.watermark_column:
            cols = {c["name"]: c["type"] for c in inputs["layout"]["columns"]}
            wc = params.watermark_column
            if wc not in cols:
                errs.append(
                    ErrorDetail(
                        loc=("params", "watermark_column"),
                        type="column_not_found",
                        input=wc,
                        msg=f"'{wc}' is not a column of the source",
                        hint=suggest(wc, cols) or f"columns: {sorted(cols)}",
                    )
                )
            elif cols[wc] not in ("bigint", "double", "date", "timestamp"):
                errs.append(
                    ErrorDetail(
                        loc=("params", "watermark_column"),
                        type="watermark_not_orderable",
                        input=wc,
                        msg=f"'{wc}' is {cols[wc]}; a watermark must be numeric, date or timestamp",
                    )
                )
            if inputs["layout"]["load_mode"] != "merge":
                errs.append(
                    ErrorDetail(
                        loc=("params", "watermark_column"),
                        type="incremental_needs_merge",
                        msg=f"incremental loads re-read the boundary rows, so load_mode must be merge (is {inputs['layout']['load_mode']})",
                        hint="set load_mode to merge with business keys in medallion_plan",
                    )
                )
        for k in src.query:
            if re.search(r"(token|key|secret|password)", k, re.I):
                errs.append(
                    ErrorDetail(
                        loc=loc + ("query", k),
                        type="credentials_in_query",
                        msg=f"query parameter '{k}' looks like a credential",
                        hint="use auth_conn_id",
                    )
                )
        return errs

    def compute(self, inputs: dict, params: AirflowDagRenderParams, ctx: StepContext) -> AirflowDagRenderResult:
        """Render the Airflow DAG file for a medallion layout and a source.

        Builds the config from the validated parameters and the ``layout`` input (columns and SQL) and renders it into the static DAG template; no
        value is interpolated into code or SQL text. With ``watermark_column`` the DAG loads incrementally. Emits the ``code`` output; the result
        lists the DAG id, source type, task ids and line count.
        """
        layout = inputs["layout"]
        src = params.source
        source = src.model_dump()
        label = src.path or src.url or src.type
        config = {
            "dag_id": params.dag_id,
            "schedule": params.schedule.strip(),
            "start_date": params.start_date,
            "catchup": params.catchup,
            "retries": params.retries,
            "tags": params.tags,
            "trino_conn_id": params.trino_conn_id,
            "source_label": Path(label).name if src.path else label,
            "source": source,
            "columns": layout["columns"],
            "sql": layout["sql"],
            "watermark": None,
        }
        if params.watermark_column:
            col = next(c for c in layout["columns"] if c["name"] == params.watermark_column)
            config["watermark"] = {
                "column": col["name"],
                "source_name": col["source_name"],
                "type": col["type"],
                "param": params.watermark_param,
                "sql": f'SELECT max("{col["name"]}") FROM {layout["tables"]["silver"]}',
            }
        code = render_dag(config)
        ctx.emit("code", code)
        return AirflowDagRenderResult(
            dag_id=params.dag_id, source_type=src.type, task_ids=list(TASKS), n_lines=code.count("\n")
        )

    def summarize(self, r: dict) -> tuple[str, list[str]]:
        return f"DAG '{r['dag_id']}' generated ({r['n_lines']} lines).", [f"task: {t}" for t in r["task_ids"]]


# ============================================================================ dag_check
ALLOWED_IMPORTS = {
    "__future__",
    "airflow",
    "csv",
    "hashlib",
    "json",
    "logging",
    "urllib",
    "datetime",
    "requests",
    "openpyxl",
    "typing",
}
FORBIDDEN_CALLS = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "os.system",
    "os.popen",
    "pickle.loads",
    "pickle.load",
    "marshal.loads",
    "yaml.load",
}
FORBIDDEN_PREFIXES = ("subprocess.", "os.exec", "os.spawn", "shutil.rmtree", "socket.")
SECRET_PATTERNS = (
    re.compile(r"(?i)(password|passwd|secret|api_?key|token)\s*[:=]\s*['\"][^'\"\s]{4,}['\"]"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}"),
)
DESTRUCTIVE_SQL = re.compile(r"(?i)\b(drop\s+(schema|catalog|database)|truncate\s+table)\b")


class DagCheckParams(ComponentParams):
    extra_imports: list[str] = Field(default_factory=list, description="additional allowed top-level modules")


class DagCheckResult(ComponentResult):
    dag_id: str | None
    task_ids: list[str]
    imports: list[str]
    n_lines: int


def _dotted(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _analyse(code: str, allowed: set[str]) -> tuple[list[ErrorDetail], dict[str, Any]]:
    errs: list[ErrorDetail] = []
    tree = ast.parse(code)
    imports, tasks, dag_id, has_dag = set(), [], None, False
    for node in ast.walk(tree):
        loc = ("inputs", "code", f"line {getattr(node, 'lineno', 0)}")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for m in mods:
                top = m.split(".")[0]
                imports.add(top)
                if top not in allowed:
                    errs.append(
                        ErrorDetail(
                            loc=loc,
                            type="import_not_allowed",
                            input=m,
                            msg=f"import of '{m}' is not allowed",
                            hint=f"allowed: {sorted(allowed)}",
                        )
                    )
        elif isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name in FORBIDDEN_CALLS or name.startswith(FORBIDDEN_PREFIXES):
                errs.append(
                    ErrorDetail(
                        loc=loc, type="forbidden_call", input=name, msg=f"call to '{name}' is not allowed in a DAG file"
                    )
                )
        elif isinstance(node, ast.FunctionDef):
            decos = {_dotted(d.func if isinstance(d, ast.Call) else d) for d in node.decorator_list}
            if "task" in decos:
                tasks.append(node.name)
            if "dag" in decos:
                has_dag = True
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and DESTRUCTIVE_SQL.search(node.value):
            errs.append(
                ErrorDetail(
                    loc=loc,
                    type="destructive_sql",
                    msg="destructive SQL (DROP SCHEMA/CATALOG, TRUNCATE) is not allowed",
                )
            )
    for pat in SECRET_PATTERNS:
        for m in pat.finditer(code):
            errs.append(
                ErrorDetail(
                    loc=("inputs", "code", f"line {code[: m.start()].count(chr(10)) + 1}"),
                    type="hardcoded_secret",
                    msg="looks like a hardcoded credential",
                    hint="use an Airflow connection",
                )
            )
    mid = re.search(r"CONFIG\s*=\s*\{.*?'dag_id':\s*'([^']+)'", code, re.S)
    dag_id = mid.group(1) if mid else None
    if not has_dag:
        errs.append(ErrorDetail(loc=("inputs", "code"), type="no_dag", msg="no function decorated with @dag"))
    missing = [t for t in TASKS if t not in tasks]
    if missing and has_dag:
        errs.append(
            ErrorDetail(
                loc=("inputs", "code"),
                type="missing_tasks",
                msg=f"medallion tasks missing: {missing}",
                hint="every DAG needs " + ", ".join(TASKS),
            )
        )
    return errs, {"dag_id": dag_id, "task_ids": tasks, "imports": sorted(imports)}


@component("dag_check")
class DagCheck(Component[DagCheckParams, DagCheckResult]):
    Params = DagCheckParams
    Result = DagCheckResult

    def extra_checks(self, inputs: dict, params: DagCheckParams) -> list[ErrorDetail]:
        return _analyse(inputs["code"], ALLOWED_IMPORTS | set(params.extra_imports))[0]

    def compute(self, inputs: dict, params: DagCheckParams, ctx: StepContext) -> DagCheckResult:
        """Statically check a generated Airflow DAG file; the checks gate the DAG before it is used.

        Rejects disallowed imports, dangerous calls (``eval``, ``exec``, subprocess), embedded secrets and destructive SQL, and verifies the
        required medallion tasks exist. Warns when ``catchup`` is enabled (backfills every interval) or ``retries`` is 0.
        """
        _, info = _analyse(inputs["code"], ALLOWED_IMPORTS | set(params.extra_imports))
        code = inputs["code"]
        warns = []
        if "catchup': True" in code:
            warns.append("catchup is enabled: the DAG will backfill every interval since start_date")
        if "'retries': 0" in code:
            warns.append("retries is 0: transient Trino or network errors fail the run")
        return DagCheckResult(n_lines=code.count("\n"), warnings=warns, **info)

    def summarize(self, r: dict) -> tuple[str, list[str]]:
        return f"DAG '{r['dag_id']}' passed the static checks.", [f"tasks: {', '.join(r['task_ids'])}"]


__all__ = [
    "AirflowDagRender",
    "AirflowDagRenderParams",
    "AirflowDagRenderResult",
    "ColumnInfo",
    "DagCheck",
    "DagCheckParams",
    "DagCheckResult",
    "MedallionPlan",
    "MedallionPlanParams",
    "MedallionPlanResult",
    "Pagination",
    "SourceConfig",
    "SourceInspect",
    "SourceInspectParams",
    "SourceInspectResult",
    "SourceType",
]
