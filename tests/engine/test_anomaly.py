"""Unusual-behaviour signal (isolation forest): useful, explainable, bounded, repeatable."""
import pandas as pd
import pytest

from ews.engine import score_portfolio
from ews.engine.anomaly import score_portfolio_anomalies
from ews.engine.config import load_profile
from ews.engine.views import build_views

AS_OF = pd.Timestamp("2026-10-31")


@pytest.fixture(scope="module")
def anomalies(clean_ds):
    return score_portfolio_anomalies(build_views(clean_ds, AS_OF, load_profile("india")), AS_OF)


def _ub(result):
    return next(s for s in result.signals if s.signal_id == "UB01")


def test_risky_customers_look_more_unusual_than_healthy(anomalies, by_scenario):
    pct = lambda scen: pd.Series([anomalies[c].percentile for c in by_scenario[scen]]).median()
    healthy = pct("S0_healthy")
    for scen in ("S5_early_delinquency_worsening", "S1_repeated_repayment_delays", "S3_increasing_exposure",
                 "S6_sme_financial_stress"):
        assert pct(scen) > healthy + 30, scen


def test_healthy_customers_are_not_in_the_top_five_percent(anomalies, by_scenario):
    assert all(anomalies[c].percentile < 95 for c in by_scenario["S0_healthy"])


def test_missing_data_is_never_unusual(anomalies, by_scenario):
    for cid in by_scenario["S7_no_transaction_data"] + by_scenario["S7_thin_history"]:
        a = anomalies[cid]
        assert a.percentile is None or a.percentile < 95, cid


def test_flags_are_explained(anomalies):
    flagged = [a for a in anomalies.values() if a.percentile is not None and a.percentile >= 95]
    assert flagged and all(a.drivers for a in flagged)
    assert all(" vs typical " in d for a in flagged for d in a.drivers)


def test_results_are_repeatable(clean_ds, anomalies):
    again = score_portfolio_anomalies(build_views(clean_ds, AS_OF, load_profile("india")), AS_OF)
    assert {c: a.percentile for c, a in again.items()} == {c: a.percentile for c, a in anomalies.items()}


def test_signal_adds_at_most_its_weight_and_never_changes_confidence(clean_results, by_scenario):
    for r in clean_results.values():
        ub = _ub(r)
        assert 0 <= ub.points <= ub.weight
    for cid in by_scenario["S7_no_transaction_data"]:
        assert clean_results[cid].confidence >= 0.5      # supplementary signal not counted


def test_documented_one_off_reduces_the_ml_signal(clean_results, by_scenario):
    for cid in by_scenario["S4_temporary_miss_with_evidence"]:
        r = clean_results[cid]
        if any("evidence on file" in m for m in r.modifiers):
            assert _ub(r).points <= 0.25 * _ub(r).weight + 1e-9, cid


def test_uploaded_definitions_without_ub01_still_get_it(clean_ds):
    assert clean_ds.signal_config and "UB01" not in {s["signal_id"] for s in clean_ds.signal_config["signals"]}
    result = score_portfolio(clean_ds)[0]
    assert any(s.signal_id == "UB01" for s in result.signals)
