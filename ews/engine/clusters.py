"""Portfolio concentration: segments where emerging risk is over-represented.

Two tests per grouping (industry x region, industry, region, segment,
portfolio, main product), each a one-sided binomial test against the portfolio:
  elevated risk - share of scored customers at Medium or above
  shared signal - share of customers with the same warning signal active,
                  which catches early-stage clusters before scores are high
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
                    min_size: int = 5, min_hits: int = 4, min_lift: float = 1.5, max_p: float = 0.001,
                    signal_min_lift: float = 2.5, signal_max_p: float = 0.0001) -> list[Cluster]:
    scored = {r.customer_id: r for r in results if r.status == "Scored"}
    if not scored:
        return []
    cust = ds.tables["customers"].set_index("customer_id")
    cust = cust.loc[cust.index.intersection(list(scored))].copy()
    cust["main_product"] = _main_product(ds.tables["facilities"]).reindex(cust.index)
    cust["elevated"] = [scored[c].score >= elevated_score for c in cust.index]
    fired = {c: {s.signal_id for s in scored[c].signals if s.points > 0} for c in cust.index}
    signal_ids = sorted(set().union(*fired.values()))
    for sid in signal_ids:
        cust[sid] = [sid in fired[c] for c in cust.index]
    names = {s.signal_id: s.name for r in scored.values() for s in r.signals}
    tests = [("elevated risk", "elevated", min_lift, max_p)] + \
        [(f"shared signal {sid} ({names[sid]})", sid, signal_min_lift, signal_max_p) for sid in signal_ids]
    base = {col: cust[col].mean() for _, col, _, _ in tests}

    def best_test(g):
        best = None
        for basis, col, lift_min, p_max in tests:
            n, k = len(g), int(g[col].sum())
            if n < min_size or base[col] == 0 or k < min_hits:
                continue
            lift, p = (k / n) / base[col], _binom_tail(k, n, base[col])
            if lift >= lift_min and p <= p_max and (best is None or p < best[2]):
                best = (basis, lift, p)
        return best

    candidates = []
    for dim, cols in DIMENSIONS.items():
        for value, g in cust.groupby(cols, dropna=True):
            best = best_test(g)
            if best:
                label = "|".join(value) if isinstance(value, tuple) else str(value)
                candidates.append((best[2], dim, label, g))

    # strongest first; a broader group must still be significant without the members of
    # stronger clusters inside it, otherwise it only echoes them (e.g. a region holding one hot industry)
    found: list[Cluster] = []
    for _, dim, label, g in sorted(candidates, key=lambda c: c[0]):
        members = set(g.index)
        nested = set().union(*[set(c.customer_ids) for c in found if set(c.customer_ids) < members] or [set()])
        best = best_test(g.drop(index=list(nested))) if nested else best_test(g)
        if not best:
            continue
        top = Counter(s for c in g.index for s in fired[c])
        found.append(Cluster(dimension=dim, value=label, n_customers=len(g), n_elevated=int(g["elevated"].sum()),
                             lift=round(best[1], 2), top_signals=[s for s, _ in top.most_common(3)],
                             customer_ids=list(g.index), p_value=round(best[2], 6), basis=best[0]))
    return found


def _main_product(fac: pd.DataFrame) -> pd.Series:
    if fac.empty:
        return pd.Series(dtype=object)
    top = fac.sort_values("outstanding_balance", ascending=False).drop_duplicates("customer_id")
    return top.set_index("customer_id")["product_type"]


def _binom_tail(k: int, n: int, p: float) -> float:
    return float(sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1)))

