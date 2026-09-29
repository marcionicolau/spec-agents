"""Generic core: artifact types, specs, registry contracts, domains, pipelines as components."""

from pathlib import Path

import pytest
from pydantic import Field

from agent_fabric import build_registry
from agent_fabric.component import Component, ComponentParams, ComponentResult
from agent_fabric.errors import SpecError
from agent_fabric.registry import Registry
from agent_fabric.spec import load_spec

from .conftest import run_component

STATS = {"summary", "linear_model", "anova", "time_series", "clustering", "pca"}
STATS_PIPELINES = {"exploratory_analysis", "experiment_analysis", "full_study"}


def test_domains_and_components(registry):
    assert set(registry.domains()) == {"statistics", "text"}
    assert STATS | STATS_PIPELINES <= set(registry.names(["statistics"]))
    assert set(registry.names(["text"])) == {"text_stats", "keywords", "document_digest"}
    assert set(registry.pipelines()) == STATS_PIPELINES | {"document_digest"}


def test_catalog_exposes_ports(registry):
    cat = {c["name"]: c for c in registry.catalog(["statistics"])}
    assert cat["clustering"]["inputs"] == {"data": "dataframe (optional)", "matrix": "dataframe (optional)"}
    assert cat["pca"]["outputs"] == {"result": "json", "scores": "dataframe", "loadings": "dataframe"}
    assert cat["exploratory_analysis"]["outputs"]["labels"] == "series"  # pipeline exposed as component
    assert "keywords" not in cat  # domain filter


def test_type_inference(registry, df, note):
    t = registry.types
    assert t.infer(df).name == "dataframe" and t.infer(note).name == "text"
    assert t.infer({"a": 1}).name == "json" and t.infer(3.2).name == "number"
    assert t.infer(df["ph"]).name == "series"


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text)
    return p


BASE = """
name: x
version: 1.0.0
title: X
description: demo spec
llm: {when_to_use: w}
"""


def test_spec_rejects_unknown_keys_and_reserved_port(tmp_path):
    with pytest.raises(SpecError) as ei:
        load_spec(_write(tmp_path, "a.yaml", BASE + "colour: red\n"))
    assert any(d.loc[-1] == "colour" and d.type == "extra_forbidden" for d in ei.value.details)
    with pytest.raises(SpecError):
        load_spec(_write(tmp_path, "b.yaml", BASE + "outputs: {result: {type: json}}\n"))


def test_pipeline_spec_rejects_undeclared_param_refs(tmp_path):
    with pytest.raises(SpecError) as ei:
        load_spec(_write(tmp_path, "p.yaml", BASE + "kind: pipeline\nsteps: [{id: a, component: summary, params: {columns: $params.cols}}]\n"))
    assert "undeclared pipeline params" in str(ei.value.details[0].msg)


class _P(ComponentParams):
    undocumented: int = Field(1)


class _Bad(Component):
    spec_name = "x"
    Params = _P
    Result = ComponentResult

    def compute(self, inputs, params, ctx):  # pragma: no cover
        raise NotImplementedError


def test_contract_mismatch(tmp_path):
    _write(tmp_path, "x.yaml", BASE + "params: {documented: {description: d}}\ninputs: {d: {type: dataframee}}\n")
    reg = Registry()
    reg.add_specs([load_spec(tmp_path / "x.yaml")])
    with pytest.raises(SpecError) as ei:
        reg.register(_Bad)
    types = {d.type for d in ei.value.details}
    assert types == {"spec_only_param", "undocumented_param", "unknown_type"}
    assert "dataframe" in next(d.hint for d in ei.value.details if d.type == "unknown_type")


def test_bad_port_constraints_rejected_at_registration(tmp_path):
    _write(tmp_path, "x.yaml", BASE + "params: {undocumented: {description: d}}\n"
                                      "inputs: {d: {type: dataframe, constraints: {min_row: 3}}}\n")
    reg = Registry()
    reg.add_specs([load_spec(tmp_path / "x.yaml")])
    with pytest.raises(SpecError) as ei:
        reg.register(_Bad)
    assert ei.value.details[0].loc == ("inputs", "d", "constraints", "min_row")


def test_spec_without_implementation(tmp_path):
    _write(tmp_path, "x.yaml", BASE)
    with pytest.raises(SpecError, match="without implementation"):
        Registry().load_domain(tmp_path, classes=[])


def test_pipeline_spec_validated_on_registration(tmp_path, registry):
    reg = build_registry([__import__("stat_fabric.domain", fromlist=["register"]).register])
    _write(tmp_path, "p.yaml", """
kind: pipeline
name: broken
version: 1.0.0
title: Broken
description: demo spec
llm: {when_to_use: w}
inputs: {data: {type: dataframe}}
steps:
  - {id: pca, component: pca, params: {features: [a, b]}}
  - {id: cl, component: clustering, inputs: {matrix: pca.score}}
""")
    with pytest.raises(SpecError) as ei:
        reg.load_domain(tmp_path, classes=[])
    d = ei.value.details[0]
    assert d.type == "unknown_output" and "scores" in d.hint


def test_unknown_component_suggests(registry):
    with pytest.raises(SpecError) as ei:
        registry.get("pcaa")
    assert "pca" in ei.value.details[0].hint


def test_text_domain_component(registry, note):
    res, store = run_component(registry, "keywords", {"top_k": 3}, text=note)
    assert [k.term for k in res.keywords][:1] == ["nitrogen"]
    assert store.get("t.terms")[0] == "nitrogen"
