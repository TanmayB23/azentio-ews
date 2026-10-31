from copy import deepcopy
import numpy as np
import pandas as pd
import pytest
from ews.contracts import Dataset
from ews.ml.features import FEATURE_IDS, feature_rows, feature_signature, horizon_end, snapshot, target


def one_customer(ds, cid="C0002"):
    return Dataset({name:frame.loc[frame.customer_id == cid].copy() for name,frame in ds.tables.items()}, [], {}, ds.signal_config)


def test_future_information_cannot_change_features(clean_ds):
    ds = one_customer(clean_ds)
    changed = deepcopy(ds)
    origin = pd.Timestamp("2026-04-30")
    changed.tables["delinquency"]["current_dpd"] = 999
    changed.tables["facilities"]["outstanding_balance"] = 99999999
    for name in ("transactions","exposure","sme_indicators"):
        frame = changed.tables[name]
        future = frame.month > "2026-04"
        for col in frame.select_dtypes(include="number"):
            frame.loc[future,col] = 999999
    rep = changed.tables["repayments"]
    future = rep.due_date > origin
    rep.loc[future,"dpd"] = 999
    rep.loc[future,"payment_date"] = pd.Timestamp("2028-01-01")
    before = feature_rows(ds,"india",origin)["C0002"]["features"]
    after = feature_rows(changed,"india",origin)["C0002"]["features"]
    np.testing.assert_allclose(list(before.values()),list(after.values()),equal_nan=True)


def test_eventual_payment_is_censored_and_reconstructed(clean_ds):
    ds=one_customer(clean_ds)
    rep=ds.tables["repayments"]
    index=rep.index[0]
    rep.loc[index,"due_date"]=pd.Timestamp("2026-04-20")
    rep.loc[index,"payment_date"]=pd.Timestamp("2026-05-20")
    rep.loc[index,"dpd"]=30
    rep.loc[index,"exception_reason"]="Future explanation"
    point=snapshot(ds,"2026-04-30")
    record=point.tables["repayments"].loc[index]
    assert record.dpd==10
    assert pd.isna(record.payment_date)
    assert record.amount_paid==0
    assert record.repayment_status=="Overdue"
    assert pd.isna(record.exception_reason)
    assert point.tables["delinquency"].current_dpd.max() >=10


def label_dataset(delay=30, partial=False):
    due=pd.to_datetime(["2026-02-01","2026-03-01","2026-04-01"])
    rep=pd.DataFrame({"customer_id":["C1"]*3,"due_date":due,
        "payment_date":[due[0]+pd.Timedelta(days=delay),due[1],due[2]],
        "amount_due":[100]*3,"amount_paid":[50 if partial else 100,100,100],
        "repayment_status":["Partially Paid" if partial else "Paid Late","Paid On Time","Paid On Time"]})
    return Dataset({"repayments":rep},[],{})


def test_exact_thirty_day_target_and_full_followup():
    assert target(label_dataset(30),"C1","2026-01-31","2026-04-30")==1
    assert target(label_dataset(29),"C1","2026-01-31","2026-04-30")==0
    assert target(label_dataset(30),"C1","2026-01-31","2026-04-29") is None
    assert target(label_dataset(10,True),"C1","2026-01-31","2026-04-30") is None
    assert str(horizon_end("2026-10-31").date())=="2027-01-31"


def test_missing_future_month_is_censored():
    ds=label_dataset()
    ds.tables["repayments"]=ds.tables["repayments"].iloc[:2]
    assert target(ds,"C1","2026-01-31","2026-04-30") is None


def test_empty_history_and_feature_schema(clean_ds):
    ds=one_customer(clean_ds)
    ds.tables["repayments"]=ds.tables["repayments"].iloc[:0]
    row=feature_rows(ds,"india","2026-04-30")["C0002"]
    assert row["observed_months"]==0 and row["coverage"]==0
    assert tuple(row["features"])==FEATURE_IDS
    assert all(np.isnan(v) for v in row["features"].values())
    altered=deepcopy(clean_ds)
    from ews.engine.scoring import _definitions
    altered.signal_config=_definitions(None)
    altered.signal_config["signals"][0]["window_months"]=12
    assert feature_signature(altered,"india")!=feature_signature(clean_ds,"india")


def test_monthly_totals_are_not_available_mid_month(clean_ds):
    with pytest.raises(ValueError,match="month-end"):
        feature_rows(one_customer(clean_ds),"india","2026-04-15")


def test_live_features_match_rule_signal_measurements(clean_ds,clean_results):
    for cid in list(clean_results)[::100]:
        row=feature_rows(one_customer(clean_ds,cid),"india","2026-10-31")[cid]
        for signal in clean_results[cid].signals:
            actual=row["features"][signal.signal_id]
            if signal.applicable and signal.evaluated:
                assert actual==pytest.approx(signal.value)
            else:
                assert np.isnan(actual)
