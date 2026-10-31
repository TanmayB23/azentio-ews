"""Portfolio concentration: segments where elevated risk is over-represented.

For each grouping (industry×region, industry, region, segment, portfolio,
main product) compare the share of scored customers at Medium or above with
the portfolio share, and test the excess with a one-sided binomial test.
"""
from __future__ import annotations

from collections import Counter
from math import comb

import pandas as pd

from ews.contracts import Cluster, CustomerResult, Dataset

DIMENSIONS = {
    "industry x region": ["industry", "region"],
    "industry": ["industry"],
    "region": ["region"],
    "segment": ["segment"],
    "portfolio": ["portfolio_classification"],
    "product": ["main_product"],
}


def detect_clusters(ds: Dataset, results: list[CustomerResult], elevated_score: float = 25,
                    min_size: int = 5, min_elevated: int = 3, min_lift: float = 1.5,
                    max_p: float = 0.05) -> list[Cluster]:
    scored = {r.customer_id: r for r in results if r.status == "Scored"}
    if not scored:
        return []
    cust = ds.tables["customers"].set_index("customer_id")
    cust = cust.loc[cust.index.intersection(list(scored))].copy()
    cust["main_product"] = _main_product(ds.tables["facilities"]).reindex(cust.index)
    cust["elevated"] = [scored[c].score >= elevated_score for c in cust.index]
    base = cust["elevated"].mean()
    if base == 0:
        return []

    clusters = []
    for dim, cols in DIMENSIONS.items():
        for value, g in cust.groupby(cols, dropna=True):
            n, k = len(g), int(g["elevated"].sum())
            if n < min_size or k < min_elevated:
                continue
            lift = (k / n) / base
            p = _binom_tail(k, n, base)
            if lift < min_lift or p > max_p:
                continue
            elevated_ids = list(g.index[g["elevated"]])
            fired = Counter(s.signal_id for c in elevated_ids for s in scored[c].signals if s.points > 0)
            label = "|".join(value) if isinstance(value, tuple) else str(value)
            clusters.append(Cluster(dimension=dim, value=label, n_customers=n, n_elevated=k,
                                    lift=round(lift, 2), top_signals=[s for s, _ in fired.most_common(3)],
                                    customer_ids=list(g.index), p_value=round(p, 4)))
    return _drop_redundant(sorted(clusters, key=lambda c: (c.p_value, -c.lift)))


def _main_product(fac: pd.DataFrame) -> pd.Series:
    if fac.empty:
        return pd.Series(dtype=object)
    top = fac.sort_values("outstanding_balance", ascending=False).drop_duplicates("customer_id")
    return top.set_index("customer_id")["product_type"]


def _binom_tail(k: int, n: int, p: float) -> float:
    return float(sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1)))


def _drop_redundant(clusters: list[Cluster]) -> list[Cluster]:
    """Drop a broad cluster whose elevated customers are almost all inside a stronger, narrower one."""
    kept: list[Cluster] = []
    for c in clusters:
        members = set(c.customer_ids)
        if any(k.n_customers < c.n_customers and set(k.customer_ids) <= members
               and k.n_elevated >= 0.8 * c.n_elevated for k in kept):
            continue
        kept.append(c)
    return kept
