"""Compatibility contract between the core and domain packs: an integer API level.

The *API level* versions what a pack builds against: `Component` and its hooks, `Registry`, the spec formats (`SKILL.md` contract,
artifact types) and the `register(registry)` entry point. It is independent of the package version, which is still 0.x:

* ``API_LEVEL`` is the level this core implements; it is bumped on a breaking change of that surface (never for additions).
* ``API_LEVEL_MIN`` is the oldest level the core still loads; raising it is how an old level is retired, one release after deprecating it.
* A pack declares the level it was written for with `requires_api` on its ``register`` function. The loaders (`build_registry`,
  `Registry.discover_domains`) refuse a pack that needs a newer core or targets a retired level, with a located `SpecError`.
  A pack without a declaration (out-of-tree, older) is accepted unchecked.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .errors import ErrorDetail, SpecError

API_LEVEL = 1
API_LEVEL_MIN = 1
_ATTR = "agent_fabric_api"


def requires_api[F: Callable[..., Any]](level: int) -> Callable[[F], F]:
    """Decorator for a pack's ``register`` function: declare the core API level the pack was written for."""
    if level < 1:
        raise ValueError("API levels start at 1")

    def deco(fn: F) -> F:
        setattr(fn, _ATTR, level)
        return fn

    return deco


def declared_api(register: Callable[..., Any]) -> int | None:
    """The API level declared on a ``register`` function with `requires_api`, or ``None``."""
    level = getattr(register, _ATTR, None)
    return level if isinstance(level, int) else None


def check_pack_api(register: Callable[..., Any], name: str) -> None:
    """Raise a `SpecError` unless the pack's declared API level is supported by this core.

    ``name`` identifies the pack in the error (its entry point name or ``module:register`` reference).
    """
    level = declared_api(register)
    if level is None or API_LEVEL_MIN <= level <= API_LEVEL:
        return
    if level > API_LEVEL:
        msg = f"pack '{name}' needs agent-fabric API level {level}, this core implements {API_LEVEL}"
        hint = (
            "upgrade agent-fabric to a release that implements this API level, or install an older version of the pack"
        )
        kind = "pack_needs_newer_core"
    else:
        msg = f"pack '{name}' targets API level {level}, which this core no longer supports (oldest: {API_LEVEL_MIN})"
        hint = "upgrade the pack to a release written for the current API level"
        kind = "pack_api_retired"
    raise SpecError(
        f"Incompatible domain pack '{name}'",
        [ErrorDetail(loc=("domains", name), type=kind, input=level, msg=msg, hint=hint)],
    )


__all__ = ["API_LEVEL", "API_LEVEL_MIN", "check_pack_api", "declared_api", "requires_api"]
