"""Unusual-behaviour detection: an isolation forest over each customer's recent behaviour.

Rules catch the patterns we anticipated; this flags combinations nobody wrote a
rule for. For each customer type (individuals and SMEs behave differently) a
forest is fitted on the portfolio's own behaviour features from the last six
months. The result is a percentile: 99 means more unusual than 99% of
comparable customers. The features furthest from typical are reported so the
flag can be explained.

Missing values are replaced by the group's typical (median) value, so missing
data never makes a customer look unusual.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ews.engine.views import CustomerViews, month_labels

MIN_GROUP = 30          # too few comparable customers to learn "typical"
SEED = 0

# feature key -> (label, unit). SME-only features are 0 for individuals.
FEATURES = {
    "inflow_trend": ("Income trend", "% per month"),
    "inflow_volatility": ("Income volatility", "ratio"),
    "inflow_vs_last_year": ("Income vs same months last year", "%"),
    "balance_change": ("Average balance change", "%"),
    "outflow_ratio": ("Outflows ÷ inflows", "ratio"),
    "bounced": ("Bounced transactions", "count"),
    "utilisation_change": ("Utilisation change", "pts"),
    "obligation_ratio_change": ("Obligations ÷ inflows change", "pts"),
    "inquiries": ("Credit inquiries (90 days)", "count"),
    "late_months": ("Late instalment months", "count"),
    "max_dpd": ("Worst days past due", "days"),
    "dpd_trend": ("Days-past-due trend", "days/month"),
    "receivable_days_change": ("Receivable days change", "days"),
    "late_filings": ("Late or missed tax filings", "count"),
}
SME_ONLY = {"receivable_days_change", "late_filings"}


@dataclass
class Anomaly:
    percentile: float | None          # 0-100, higher = more unusual; None when not assessed
    drivers: list[str]                # plain-English top contributors
    reason: str | None = None         # why not assessed


def _pct(a, b):
    return 100 * (a / b - 1) if b and b > 0 and a == a else np.nan


def features(v: CustomerViews, as_of: pd.Timestamp) -> dict[str, float]:
    window = month_labels(as_of, 6)
    f = dict.fromkeys(FEATURES, np.nan)

    tx = v.transactions.dropna(subset=["income_receipts"])
    recent = tx[tx["month"].isin(window)]
    if len(recent) >= 3:
        inc = recent["income_receipts"].astype(float).clip(lower=1)
        x = np.arange(len(inc))
        f["inflow_trend"] = 100 * (np.exp(np.polyfit(x, np.log(inc), 1)[0]) - 1)
        f["inflow_volatility"] = float(inc.std() / inc.mean())
        flows = recent.dropna(subset=["total_outflows", "total_inflows"]).tail(3)
        if len(flows):
            f["outflow_ratio"] = float((flows["total_outflows"] / flows["total_inflows"].clip(lower=1)).mean())
        f["bounced"] = float(recent["bounced_txns"].fillna(0).sum())
        bal = recent["avg_balance"].astype(float)
        if len(bal) >= 6:
            f["balance_change"] = _pct(bal.iloc[3:].mean(), bal.iloc[:3].mean())
        last3 = month_labels(as_of, 3)
        year_ago = [str(pd.Period(m, "M") - 12) for m in last3]
        by_month = tx.set_index("month")["income_receipts"]
        if all(m in by_month.index for m in last3 + year_ago):
            f["inflow_vs_last_year"] = _pct(by_month[last3].mean(), by_month[year_ago].mean())

    ex = v.exposure[v.exposure["month"].isin(window)]
    util = ex["utilisation_pct"].dropna()
    if len(util) >= 2:
        f["utilisation_change"] = float(util.iloc[-1] - util.iloc[0])
    if len(ex):
        f["inquiries"] = float(ex["new_credit_inquiries_90d"].dropna().iloc[-1]) \
            if ex["new_credit_inquiries_90d"].notna().any() else np.nan
        j = ex.merge(tx, on=["customer_id", "month"]).dropna(subset=["monthly_obligations", "total_inflows"])
        j = j[j["total_inflows"] > 0]
        if len(j) >= 4:
            half = len(j) // 2
            ratio = lambda rows: 100 * (j["monthly_obligations"] + j["external_bureau_obligations"].fillna(0)) \
                .iloc[rows].sum() / j["total_inflows"].iloc[rows].sum()
            f["obligation_ratio_change"] = float(ratio(slice(-half, None)) - ratio(slice(None, half)))

    rm = v.repay_months[v.repay_months["month"].isin(window)]
    if len(rm) >= 3:
        f["late_months"] = float(rm["late"].sum())
        f["max_dpd"] = float(rm["dpd"].max())
        f["dpd_trend"] = float(np.polyfit(np.arange(len(rm)), rm["dpd"].astype(float), 1)[0])

    if v.customer.get("customer_type") == "SME":
        sm = v.sme[v.sme["month"].isin(window)]
        rd = sm["receivable_days"].dropna()
        if len(rd) >= 2:
            f["receivable_days_change"] = float(rd.iloc[-2:].mean() - rd.iloc[:2].mean())
        if len(sm):
            f["late_filings"] = float((sm["tax_filing_status"].fillna("Filed On Time") != "Filed On Time").sum())
    else:
        f["receivable_days_change"] = f["late_filings"] = 0.0
    return f


def _fmt(key: str, value: float) -> str:
    unit = FEATURES[key][1]
    if unit in ("%", "% per month"):
        return f"{value:+.0f}%"
    if unit == "ratio":
        return f"{value:.2f}"
    if unit in ("pts", "days", "days/month") and key != "max_dpd":
        return f"{value:+.1f}"
    return f"{value:.0f}"


def score_portfolio_anomalies(views: dict[str, CustomerViews], as_of: pd.Timestamp) -> dict[str, Anomaly]:
    from sklearn.ensemble import IsolationForest

    rows = {cid: features(v, as_of) for cid, v in views.items()}
    frame = pd.DataFrame.from_dict(rows, orient="index")[list(FEATURES)]
    kind = pd.Series({cid: v.customer.get("customer_type") or "Unknown" for cid, v in views.items()})
    coverage = frame.drop(columns=list(SME_ONLY)).notna().mean(axis=1)

    out: dict[str, Anomaly] = {}
    for group, ids in kind.groupby(kind).groups.items():
        ids = [i for i in ids if coverage[i] >= 0.5]
        skipped = set(kind[kind == group].index) - set(ids)
        for cid in skipped:
            out[cid] = Anomaly(None, [], "Not enough recent behaviour data to compare")
        if len(ids) < MIN_GROUP:
            for cid in ids:
                out[cid] = Anomaly(None, [], f"Fewer than {MIN_GROUP} comparable customers to learn typical behaviour")
            continue
        g = frame.loc[ids]
        median = g.median()
        spread = (g.quantile(0.75) - g.quantile(0.25)).replace(0, np.nan)
        spread = spread.fillna(g.std().replace(0, np.nan)).fillna(1.0)
        filled = g.fillna(median)
        z = (filled - median) / spread
        forest = IsolationForest(n_estimators=300, random_state=SEED).fit(z.values)
        unusual = -forest.score_samples(z.values)                     # higher = more unusual
        pct = pd.Series(unusual, index=ids).rank(pct=True) * 100
        for cid in ids:
            top = z.loc[cid].abs().sort_values(ascending=False)
            drivers = [f"{FEATURES[k][0]} {_fmt(k, filled.loc[cid, k])} vs typical {_fmt(k, median[k])}"
                       for k in top.index[:3] if top[k] >= 2 and not np.isnan(g.loc[cid, k])]
            out[cid] = Anomaly(round(float(pct[cid]), 1), drivers)
    return out
