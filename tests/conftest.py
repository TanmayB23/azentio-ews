from pathlib import Path

import pytest

from ews.engine import load_dir

DATA = Path(__file__).resolve().parents[1] / "files" / "ews_synthetic_data" / "ews_synthetic_data"


@pytest.fixture(scope="session")
def clean_ds():
    return load_dir(DATA / "clean")


@pytest.fixture(scope="session")
def dirty_ds():
    return load_dir(DATA / "dirty")
