import pandas as pd
import pytest

from agent_fabric import build_registry
from agent_fabric.pipeline import PipelineInputs
from agent_fabric.testing import run_component  # noqa: F401  (re-exported for tests)
from stat_fabric.domain import register as register_stats
from stat_fabric.testing import NOTE, sample_trial_df
from text_pack import register as register_text


@pytest.fixture(scope="session")
def df() -> pd.DataFrame:
    return sample_trial_df()


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
