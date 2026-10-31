"""Customer-month views built from the validated tables.

Repayments are collapsed to one row per customer per due month using the worst
DPD across that customer's loans. Missing months stay missing (never zero-filled).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ews.contracts import Dataset

UNPAID = ("Overdue", "Missed")
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass
class CustomerViews:
    customer: dict
    facilities: pd.DataFrame
    repay_rows: pd.DataFrame       # instalment level, due on or before as_of
    repay_months: pd.DataFrame     # one row per due month
    delinquency: pd.DataFrame
    exposure: pd.DataFrame         # one row per month, sorted
    transactions: pd.DataFrame     # one row per month, sorted
    sme: pd.DataFrame              # SME indicators, one row per month (empty for individuals)


def month_labels(as_of: pd.Timestamp, n: int) -> list[str]:
    """The n calendar months ending with the as-of month, oldest first."""
    end = as_of.to_period("M")
    return [str(end - i) for i in range(n - 1, -1, -1)]


def month_index(label: str, as_of: pd.Timestamp) -> int:
    """Months before the as-of month (0 = as-of month)."""
    return (as_of.to_period("M") - pd.Period(label, "M")).n


def build_views(ds: Dataset, as_of: pd.Timestamp, profile: dict) -> dict[str, CustomerViews]:
    t = ds.tables
    rep = t["repayments"]
    rep = rep[rep["due_date"] <= as_of].copy()
    rep["month"] = rep["due_date"].dt.to_period("M").astype(str)
    rep = _mark_calendar_exceptions(rep, profile)

    by = lambda df: dict(tuple(df.groupby("customer_id"))) if len(df) else {}
    rep_g, fac_g, del_g = by(rep), by(t["facilities"]), by(t["delinquency"])
    exp_g, txn_g, sme_g = by(t["exposure"]), by(t["transactions"]), by(t["sme_indicators"])
    empty = lambda name: t[name].iloc[0:0]
    rep_empty = rep.iloc[0:0]

    views = {}
    for cust in t["customers"].to_dict("records"):
        cid = cust["customer_id"]
        rows = rep_g.get(cid, rep_empty)
        views[cid] = CustomerViews(
            customer=cust,
            facilities=fac_g.get(cid, empty("facilities")),
            repay_rows=rows,
            repay_months=_repay_months(rows),
            delinquency=del_g.get(cid, empty("delinquency")),
            exposure=exp_g.get(cid, empty("exposure")).sort_values("month"),
            transactions=txn_g.get(cid, empty("transactions")).sort_values("month"),
            sme=sme_g.get(cid, empty("sme_indicators")).sort_values("month"),
        )
    return views


def _mark_calendar_exceptions(rep: pd.DataFrame, profile: dict) -> pd.DataFrame:
    """A short delay on a weekend/holiday due date counts as an exception with evidence."""
    cal = profile.get("calendar", {})
    weekend = {WEEKDAYS.index(d) for d in cal.get("weekend", [])}
    holidays = set(pd.to_datetime(cal.get("holidays", [])))
    grace = cal.get("holiday_grace_days", 0)
    non_business = rep["due_date"].dt.weekday.isin(weekend) | rep["due_date"].isin(holidays)
    hit = non_business & (rep["dpd"] > 0) & (rep["dpd"] <= grace) & rep["exception_reason"].isna() \
        & rep["payment_date"].notna()
    rep.loc[hit, "exception_reason"] = "Due date fell on a non-business day (profile calendar)"
    rep.loc[hit, "exception_evidence_available"] = "Y"
    return rep


def _repay_months(rows: pd.DataFrame) -> pd.DataFrame:
    cols = ["month", "dpd", "late", "partial", "unpaid", "exception_reason", "evidence", "repayment_ids"]
    if rows.empty:
        return pd.DataFrame(columns=cols)
    out = []
    for month, g in rows.groupby("month"):
        worst = g.loc[g["dpd"].fillna(0).idxmax()]
        exc = g["exception_reason"].dropna()
        out.append({
            "month": month,
            "dpd": float(g["dpd"].fillna(0).max()),
            "late": bool((g["dpd"].fillna(0) > 0).any()),
            "partial": bool((g["repayment_status"] == "Partially Paid").any()),
            "unpaid": bool(g["repayment_status"].isin(UNPAID).any()),
            "exception_reason": exc.iloc[0] if len(exc) else None,
            "evidence": bool((g["exception_evidence_available"] == "Y").any()),
            "repayment_ids": [worst["repayment_id"]] + [r for r in g["repayment_id"] if r != worst["repayment_id"]],
        })
    return pd.DataFrame(out, columns=cols).sort_values("month").reset_index(drop=True)
