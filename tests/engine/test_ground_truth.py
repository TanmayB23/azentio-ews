"""Scores vs planted scenarios. ground_truth.csv is used only here, never as a feature.

Run with `pytest -s tests/engine/test_ground_truth.py` to print the tables.
"""
import pandas as pd
import pytest

BANDS = ["Low", "Medium", "High", "Critical", "Insufficient data"]
SAFE = ("S0_", "S4_", "S7_no_transaction_data", "S7_transaction_gap")
AT_RISK = ("S1_", "S2_", "S3_", "S5_early_delinquency_worsening", "S6_", "S8_")
SEVERE = ("S5_early_delinquency_worsening", "S6_")


def _bands(results, ground_truth):
    gt = ground_truth.copy()
    gt["band"] = gt["customer_id"].map(lambda c: results[c].band or results[c].status)
    return gt


@pytest.fixture(params=["india", "gcc_islamic"])
def scored(request, clean_results, ground_truth, gcc):
    if request.param == "india":
        return request.param, _bands(clean_results, ground_truth)
    _, results, gt = gcc
    return request.param, _bands(results, gt)


def test_print_scenario_table(scored):
    name, gt = scored
    table = pd.crosstab(gt["scenario"], gt["band"]).reindex(columns=BANDS, fill_value=0)
    print(f"\n{name}\n{table.to_string()}")


def test_safe_customers_are_not_flagged_high(scored):
    _, gt = scored
    safe = gt[gt["scenario"].str.startswith(SAFE)]
    assert safe["band"].isin(["High", "Critical"]).sum() == 0
    assert (safe["band"] == "Low").mean() >= 0.98


def test_at_risk_customers_are_flagged(scored):
    _, gt = scored
    risky = gt[gt["scenario"].str.startswith(AT_RISK)]
    assert (risky["band"] != "Low").mean() >= 0.95
    severe = gt[gt["scenario"].str.startswith(SEVERE)]
    assert severe["band"].isin(["High", "Critical"]).all()


def test_thin_history_is_never_scored(scored):
    _, gt = scored
    assert (gt[gt["scenario"] == "S7_thin_history"]["band"] == "Insufficient data").all()
