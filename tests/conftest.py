from pathlib import Path

import pandas as pd
import pytest

from ews.engine import load_dir, score_portfolio

DATA = Path(__file__).resolve().parents[1] / "files" / "ews_synthetic_data" / "ews_synthetic_data"


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
