"""Every pack in this repository declares the core API level it was written for, and the core accepts it."""

from __future__ import annotations

import pytest

from agent_fabric import API_LEVEL, API_LEVEL_MIN, build_registry
from agent_fabric.compat import declared_api

PACKS = ["stat_fabric", "lake_fabric", "coworker_fabric", "text_pack"]


@pytest.mark.parametrize("pack", PACKS)
def test_pack_declares_a_supported_api_level(pack):
    import importlib

    register = importlib.import_module(pack).register
    level = declared_api(register)
    assert level is not None, f"{pack}.register must be decorated with @requires_api(<level>)"
    assert API_LEVEL_MIN <= level <= API_LEVEL


def test_installed_packs_load_through_discovery():
    reg = build_registry(discover=True)
    assert {"statistics", "text", "lakehouse", "coworker"} <= set(reg.domains())
