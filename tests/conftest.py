import numpy as np
import pandas as pd
import pytest

from agent_fabric import build_registry
from agent_fabric.component import ArtifactStore, StepContext
from agent_fabric.pipeline import PipelineInputs
from examples.domains.text_pack import register as register_text
from stat_fabric.domain import register as register_stats

NOTE = (
    "Field note, 2026 season. Plots receiving the N120 nitrogen treatment showed denser tillering and "
    "higher wheat yield. Nitrogen uptake improved grain filling; rainfall in October limited phosphorus uptake."
)


@pytest.fixture(scope="session")
def df() -> pd.DataFrame:
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


@pytest.fixture(scope="session")
def note() -> str:
    return NOTE


@pytest.fixture(scope="session")
def registry():
    return build_registry([register_stats, register_text])


@pytest.fixture
def pin(registry, df) -> PipelineInputs:
    return PipelineInputs.from_values({"data": df}, registry.types)


@pytest.fixture
def good_plan() -> dict:
    return {
        "objective": "Effect of nitrogen treatments on wheat yield",
        "steps": [
            {"id": "summary", "component": "summary"},
            {
                "id": "lm",
                "component": "linear_model",
                "params": {"response": "yield_t_ha", "predictors": ["nitrogen", "rainfall", "treatment"]},
            },
            {"id": "aov", "component": "anova", "params": {"response": "yield_t_ha", "factors": ["treatment"]}},
            {
                "id": "ts",
                "component": "time_series",
                "params": {"time_col": "date", "value_col": "yield_t_ha", "horizon": 6},
            },
            {
                "id": "pca",
                "component": "pca",
                "params": {"features": ["nitrogen", "phosphorus", "potassium", "ph", "rainfall"]},
            },
            {"id": "clusters", "component": "clustering", "inputs": {"matrix": "pca.scores"}},
        ],
        "outputs": {"labels": "clusters.labels"},
    }


def run_component(registry, name, params=None, **inputs):
    comp = registry.get(name)
    store = ArtifactStore()
    result = comp.execute(inputs, params or {}, StepContext(store, "t", comp.spec, registry.types))
    return result, store
