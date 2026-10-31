import pandas as pd

from ews.engine import load_dataset
from tests.conftest import DATA


def test_clean_data_has_no_errors(clean_ds):
    assert not [i for i in clean_ds.issues if i.severity == "error"]
    assert len(clean_ds.tables["customers"]) == 300
    assert len(clean_ds.tables["repayments"]) == 5889


def test_every_manifest_defect_is_reported(dirty_ds):
    manifest = pd.read_csv(DATA / "dirty" / "data_issues_manifest.csv")
    found = {(i.table, i.record_key) for i in dirty_ds.issues}
    missed = []
    for row in manifest.itertuples():
        if "invalid month" in row.issue:
            cid = row.record_key.split("|")[0]
            hit = any(i.table == row.table and i.record_key.startswith(cid + "|") and "invalid month" in i.issue
                      for i in dirty_ds.issues)
        else:
            hit = (row.table, row.record_key) in found
        if not hit:
            missed.append((row.table, row.record_key, row.issue))
    assert not missed, f"{len(missed)} manifest defects not reported: {missed}"


def test_orphans_and_duplicates_are_quarantined(dirty_ds):
    t = dirty_ds.tables
    assert "C9999" not in set(t["facilities"]["customer_id"])
    assert "C9999" not in set(t["transactions"]["customer_id"])
    assert "L99999" not in set(t["repayments"]["loan_id"])
    assert t["repayments"]["repayment_id"].is_unique
    assert t["customers"]["customer_id"].is_unique
    assert not t["transactions"].duplicated(["customer_id", "month"]).any()


def test_repairs_are_applied(dirty_ds):
    t = dirty_ds.tables
    assert set(t["customers"]["customer_type"].dropna()) <= {"Individual", "SME"}
    assert t["customers"]["customer_type"].notna().all()
    assert t["transactions"]["total_inflows"].ge(0).all()
    assert t["exposure"]["utilisation_pct"].dropna().between(0, 100).all()
    paid_on_time = t["repayments"][t["repayments"]["repayment_status"] == "Paid On Time"]
    assert (paid_on_time["dpd"] == 0).all()


def test_excel_and_json_match_csv(clean_ds):
    xl = load_dataset({"early_warning_data.xlsx": DATA / "clean" / "early_warning_data.xlsx"})
    js = load_dataset({"portfolio.json": DATA / "clean" / "portfolio.json"})
    for ds in (xl, js):
        for name, df in clean_ds.tables.items():
            assert len(ds.tables[name]) == len(df), name
    assert xl.signal_config is not None and len(xl.signal_config["signals"]) == 13


def test_missing_table_is_reported():
    ds = load_dataset({"customers.csv": DATA / "clean" / "customers.csv"})
    assert any(i.issue == "table 'repayments' not provided" for i in ds.issues)
