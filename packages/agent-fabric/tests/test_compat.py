"""Core/pack compatibility: an integer API level declared by the pack and checked by the loaders."""

from __future__ import annotations

import pytest

from agent_fabric import API_LEVEL, API_LEVEL_MIN, build_registry, requires_api
from agent_fabric.compat import check_pack_api, declared_api
from agent_fabric.errors import SpecError
from agent_fabric.registry import Registry


def fake_pack(level: int | None):
    def register(registry):
        registry.loaded = True
        return []

    return register if level is None else requires_api(level)(register)


def test_current_core_levels_are_consistent():
    assert 1 <= API_LEVEL_MIN <= API_LEVEL


def test_requires_api_records_the_level_and_validates_it():
    assert declared_api(fake_pack(API_LEVEL)) == API_LEVEL
    assert declared_api(fake_pack(None)) is None
    with pytest.raises(ValueError, match="start at 1"):
        requires_api(0)


def test_supported_levels_and_undeclared_packs_load():
    for level in range(API_LEVEL_MIN, API_LEVEL + 1):
        check_pack_api(fake_pack(level), "p")
    check_pack_api(fake_pack(None), "legacy")  # out-of-tree packs without a declaration are accepted unchecked
    reg = build_registry([fake_pack(API_LEVEL), fake_pack(None)])
    assert isinstance(reg, Registry)


def test_pack_needing_a_newer_core_is_rejected_with_a_located_error():
    with pytest.raises(SpecError) as ei:
        check_pack_api(fake_pack(API_LEVEL + 1), "future-pack")
    [d] = ei.value.details
    assert d.loc == ("domains", "future-pack")
    assert d.type == "pack_needs_newer_core"
    assert d.input == API_LEVEL + 1
    assert "upgrade agent-fabric" in (d.hint or "")


def test_retired_level_is_rejected(monkeypatch):
    import agent_fabric.compat as compat

    monkeypatch.setattr(compat, "API_LEVEL", 3)
    monkeypatch.setattr(compat, "API_LEVEL_MIN", 2)
    compat.check_pack_api(fake_pack(2), "ok")
    with pytest.raises(SpecError) as ei:
        compat.check_pack_api(fake_pack(1), "old-pack")
    assert ei.value.details[0].type == "pack_api_retired"
    assert "upgrade the pack" in (ei.value.details[0].hint or "")


def test_build_registry_checks_callables_and_references(tmp_path, monkeypatch):
    with pytest.raises(SpecError) as ei:
        build_registry([fake_pack(API_LEVEL + 5)])
    assert ei.value.details[0].type == "pack_needs_newer_core"
    # a "module:attr" reference is named in the error
    import sys
    import types

    mod = types.ModuleType("fake_future_pack")
    mod.register = fake_pack(API_LEVEL + 1)
    monkeypatch.setitem(sys.modules, "fake_future_pack", mod)
    with pytest.raises(SpecError) as ei:
        build_registry(["fake_future_pack:register"])
    assert ei.value.details[0].loc == ("domains", "fake_future_pack:register")


def test_entry_point_discovery_checks_the_level(monkeypatch):
    from importlib import metadata

    class EP:
        def __init__(self, name, fn):
            self.name, self._fn = name, fn

        def load(self):
            return self._fn

    eps = [EP("good", fake_pack(API_LEVEL)), EP("future", fake_pack(API_LEVEL + 1))]
    monkeypatch.setattr(metadata, "entry_points", lambda group: eps)
    with pytest.raises(SpecError) as ei:
        Registry().discover_domains()
    assert ei.value.details[0].loc == ("domains", "future")
