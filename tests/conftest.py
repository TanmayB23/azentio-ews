from pathlib import Path

import pandas as pd
import pytest

from ews.engine import load_dir, score_portfolio

DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
DATA = DATA_ROOT / "india"


@pytest.fixture(scope="session")
def clean_ds():
    return load_dir(DATA / "clean")


@pytest.fixture(scope="session")
def dirty_ds():
    return load_dir(DATA / "dirty")


@pytest.fixture(scope="session")
def clean_results(clean_ds):
    return {r.customer_id: r for r in score_portfolio(clean_ds)}


@pytest.fixture(scope="session")
def ground_truth():
    return pd.read_csv(DATA / "ground_truth.csv")


@pytest.fixture(scope="session")
def by_scenario(ground_truth):
    return ground_truth.groupby("scenario")["customer_id"].apply(list).to_dict()


@pytest.fixture(scope="session")
def gcc():
    """(dataset, results by customer, ground truth) for the Gulf / Islamic portfolio."""
    ds = load_dir(DATA_ROOT / "gcc_islamic" / "clean")
    results = {r.customer_id: r for r in score_portfolio(ds, "gcc_islamic")}
    return ds, results, pd.read_csv(DATA_ROOT / "gcc_islamic" / "ground_truth.csv")
