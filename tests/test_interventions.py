"""Recommended interventions match the planted scenarios."""
import pandas as pd
import pytest

from ews.engine import detect_clusters
from ews.interventions import customer_facts, load_playbook, recommend
from tests.conftest import DATA


@pytest.fixture(scope="module")
def recs(clean_ds, clean_results):
    clusters = detect_clusters(clean_ds, list(clean_results.values()))
    facts = customer_facts(clean_ds, clusters, "india")
    return {cid: recommend(r, facts[cid]) for cid, r in clean_results.items()}


def _ids(recs, cid):
    return [r.action_id for r in recs[cid]]


def test_every_rule_names_a_known_action():
    book = load_playbook()
    assert {r["action"] for r in book["rules"]} <= set(book["actions"])


def test_worsening_delinquency_goes_to_collections_first(recs, by_scenario):
    for cid in by_scenario["S5_early_delinquency_worsening"]:
        assert _ids(recs, cid)[0] == "COLLECTIONS_CONTACT", cid


def test_one_off_miss_with_evidence_needs_no_action(recs, by_scenario):
    for cid in by_scenario["S4_temporary_miss_with_evidence"]:
        assert not recs[cid], (cid, _ids(recs, cid))


def test_one_off_miss_without_evidence_asks_for_it(recs, by_scenario):
    asked = [cid for cid in by_scenario["S4_temporary_miss_no_evidence"] if "REQUEST_EVIDENCE" in _ids(recs, cid)]
    assert len(asked) >= len(by_scenario["S4_temporary_miss_no_evidence"]) // 2


def test_thin_history_collects_data_and_nothing_harsher(recs, by_scenario):
    for cid in by_scenario["S7_thin_history"]:
        assert _ids(recs, cid) == ["COLLECT_DATA"], cid


def test_healthy_customers_are_left_alone(recs, by_scenario):
    healthy = by_scenario["S0_healthy"] + by_scenario["S0_seasonal_sme"] + by_scenario["S0_volatile_but_stable"]
    flagged = [cid for cid in healthy if recs[cid]]
    assert len(flagged) <= 0.02 * len(healthy)


def test_cash_flow_and_exposure_scenarios_get_matching_actions(recs, by_scenario):
    cash = [cid for cid in by_scenario["S2_declining_income_cashflow"] if "RM_CASHFLOW_REVIEW" in _ids(recs, cid)]
    assert len(cash) >= len(by_scenario["S2_declining_income_cashflow"]) // 2
    for cid in by_scenario["S3_increasing_exposure"]:
        if recs[cid]:
            assert "FREEZE_LIMITS" in _ids(recs, cid) or recs[cid][0].action_id == "NEXT_CYCLE_CHECK", cid


def test_reasons_cite_real_signals(recs, clean_results):
    for cid, rs in recs.items():
        ids = {s.signal_id for s in clean_results[cid].signals}
        for r in rs:
            assert r.reasons, (cid, r.action_id)
            assert set(r.cites) <= ids, (cid, r.action_id, r.cites)


def test_islamic_profile_adds_shariah_restructuring(gcc):
    ds, results, gt = gcc
    facts = customer_facts(ds, detect_clusters(ds, list(results.values())), "gcc_islamic")
    worsening = gt[gt["scenario"] == "S5_early_delinquency_worsening"]["customer_id"]
    for cid in worsening:
        assert "ISLAMIC_RESCHEDULE" in [r.action_id for r in recommend(results[cid], facts[cid])], cid
