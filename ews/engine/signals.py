"""Signal metrics. Each metric is looked up by the first word of the `metric`
field in the signal definitions, so thresholds, weights, windows and minimum
observations stay configurable.

A metric returns a Measure. value=None with applicable=False means the signal
does not apply to this customer; value=None with applicable=True means the
data needed is missing.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ews.contracts import SignalResult
from ews.engine.config import pillar_of
from ews.engine.views import CustomerViews, month_index, month_labels


@dataclass
class Measure:
    value: float | None
    n_obs: int
    evidence: list[str] = field(default_factory=list)
    applicable: bool = True
    note: str | None = None


def _window(df: pd.DataFrame, as_of: pd.Timestamp, months: int) -> pd.DataFrame:
    if df.empty:
        return df
    return df[df["month"].isin(month_labels(as_of, max(1, months)))]


# ----------------------------- repayment ----------------------------------- #
def late_instalments_in_window(v: CustomerViews, as_of, w, s=None) -> Measure:
    rm = _window(v.repay_months, as_of, w)
    late = rm[rm["late"]]
    return Measure(float(len(late)), len(rm), [r[0] for r in late["repayment_ids"]])


def slope_of_dpd_per_month(v: CustomerViews, as_of, w, s=None) -> Measure:
    rm = _window(v.repay_months, as_of, w)
    if len(rm) < 2:
        return Measure(None, len(rm))
    x = np.array([-month_index(m, as_of) for m in rm["month"]], dtype=float)
    slope = float(np.polyfit(x, rm["dpd"].astype(float), 1)[0])
    return Measure(slope, len(rm), list(rm["month"]))


def partially_paid_instalments_in_window(v: CustomerViews, as_of, w, s=None) -> Measure:
    rm = _window(v.repay_months, as_of, w)
    part = rm[rm["partial"]]
    return Measure(float(len(part)), len(rm), [r[0] for r in part["repayment_ids"]])


def current_dpd(v: CustomerViews, as_of, w, s=None) -> Measure:
    if not v.delinquency.empty and v.delinquency["current_dpd"].notna().any():
        d = v.delinquency
        worst = d.loc[d["current_dpd"].idxmax()]
        return Measure(float(worst["current_dpd"]), len(d), [worst["loan_id"]])
    rows = v.repay_rows
    if rows.empty:
        return Measure(None, 0)
    unpaid = rows[rows["repayment_status"].isin(("Overdue", "Missed"))]
    if unpaid.empty:
        return Measure(0.0, len(rows))
    return Measure(float((as_of - unpaid["due_date"].min()).days), len(rows), list(unpaid["repayment_id"]))


# ----------------------------- cash flow ----------------------------------- #
def consecutive_months_total_inflows_declining(v: CustomerViews, as_of, w, s=None) -> Measure:
    """Consecutive month-on-month declines ending in the latest month. Optional
    definition keys: `series` (column to read, default total_inflows) and
    `min_total_decline_pct` (a run whose overall drop is smaller counts as 0)."""
    s = s or {}
    col = s.get("series") or "total_inflows"
    tx = _window(v.transactions, as_of, w).dropna(subset=[col])
    if tx.empty:
        return Measure(None, 0)
    months, vals = list(tx["month"]), list(tx[col])
    n = 0
    for i in range(len(vals) - 1, 0, -1):
        adjacent = month_index(months[i - 1], as_of) - month_index(months[i], as_of) == 1
        if adjacent and vals[i] < vals[i - 1]:
            n += 1
        else:
            break
    run = months[len(months) - 1 - n:]
    if n and vals[-1 - n] > 0:
        drop = 100 * (1 - vals[-1] / vals[-1 - n])
        if drop < float(s.get("min_total_decline_pct") or 0):
            return Measure(0.0, len(tx), note=f"{n} small declines totalling {drop:.1f}%")
    return Measure(float(n), len(tx), run)


def _half_change(v: CustomerViews, as_of, w, col) -> Measure:
    tx = _window(v.transactions, as_of, w).dropna(subset=[col])
    if len(tx) < 2:
        return Measure(None, len(tx))
    half = len(tx) // 2
    prior, last = tx[col].iloc[:half].mean(), tx[col].iloc[-half:].mean()
    if prior <= 0:
        return Measure(None, len(tx), note=f"prior average {col} is zero")
    return Measure(float(100 * (last / prior - 1)), len(tx), list(tx["month"]))


def pct_change_avg_inflow_last3m_vs_prior3m(v, as_of, w, s=None) -> Measure:
    return _half_change(v, as_of, w, "total_inflows")


def pct_change_avg_balance_last3m_vs_prior3m(v, as_of, w, s=None) -> Measure:
    return _half_change(v, as_of, w, "avg_balance")


def months_outflow_gt_inflow(v: CustomerViews, as_of, w, s=None) -> Measure:
    tx = _window(v.transactions, as_of, w).dropna(subset=["total_inflows", "total_outflows"])
    hit = tx[tx["total_outflows"] > tx["total_inflows"]]
    return Measure(float(len(hit)), len(tx), list(hit["month"]))


def bounced_txns_in_window(v: CustomerViews, as_of, w, s=None) -> Measure:
    tx = _window(v.transactions, as_of, w).dropna(subset=["bounced_txns"])
    hit = tx[tx["bounced_txns"] > 0]
    return Measure(float(tx["bounced_txns"].sum()), len(tx), list(hit["month"]))


# ----------------------------- exposure ------------------------------------ #
def utilisation_pct_change_in_points(v: CustomerViews, as_of, w, s=None) -> Measure:
    if v.exposure.empty or v.exposure["utilisation_pct"].isna().all():
        has_rev = (v.facilities["facility_type"] == "Revolving").any()
        if not has_rev:
            return Measure(None, 0, applicable=False, note="no revolving facility")
    ex = _window(v.exposure, as_of, w).dropna(subset=["utilisation_pct"])
    if len(ex) < 2:
        return Measure(None, len(ex))
    return Measure(float(ex["utilisation_pct"].iloc[-1] - ex["utilisation_pct"].iloc[0]), len(ex),
                   [ex["month"].iloc[0], ex["month"].iloc[-1]])


def new_facilities_in_window(v: CustomerViews, as_of, w, s=None) -> Measure:
    """Facilities opened in the window, not counting the customer's first
    facility (or any opened with it) - a new customer is not adding credit."""
    f = v.facilities.dropna(subset=["disbursement_date"])
    if f.empty:
        return Measure(None, 0)
    first = f["disbursement_date"].min()
    start = as_of - pd.DateOffset(months=int(w))
    new = f[(f["disbursement_date"] > start) & (f["disbursement_date"] > first + pd.Timedelta(days=30))]
    return Measure(float(len(new)), len(f), list(new["loan_id"]))


def change_in_obligation_to_inflow_pct_points(v: CustomerViews, as_of, w, s=None) -> Measure:
    ex = _window(v.exposure, as_of, w)
    tx = _window(v.transactions, as_of, w)
    if ex.empty or tx.empty:
        return Measure(None, 0)
    j = ex.merge(tx, on=["customer_id", "month"]).dropna(subset=["monthly_obligations", "total_inflows"])
    j = j[j["total_inflows"] > 0]
    if len(j) < 2:
        return Measure(None, len(j))
    ratio = 100 * (j["monthly_obligations"] + j["external_bureau_obligations"].fillna(0)) / j["total_inflows"]
    half = len(j) // 2
    return Measure(float(ratio.iloc[-half:].mean() - ratio.iloc[:half].mean()), len(j), list(j["month"]))


def new_credit_inquiries_90d_latest(v: CustomerViews, as_of, w, s=None) -> Measure:
    ex = _window(v.exposure, as_of, w).dropna(subset=["new_credit_inquiries_90d"])
    if ex.empty:
        return Measure(None, 0)
    return Measure(float(ex["new_credit_inquiries_90d"].iloc[-1]), len(ex), [ex["month"].iloc[-1]])


# ----------------------------- business (SME) ------------------------------ #
def _sme_window(v: CustomerViews, as_of, w):
    if v.customer.get("customer_type") != "SME":
        return None
    return _window(v.sme, as_of, w)


def tax_filings_late_or_missed_in_window(v: CustomerViews, as_of, w, s=None) -> Measure:
    sm = _sme_window(v, as_of, w)
    if sm is None:
        return Measure(None, 0, applicable=False, note="individual customer")
    sm = sm.dropna(subset=["tax_filing_status"])
    hit = sm[sm["tax_filing_status"] != "Filed On Time"]
    return Measure(float(len(hit)), len(sm), list(hit["month"]))


def receivable_days_change_in_window(v: CustomerViews, as_of, w, s=None) -> Measure:
    sm = _sme_window(v, as_of, w)
    if sm is None:
        return Measure(None, 0, applicable=False, note="individual customer")
    sm = sm.dropna(subset=["receivable_days"])
    if len(sm) < 2:
        return Measure(None, len(sm))
    half = max(1, len(sm) // 3)
    change = sm["receivable_days"].iloc[-half:].mean() - sm["receivable_days"].iloc[:half].mean()
    return Measure(float(change), len(sm), list(sm["month"]))


METRICS = {fn.__name__: fn for fn in (
    late_instalments_in_window, slope_of_dpd_per_month, partially_paid_instalments_in_window, current_dpd,
    consecutive_months_total_inflows_declining, pct_change_avg_inflow_last3m_vs_prior3m,
    pct_change_avg_balance_last3m_vs_prior3m, months_outflow_gt_inflow, bounced_txns_in_window,
    utilisation_pct_change_in_points, new_facilities_in_window, change_in_obligation_to_inflow_pct_points,
    new_credit_inquiries_90d_latest, tax_filings_late_or_missed_in_window, receivable_days_change_in_window,
)}


def strength(value: float, trigger: float, saturation: float) -> float:
    """0 at trigger, 1 at saturation, linear between; works for either direction."""
    if saturation == trigger:
        return float(value >= trigger)
    return float(np.clip((value - trigger) / (saturation - trigger), 0.0, 1.0))


def evaluate_signals(v: CustomerViews, defs: dict, as_of: pd.Timestamp) -> list[SignalResult]:
    results = []
    for s in defs["signals"]:
        metric = str(s["metric"]).split()[0]
        trig, sat, weight = float(s["trigger"]), float(s["saturation"]), float(s["weight"])
        common = dict(signal_id=s["signal_id"], name=s["signal_name"], pillar=pillar_of(s),
                      trigger=trig, saturation=sat, weight=weight)
        fn = METRICS.get(metric)
        if fn is None:
            results.append(SignalResult(**common, evaluated=False, reason_not_evaluated=f"no metric '{metric}'",
                                        value=None, strength=0.0, points=0.0, evidence=[]))
            continue
        m = fn(v, as_of, int(s.get("window_months") or 0), s)
        min_obs = int(s.get("min_observations") or 1)
        if not m.applicable:
            ok, reason = False, f"Not applicable: {m.note}"
        elif m.value is None or m.n_obs < min_obs:
            ok = False
            reason = m.note or f"Insufficient data: {m.n_obs} of {min_obs} required observations ({s.get('requires')})"
        else:
            ok, reason = True, None
        results.append(SignalResult(
            **common, evaluated=ok, reason_not_evaluated=reason, value=m.value,
            strength=strength(m.value, trig, sat) if ok else 0.0, points=0.0,
            evidence=m.evidence if ok else [], applicable=m.applicable,
        ))
    return results
