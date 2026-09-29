"""Pure functions: column naming, type inference and the SQL of the three medallion layers (Trino + Iceberg).

Every identifier that reaches SQL is validated with :data:`IDENT` and double-quoted; values never reach SQL text
(the generated DAG binds them as parameters).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

IDENT = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
META_COLUMNS = ("_batch_id", "_source", "_ingested_at")
TRINO_TYPE = {"varchar": "VARCHAR", "bigint": "BIGINT", "double": "DOUBLE", "boolean": "BOOLEAN",
              "date": "DATE", "timestamp": "TIMESTAMP(6)"}
NUMERIC = {"bigint", "double"}

_INT = re.compile(r"^[+-]?(0|[1-9]\d*)$")
_FLOAT = re.compile(r"^[+-]?((0|[1-9]\d*)(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")


def sanitize(name: str, taken: set[str]) -> str:
    """snake_case identifier, unique within ``taken`` (which is updated)."""
    base = re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_") or "col"
    if not base[0].isalpha():
        base = f"c_{base}"
    base = base[:56]
    out, i = base, 2
    while out in taken:
        out, i = f"{base}_{i}", i + 1
    taken.add(out)
    return out


def value_kind(v: Any) -> str | None:
    """Logical type of one value; None for missing."""
    if v is None:
        return None
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "bigint"
    if isinstance(v, float):
        return "double"
    if isinstance(v, datetime):
        return "timestamp"
    if isinstance(v, date):
        return "date"
    if isinstance(v, (dict, list)):
        return "varchar"
    s = str(v).strip()
    if s == "":
        return None
    if s.lower() in ("true", "false"):
        return "boolean"
    if _INT.match(s):
        return "bigint"
    if _FLOAT.match(s):
        return "double"
    if _DATE.match(s):
        return "date"
    if _TS.match(s):
        return "timestamp"
    return "varchar"


def merge_kinds(kinds: set[str | None]) -> str:
    kinds = {k for k in kinds if k}
    if not kinds:
        return "varchar"
    if len(kinds) == 1:
        return next(iter(kinds))
    if kinds <= NUMERIC:
        return "double"
    if kinds <= {"date", "timestamp"}:
        return "timestamp"
    return "varchar"


def q(ident: str) -> str:
    """Quote a validated identifier."""
    return f'"{ident}"'


def fqn(catalog: str, schema: str, table: str) -> str:
    return ".".join(q(p) for p in (catalog, schema, table))


def _cast(col: dict[str, str]) -> str:
    t = col["type"]
    return q(col["name"]) if t == "varchar" else f'TRY_CAST({q(col["name"])} AS {TRINO_TYPE[t]}) AS {q(col["name"])}'


def build_layout(*, catalog: str, table: str, schemas: dict[str, str], columns: list[dict[str, str]],
                 business_keys: list[str], load_mode: str, partition_column: str | None,
                 gold_group_by: list[str], gold_measures: list[str]) -> dict[str, Any]:
    tables = {layer: fqn(catalog, schemas[layer], table if layer != "gold" else f"{table}_summary")
              for layer in ("bronze", "silver", "gold")}
    names = [c["name"] for c in columns]
    silver_cols = [q(n) for n in names] + [q("_batch_id"), q("_ingested_at")]

    bronze_ddl = (f"CREATE TABLE IF NOT EXISTS {tables['bronze']} ("
                  + ", ".join(f"{q(n)} VARCHAR" for n in names + list(META_COLUMNS)) + ") WITH (format = 'PARQUET')")
    props = "format = 'PARQUET'"
    if partition_column:
        props += f", partitioning = ARRAY['day({partition_column})']"
    silver_ddl = (f"CREATE TABLE IF NOT EXISTS {tables['silver']} ("
                  + ", ".join(f"{q(c['name'])} {TRINO_TYPE[c['type']]}" for c in columns)
                  + f", {q('_batch_id')} VARCHAR, {q('_ingested_at')} TIMESTAMP(6)) WITH ({props})")
    ddl = [f"CREATE SCHEMA IF NOT EXISTS {q(catalog)}.{q(schemas[layer])}" for layer in ("bronze", "silver", "gold")]
    ddl += [bronze_ddl, silver_ddl]

    casts = ", ".join(_cast(c) for c in columns)
    meta = f'{q("_batch_id")}, TRY_CAST({q("_ingested_at")} AS TIMESTAMP(6)) AS {q("_ingested_at")}'
    if business_keys:
        keys = ", ".join(q(k) for k in business_keys)
        source = (f"SELECT {casts}, {meta} FROM (SELECT *, row_number() OVER (PARTITION BY {keys} "
                  f"ORDER BY {q('_ingested_at')} DESC) AS {q('_rn')} FROM {tables['bronze']} WHERE {q('_batch_id')} = ?) WHERE {q('_rn')} = 1")
    else:
        source = f"SELECT {casts}, {meta} FROM {tables['bronze']} WHERE {q('_batch_id')} = ?"

    if load_mode == "merge":
        on = " AND ".join(f"t.{q(k)} = s.{q(k)}" for k in business_keys)
        updates = ", ".join(f"{c} = s.{c}" for c in silver_cols if c.strip('"') not in business_keys)
        silver_load = [f"MERGE INTO {tables['silver']} AS t USING ({source}) AS s ON {on} "
                       f"WHEN MATCHED THEN UPDATE SET {updates} "
                       f"WHEN NOT MATCHED THEN INSERT ({', '.join(silver_cols)}) VALUES ({', '.join('s.' + c for c in silver_cols)})"]
    else:
        silver_load = [f"INSERT INTO {tables['silver']} ({', '.join(silver_cols)}) {source}"]
        if load_mode == "overwrite":
            silver_load.insert(0, f"DELETE FROM {tables['silver']}")
        else:  # append: a retried batch must not insert its rows twice
            silver_load.insert(0, f"DELETE FROM {tables['silver']} WHERE {q('_batch_id')} = ?")

    group = [q(g) for g in gold_group_by]
    aggs = ["count(*) AS row_count"]
    for m in gold_measures:
        aggs += [f"avg({q(m)}) AS {q('avg_' + m)}", f"min({q(m)}) AS {q('min_' + m)}", f"max({q(m)}) AS {q('max_' + m)}"]
    gold = (f"CREATE OR REPLACE TABLE {tables['gold']} AS SELECT {', '.join(group + aggs)} FROM {tables['silver']}"
            + (f" GROUP BY {', '.join(group)}" if group else ""))

    return {
        "catalog": catalog, "load_mode": load_mode, "business_keys": business_keys,
        "tables": tables, "columns": columns, "bronze_columns": names + list(META_COLUMNS),
        "sql": {
            "ddl": ddl,
            "bronze_insert": f"INSERT INTO {tables['bronze']} ({', '.join(q(n) for n in names + list(META_COLUMNS))}) VALUES ",
            "bronze_reset": f"DELETE FROM {tables['bronze']} WHERE {q('_batch_id')} = ?",
            "bronze_count": f"SELECT count(*) FROM {tables['bronze']} WHERE {q('_batch_id')} = ?",
            "bronze_null_keys": {k: f"SELECT count(*) FROM {tables['bronze']} WHERE {q('_batch_id')} = ? AND {q(k)} IS NULL"
                                 for k in business_keys},
            "silver_load": silver_load,
            "gold_refresh": gold,
        },
    }
