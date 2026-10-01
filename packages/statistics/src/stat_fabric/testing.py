"""Test helpers for statistics-based tests (shared by this pack's tests and the cross-package suite)."""

from __future__ import annotations

import numpy as np
import pandas as pd

NOTE = (
    "Field note, 2026 season. Plots receiving the N120 nitrogen treatment showed denser tillering and "
    "higher wheat yield. Nitrogen uptake improved grain filling; rainfall in October limited phosphorus uptake."
)


def sample_trial_df() -> pd.DataFrame:
    """Synthetic agronomic trial (120 rows, 2 missing yields) with a known structure."""
    rng = np.random.default_rng(42)
    n = 120
    d = pd.DataFrame(
        {
            "date": pd.date_range("2016-01-01", periods=n, freq="MS").strftime("%Y-%m-%d"),
            "treatment": rng.choice(["control", "N60", "N120"], n),
            "cultivar": rng.choice(["TBIO", "ORS"], n),
            "nitrogen": rng.normal(40, 8, n),
            "phosphorus": rng.normal(20, 4, n),
            "potassium": rng.normal(60, 10, n),
            "ph": rng.normal(5.8, 0.3, n),
            "rainfall": rng.gamma(4, 40, n),
        }
    )
    d["phosphorus"] += 0.3 * d["nitrogen"]
    effect = d["treatment"].map({"control": 0.0, "N60": 0.4, "N120": 0.8})
    season = 0.3 * np.sin(np.arange(n) / 12 * 2 * np.pi)
    d["yield_t_ha"] = 2.0 + 0.02 * d["nitrogen"] + 0.002 * d["rainfall"] + effect + season + rng.normal(0, 0.25, n)
    d.loc[[3, 17], "yield_t_ha"] = np.nan
    return d


__all__ = [
    "sample_trial_df",
]
