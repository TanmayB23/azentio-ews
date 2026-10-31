"""Shared interface checks; never require Streamlit in the real engine."""
import importlib
import importlib.util
from dataclasses import asdict
import math
import pytest
from ews import fake_engine
from ews.contracts import Cluster, CustomerResult, Dataset, SignalResult

@pytest.mark.parametrize("module", ["ews.fake_engine"])
def test_engine_contract(module):
    if module == "ews.engine" and importlib.util.find_spec(module) is None:
        pytest.skip("Person A engine has not been merged")
    engine = importlib.import_module(module)
    folder = fake_engine.SAMPLE_ROOT / "clean"
    ds = engine.load_dataset({f"{t}.csv": str(folder / f"{t}.csv") for t in fake_engine.TABLES})
    assert isinstance(ds, Dataset)
    results = engine.score_portfolio(ds, profile="india")
    assert len(results) == ds.tables["customers"].customer_id.nunique()
    assert {r.customer_id for r in results} == set(ds.tables["customers"].customer_id)
    for r in results:
        assert isinstance(r, CustomerResult)
        assert isinstance(r.customer_id, str) and isinstance(r.summary, str)
        assert r.as_of == "2026-10-31"
        assert 0 <= r.confidence <= 1
        if r.status == "Insufficient data":
            assert r.score is None and r.band is None
        else:
            assert r.status == "Scored" and 0 <= r.score <= 100
            expected = "Low" if r.score < 25 else "Medium" if r.score < 50 else "High" if r.score < 75 else "Critical"
            assert r.band == expected
        for signal in r.signals:
            assert isinstance(signal, SignalResult)
            assert signal.pillar in ("RB", "CF", "EX")
            assert 0 <= signal.strength <= 1
            assert math.isfinite(signal.points) and signal.points >= 0
            assert signal.points == pytest.approx(signal.strength * signal.weight)
            assert isinstance(signal.evidence, list)
            if not signal.evaluated:
                assert signal.reason_not_evaluated
                assert signal.points == 0
        # The plan's nonlinear pillar combination and modifiers mean raw signal
        # points need not sum to the final risk score in the production engine.
    for cluster in engine.detect_clusters(ds, results):
        assert isinstance(cluster, Cluster)
        assert cluster.n_customers == len(set(cluster.customer_ids))
        assert 0 <= cluster.n_elevated <= cluster.n_customers
        assert set(cluster.customer_ids) <= {r.customer_id for r in results}
