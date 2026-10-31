"""Behaviour checks on individual planted scenarios."""
from collections import Counter

from ews.engine import detect_clusters

HIGH = {"High", "Critical"}


def _sig(result, signal_id):
    return next(s for s in result.signals if s.signal_id == signal_id)


def test_repeated_delays_fire_repayment_signals(clean_results, by_scenario):
    for cid in by_scenario["S1_repeated_repayment_delays"]:
        r = clean_results[cid]
        assert _sig(r, "RB01").strength > 0, cid
        assert r.band in {"Medium", "High", "Critical"}, cid


def test_temporary_miss_is_dampened_not_escalated(clean_results, by_scenario):
    # misses before the 6-month window need no dampening, so only some customers get it
    cids = by_scenario["S4_temporary_missed_payment"]
    dampened = [c for c in cids if any("Isolated late payment" in m for m in clean_results[c].modifiers)]
    assert len(dampened) >= 5
    assert all(clean_results[c].band == "Low" for c in cids)


def test_worsening_delinquency_triggers_roll_forward(clean_results, by_scenario):
    for cid in by_scenario["S5_early_delinquency_worsening"]:
        r = clean_results[cid]
        assert any(m.startswith("Roll-forward") for m in r.modifiers), cid
        assert r.band == "Critical", cid


def test_recovering_delinquency_is_not_rolled_forward(clean_results, by_scenario):
    for cid in by_scenario["S5_early_delinquency_recovering"]:
        r = clean_results[cid]
        assert not any(m.startswith("Roll-forward") for m in r.modifiers), cid
        assert r.band not in HIGH, cid


def test_thin_history_is_insufficient_not_risky(clean_results, by_scenario):
    for cid in by_scenario["S7_thin_or_missing_history"]:
        r = clean_results[cid]
        assert r.status == "Insufficient data", cid
        assert r.score is None and r.band is None
        assert r.confidence < 0.5


def test_transaction_gap_lowers_confidence_only(clean_results, by_scenario):
    # gaps before the 6-month window do not affect any signal, so confidence can stay 1.0
    results = [clean_results[c] for c in by_scenario["S7_transaction_gap_otherwise_healthy"]]
    assert all(r.band == "Low" for r in results)
    assert any(r.confidence < 1.0 for r in results)


def test_new_customer_first_facility_is_not_new_exposure(clean_results, by_scenario):
    for cid in by_scenario["S7_thin_or_missing_history"]:
        assert _sig(clean_results[cid], "EX02").strength == 0, cid


def test_no_revolving_facility_makes_utilisation_not_applicable(clean_ds, clean_results):
    fac = clean_ds.tables["facilities"]
    term_only = set(fac["customer_id"]) - set(fac[fac["facility_type"] == "Revolving"]["customer_id"])
    for cid in list(term_only)[:20]:
        assert _sig(clean_results[cid], "EX01").applicable is False


def test_planted_clusters_are_detected(clean_ds, clean_results):
    clusters = detect_clusters(clean_ds, list(clean_results.values()))
    found = {(c.dimension, c.value) for c in clusters}
    assert ("industry x region", "Textiles|Tamil Nadu") in found
    assert ("industry x region", "Gig Economy|Karnataka") in found


def test_gcc_profile_runs(clean_ds):
    from ews.engine import score_portfolio
    results = score_portfolio(clean_ds, "gcc_islamic")
    assert len(results) == 300
    assert all("gcc_islamic" in r.rules_version for r in results)
