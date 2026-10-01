import pandas as pd
import pytest

from agent_fabric import build_registry
from stat_fabric.domain import register as register_stats
from stat_fabric.testing import NOTE, sample_trial_df


@pytest.fixture(scope="session")
def df() -> pd.DataFrame:
    return sample_trial_df()


@pytest.fixture(scope="session")
def registry():
    return build_registry([register_stats])


@pytest.fixture(scope="session")
def note() -> str:
    return NOTE
