"""Eval baselines: a score that drops below baseline - tolerance must be reported as a regression."""

from __future__ import annotations

from agent_fabric.evals import compare_baseline, load_baselines, save_baselines

BASE = {"tolerance": 0.02, "suites": {"s": {"mean_score": 0.9, "case:a": 1.0}}}


def kinds(current, baselines=BASE, **kw):
    return {(i.severity, i.metric) for i in compare_baseline("s", current, baselines, **kw)}


def test_equal_scores_are_clean():
    assert kinds({"mean_score": 0.9, "case:a": 1.0}) == set()


def test_within_tolerance_is_clean_and_below_is_a_regression():
    assert kinds({"mean_score": 0.885, "case:a": 1.0}) == set()
    assert kinds({"mean_score": 0.87, "case:a": 1.0}) == {("regression", "mean_score")}


def test_single_case_drop_is_caught_even_when_the_mean_holds():
    assert kinds({"mean_score": 0.9, "case:a": 0.5}) == {("regression", "case:a")}


def test_improvement_new_and_missing_metrics_are_reported():
    assert kinds({"mean_score": 0.95, "case:a": 1.0}) == {("improvement", "mean_score")}
    assert kinds({"mean_score": 0.9, "case:a": 1.0, "case:b": 1.0}) == {("new", "case:b")}
    assert kinds({"mean_score": 0.9}) == {("missing", "case:a")}


def test_tolerance_override_and_unknown_suite():
    assert kinds({"mean_score": 0.87, "case:a": 1.0}, tolerance=0.05) == set()
    assert {i.severity for i in compare_baseline("other", {"mean_score": 1.0}, BASE)} == {"new"}


def test_roundtrip_and_missing_file(tmp_path):
    assert load_baselines(tmp_path / "none.json")["suites"] == {}
    save_baselines(tmp_path / "b.json", BASE)
    assert load_baselines(tmp_path / "b.json") == BASE
