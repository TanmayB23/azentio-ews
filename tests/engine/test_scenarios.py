"""Behaviour checks on individual planted scenarios."""
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
    # not every customer needs it: misses before the 6-month window or of 3 days or less score ~0 anyway
    cids = by_scenario["S4_temporary_miss_with_evidence"] + by_scenario["S4_temporary_miss_no_evidence"]
    dampened = [c for c in cids if any("Isolated late payment" in m for m in clean_results[c].modifiers)]
    assert len(dampened) >= len(cids) // 2
    assert all(clean_results[c].band == "Low" for c in cids)


def test_evidence_dampens_more_than_no_evidence(clean_results, by_scenario):
    mods = lambda scen: [m for c in by_scenario[scen] for m in clean_results[c].modifiers if "Isolated" in m]
    assert all(m.endswith("x0.25") for m in mods("S4_temporary_miss_with_evidence"))
    assert all(m.endswith("x0.6") for m in mods("S4_temporary_miss_no_evidence"))


def test_worsening_delinquency_triggers_roll_forward(clean_results, by_scenario):
    for cid in by_scenario["S5_early_delinquency_worsening"]:
        r = clean_results[cid]
        assert any(m.startswith("Roll-forward") for m in r.modifiers), cid
        assert r.band == "Critical", cid


def test_recovering_delinquency_is_watched_not_escalated(clean_results, by_scenario):
    for cid in by_scenario["S5_early_delinquency_recovering"]:
        r = clean_results[cid]
        assert not any(m.startswith("Roll-forward") for m in r.modifiers), cid
        assert r.band == "Medium", cid


def test_thin_history_is_insufficient_not_risky(clean_results, by_scenario):
    for cid in by_scenario["S7_thin_history"]:
        r = clean_results[cid]
        assert r.status == "Insufficient data", cid
        assert r.score is None and r.band is None
        assert r.confidence < 0.5


def test_missing_transactions_lower_confidence_not_risk(clean_results, by_scenario):
    for cid in by_scenario["S7_no_transaction_data"]:
        r = clean_results[cid]
        assert r.band == "Low", cid
        assert r.confidence < 1.0
        assert all(not s.evaluated for s in r.signals if s.pillar == "CF")


def test_transaction_gap_stays_low(clean_results, by_scenario):
    results = [clean_results[c] for c in by_scenario["S7_transaction_gap"]]
    assert all(r.band == "Low" for r in results)
    assert any(r.confidence < 1.0 for r in results)


def test_seasonal_dip_is_not_deterioration(clean_results, by_scenario):
    results = [clean_results[c] for c in by_scenario["S0_seasonal_sme"]]
    assert all(r.band == "Low" for r in results)
    assert any(any(m.startswith("Seasonal pattern") for m in r.modifiers) for r in results)


def test_sme_signals_apply_only_to_smes(clean_ds, clean_results, by_scenario):
    types = clean_ds.tables["customers"].set_index("customer_id")["customer_type"]
    for cid, r in clean_results.items():
        assert _sig(r, "SM01").applicable == (types[cid] == "SME"), cid
    stressed = by_scenario["S6_sme_financial_stress"]
    assert sum(_sig(clean_results[c], "SM02").strength > 0 for c in stressed) >= len(stressed) // 2


def test_new_customer_first_facility_is_not_new_exposure(clean_results, by_scenario):
    for cid in by_scenario["S7_thin_history"]:
        assert _sig(clean_results[cid], "EX02").strength == 0, cid


def test_no_revolving_facility_makes_utilisation_not_applicable(clean_ds, clean_results):
    fac = clean_ds.tables["facilities"]
    term_only = set(fac["customer_id"]) - set(fac[fac["facility_type"] == "Revolving"]["customer_id"])
    for cid in sorted(term_only)[:20]:
        assert _sig(clean_results[cid], "EX01").applicable is False


def test_planted_clusters_are_detected(clean_ds, clean_results):
    found = {(c.dimension, c.value) for c in detect_clusters(clean_ds, list(clean_results.values()))}
    assert ("industry x region", "Textiles|Tamil Nadu") in found
    assert ("industry x region", "Gig Economy|Karnataka") in found
    assert ("industry", "Logistics & Transport") in found


def test_broad_groups_do_not_echo_a_nested_cluster(clean_ds, clean_results):
    found = {(c.dimension, c.value) for c in detect_clusters(clean_ds, list(clean_results.values()))}
    assert ("region", "Tamil Nadu") not in found
    assert ("industry", "Textiles") not in found


def test_gcc_portfolio_scores_and_clusters(gcc):
    ds, results, gt = gcc
    assert all("gcc_islamic" in r.rules_version for r in results.values())
    worsening = gt[gt["scenario"] == "S5_early_delinquency_worsening"]["customer_id"]
    assert all(results[c].band == "Critical" for c in worsening)
    found = {(c.dimension, c.value) for c in detect_clusters(ds, list(results.values()))}
    assert ("industry x region", "Construction & Contracting|Dubai") in found
    assert ("industry x region", "Delivery & Ride-hailing|Riyadh") in found
