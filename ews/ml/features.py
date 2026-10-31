"""Reconstruct observations known at a forecast origin; never use final DPD as history."""
from __future__ import annotations
from hashlib import sha256
import json

import numpy as np
import pandas as pd

from ews.contracts import Dataset
from ews.engine.config import load_profile
from ews.engine.scoring import _definitions
from ews.engine.signals import evaluate_signals
from ews.engine.views import build_views

FEATURE_VERSION = "point-in-time-signals-v1"
FEATURE_IDS = tuple([f"RB{i:02d}" for i in range(1,5)] + [f"CF{i:02d}" for i in range(1,6)] + [f"EX{i:02d}" for i in range(1,5)] + ["SM01", "SM02"])
HORIZON_MONTHS = 3
THRESHOLD_DPD = 30


def horizon_end(origin):
    return pd.Timestamp(origin).normalize() + pd.DateOffset(months=HORIZON_MONTHS)


def feature_signature(ds, profile):
    keys = ("signal_id", "metric", "window_months", "min_observations", "series", "min_total_decline_pct")
    definitions = _definitions(ds.signal_config)
    # only the signals the model uses: adding an unrelated signal (e.g. UB01) must not invalidate the model
    signals = sorted([{k: s.get(k) for k in keys} for s in definitions["signals"] if s["signal_id"] in FEATURE_IDS],
                     key=lambda s: s["signal_id"])
    return sha256(json.dumps({"version": FEATURE_VERSION, "signals": signals,
        "calendar": load_profile(profile).get("calendar", {})}, sort_keys=True).encode()).hexdigest()


def snapshot(ds: Dataset, origin) -> Dataset:
    """Remove future months/loans and censor eventual payment outcomes at origin.

    Current delinquency is reconstructed, never copied from the final snapshot.
    Static current facility balances are not features and are blanked here.
    """
    origin = pd.Timestamp(origin).normalize()
    tables = {name: frame.copy() for name, frame in ds.tables.items()}
    customers = tables["customers"]
    if "onboarding_date" in customers:
        onboarded = pd.to_datetime(customers.onboarding_date, errors="coerce")
        tables["customers"] = customers.loc[onboarded.isna() | (onboarded <= origin)].copy()
    ids = set(tables["customers"].customer_id)
    facilities = tables["facilities"]
    dates = pd.to_datetime(facilities.disbursement_date, errors="coerce")
    facilities = facilities.loc[(dates <= origin) & facilities.customer_id.isin(ids)].copy()
    if "outstanding_balance" in facilities:
        facilities["outstanding_balance"] = np.nan
    tables["facilities"] = facilities
    rep = tables["repayments"]
    due = pd.to_datetime(rep.due_date, errors="coerce")
    rep = rep.loc[(due <= origin) & rep.loan_id.isin(facilities.loan_id)].copy()
    rep["due_date"] = pd.to_datetime(rep.due_date)
    paid = pd.to_datetime(rep.payment_date, errors="coerce")
    known = paid.notna() & (paid <= origin)
    rep["payment_date"] = paid.where(known)
    rep["dpd"] = ((paid.where(known, origin) - rep.due_date).dt.days).clip(lower=0).astype(float)
    rep.loc[~known, "amount_paid"] = 0.0
    partial = known & (rep.amount_paid < rep.amount_due)
    rep["repayment_status"] = np.where(~known, "Overdue", np.where(partial, "Partially Paid", np.where(rep.dpd > 0, "Paid Late", "Paid On Time")))
    for column in ("exception_reason", "exception_evidence_available"):
        rep[column] = rep[column].astype(object)
        rep.loc[~known, column] = None
    tables["repayments"] = rep
    open_rows = rep.loc[~known]
    current = open_rows.groupby("loan_id").dpd.max()
    dq = facilities[["loan_id", "customer_id"]].copy()
    dq["current_dpd"] = dq.loan_id.map(current).fillna(0.0)
    tables["delinquency"] = dq
    for name in ("transactions", "exposure", "sme_indicators"):
        frame = tables[name]
        months = pd.to_datetime(frame.month, format="%Y-%m", errors="coerce")
        tables[name] = frame.loc[(months.dt.to_period("M") <= origin.to_period("M")) & frame.customer_id.isin(ids)].copy()
    return Dataset(tables=tables, issues=[], quarantined={}, signal_config=ds.signal_config)


def feature_rows(ds, profile, origin):
    if not pd.Timestamp(origin).is_month_end:
        raise ValueError("ML features require a month-end origin; monthly totals are not known mid-month")
    point = snapshot(ds, origin)
    definitions = _definitions(ds.signal_config)
    output = {}
    for cid, view in build_views(point, pd.Timestamp(origin), load_profile(profile)).items():
        if view.repay_months.empty:
            output[cid] = {"features":{sid:np.nan for sid in FEATURE_IDS}, "observed_months":0,
                "coverage":0.0,"current_dpd":0.0,"signals":{}}
            continue
        signals = {s.signal_id: s for s in evaluate_signals(view, definitions, pd.Timestamp(origin))}
        output[cid] = {
            "features": {sid: float(signals[sid].value) if sid in signals and signals[sid].applicable and signals[sid].evaluated and signals[sid].value is not None else np.nan for sid in FEATURE_IDS},
            "observed_months": len(view.repay_months),
            "coverage": sum(s.weight for s in signals.values() if s.applicable and s.evaluated) / max(sum(s.weight for s in signals.values() if s.applicable), 1),
            "current_dpd": float(view.delinquency.current_dpd.max()) if not view.delinquency.empty else 0.0,
            "signals": signals,
        }
    return output


def target(ds, cid, origin, observed_through):
    """Incident recorded 30+ DPD crossing in (origin, origin+3 calendar months].

    Missing horizon/schedule or ambiguous partial-payment outcomes are censored.
    A paid row crosses at due+30 only when its recorded payment is on/after it.
    """
    origin = pd.Timestamp(origin).normalize()
    end = horizon_end(origin)
    if end > pd.Timestamp(observed_through).normalize():
        return None
    rep = ds.tables["repayments"]
    rows = rep.loc[rep.customer_id == cid].copy()
    if rows.empty:
        return None
    due = pd.to_datetime(rows.due_date)
    paid = pd.to_datetime(rows.payment_date, errors="coerce")
    next_months = {str(origin.to_period("M") + i) for i in range(1,4)}
    observed_months = set(due.loc[(due > origin) & (due <= end)].dt.to_period("M").astype(str))
    if not next_months.issubset(observed_months):
        return None
    crossing = due + pd.to_timedelta(THRESHOLD_DPD, unit="D")
    in_window = (crossing > origin) & (crossing <= end)
    observed_unpaid = paid.isna() & rows.repayment_status.isin(("Overdue", "Missed"))
    proven = in_window & (observed_unpaid | (paid >= crossing))
    if proven.any():
        return 1
    # A recorded partial receipt does not establish the eventual full settlement date.
    partial = (rows.repayment_status == "Partially Paid") & (rows.amount_paid < rows.amount_due)
    if (in_window & (partial | (paid.isna() & ~observed_unpaid))).any() or rows.due_date.isna().any():
        return None
    return 0
