"""Scores vs planted scenarios. ground_truth.csv is used only here, never as a feature.

Run with `pytest -s tests/engine/test_ground_truth.py` to print the table.
"""
import pandas as pd

BANDS = ["Low", "Medium", "High", "Critical", "Insufficient data"]
HEALTHY = ["S0_healthy", "S0_volatile_but_stable", "S7_transaction_gap_otherwise_healthy",
           "S4_temporary_missed_payment"]
AT_RISK = ["S1_repeated_repayment_delays", "S2_declining_income_cashflow", "S3_increasing_exposure",
           "S5_early_delinquency_worsening", "S6_sme_financial_stress", "S8_cluster_textiles_tamil_nadu",
           "S8_cluster_gig_workers_karnataka"]


def _table(clean_results, ground_truth):
    gt = ground_truth.copy()
    gt["band"] = gt["customer_id"].map(lambda c: clean_results[c].band or clean_results[c].status)
    return gt, pd.crosstab(gt["scenario"], gt["band"]).reindex(columns=BANDS, fill_value=0)


def test_print_scenario_table(clean_results, ground_truth):
    _, table = _table(clean_results, ground_truth)
    print("\n" + table.to_string())


def test_healthy_customers_are_not_flagged_high(clean_results, ground_truth):
    gt, _ = _table(clean_results, ground_truth)
    healthy = gt[gt["scenario"].isin(HEALTHY)]
    assert healthy["band"].isin(["High", "Critical"]).sum() == 0
    assert (healthy["band"] == "Low").mean() >= 0.95


def test_at_risk_customers_are_flagged(clean_results, ground_truth):
    gt, _ = _table(clean_results, ground_truth)
    risky = gt[gt["scenario"].isin(AT_RISK)]
    assert (risky["band"] != "Low").mean() >= 0.9
    severe = gt[gt["scenario"].isin(["S5_early_delinquency_worsening", "S6_sme_financial_stress"])]
    assert severe["band"].isin(["High", "Critical"]).mean() >= 0.9
