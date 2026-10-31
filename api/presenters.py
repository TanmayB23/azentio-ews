"""Read models for each screen, built only from contract fields and documented table columns."""
from __future__ import annotations

from dataclasses import asdict
import math

import numpy as np
import pandas as pd

from api.registry import Run, frame_records
from ews.contracts import CustomerResult, Dataset

BANDS = ["Critical", "High", "Medium", "Low", "Insufficient data"]
ELEVATED = {"High", "Critical"}
PILLARS = {"RB": "Repayment", "CF": "Cash flow", "EX": "Exposure", "SM": "Business", "UB": "Unusual behaviour"}


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def signal_status(s) -> str:
    if not s.applicable:
        return "Not applicable"
    if not s.evaluated:
        return "Missing data"
    return "Active" if s.strength > 0 else "No warning"


# --------------------------------------------------------------------------- watchlist
def watchlist_frame(run: Run, latest_reviews: dict[str, dict]) -> pd.DataFrame:
    t = run.dataset.tables
    cust = t["customers"].set_index("customer_id")
    fac = t["facilities"]
    as_of = pd.Timestamp(next(iter(run.results.values())).as_of) if run.results else pd.Timestamp.now()

    main_product = pd.Series(dtype=object)
    products = pd.Series(dtype=object)
    fac_total = pd.Series(dtype=float)
    if not fac.empty:
        ordered = fac.sort_values("outstanding_balance", ascending=False, na_position="last")
        main_product = ordered.drop_duplicates("customer_id").set_index("customer_id")["product_type"]
        products = fac.groupby("customer_id")["product_type"].agg(lambda s: sorted(set(s.dropna().astype(str))))
        fac_total = fac.groupby("customer_id")["outstanding_balance"].sum(min_count=1)

    ex = t["exposure"]
    exp_total = pd.Series(dtype=float)
    if not ex.empty:
        recent = ex[pd.to_datetime(ex["month"], format="%Y-%m", errors="coerce") <= as_of]
        exp_total = recent.sort_values("month").drop_duplicates("customer_id", keep="last") \
            .set_index("customer_id")["total_outstanding"]

    dq = t["delinquency"]
    bucket = pd.Series(dtype=object)
    worst_dpd = pd.Series(dtype=float)
    if not dq.empty:
        worst = dq.sort_values("current_dpd", ascending=False, na_position="last").drop_duplicates("customer_id")
        bucket = worst.set_index("customer_id")["delinquency_bucket"]
        worst_dpd = worst.set_index("customer_id")["current_dpd"]

    rows = []
    for cid, r in run.results.items():
        info = cust.loc[cid] if cid in cust.index else pd.Series(dtype=object)
        active = sorted((s for s in r.signals if s.evaluated and s.points > 0), key=lambda s: s.points, reverse=True)
        outstanding = _num(exp_total.get(cid)) if cid in exp_total.index else None
        if outstanding is None:
            outstanding = _num(fac_total.get(cid))
        review = latest_reviews.get(cid)
        rows.append({
            "customer_id": cid,
            "customer_name": info.get("customer_name") or cid,
            "customer_type": info.get("customer_type") or "Unknown",
            "segment": info.get("segment") or "Unknown",
            "portfolio": info.get("portfolio_classification") or "Unknown",
            "region": info.get("region") or "Unknown",
            "industry": info.get("industry") or "Unknown",
            "main_product": main_product.get(cid, "Unknown"),
            "products": products.get(cid, []),
            "total_outstanding": outstanding,
            "current_dpd": _num(worst_dpd.get(cid)),
            "delinquency_bucket": bucket.get(cid, "Unknown") if cid in bucket.index else "Unknown",
            "score": r.score,
            "band": r.band or "Insufficient data",
            "status": r.status,
            "monitoring_status": r.monitoring_status,
            "confidence": r.confidence,
            "signals_active": len(active),
            "top_factors": [{"signal_id": s.signal_id, "name": s.name, "points": round(s.points, 1)} for s in active[:3]],
            "summary": r.summary,
            "next_action": run.actions[cid][0].title if run.actions.get(cid) else None,
            "next_action_owner": run.actions[cid][0].owner if run.actions.get(cid) else None,
            "next_action_due": run.actions[cid][0].due_date if run.actions.get(cid) else None,
            "action_count": len(run.actions.get(cid, [])),
            "review_decision": review["decision"] if review else None,
            "reviewed_at": review["created_at"] if review else None,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["_band_rank"] = df["band"].map({b: i for i, b in enumerate(BANDS)})
    return df.sort_values(["score", "customer_id"], ascending=[False, True], na_position="last").reset_index(drop=True)


FILTERS = ("band", "main_product", "segment", "portfolio", "delinquency_bucket", "customer_type", "region")
SORTABLE = {"score", "customer_name", "total_outstanding", "confidence", "current_dpd", "customer_id"}


def filter_watchlist(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    if df.empty:
        return df
    out = df
    for key in FILTERS:
        values = params.get(key)
        if values:
            if key == "main_product":   # product filter matches any facility held
                out = out[out["products"].apply(lambda ps: any(v in ps for v in values))]
            else:
                out = out[out[key].isin(values)]
    review = params.get("review")
    if review == "unreviewed":
        out = out[out["review_decision"].isna()]
    elif review == "reviewed":
        out = out[out["review_decision"].notna()]
    q = (params.get("q") or "").strip().lower()
    if q:
        out = out[out["customer_id"].str.lower().str.contains(q, regex=False)
                  | out["customer_name"].str.lower().str.contains(q, regex=False)]
    sort = params.get("sort") or "score"
    if sort in SORTABLE:
        asc = params.get("order") == "asc"
        out = out.sort_values([sort, "customer_id"], ascending=[asc, True], na_position="last")
    return out


def facets(df: pd.DataFrame) -> dict:
    if df.empty:
        return {k: [] for k in FILTERS}
    out = {k: sorted(df[k].dropna().astype(str).unique()) for k in FILTERS if k != "main_product"}
    out["main_product"] = sorted({p for ps in df["products"] for p in ps})
    out["band"] = [b for b in BANDS if b in set(df["band"])]
    return out


def watchlist_rows(df: pd.DataFrame) -> list[dict]:
    return frame_records(df.drop(columns=["_band_rank"], errors="ignore"))


# --------------------------------------------------------------------------- overview
def summary(run: Run, df: pd.DataFrame, latest_reviews: dict, quality: dict) -> dict:
    bands = {b: int((df["band"] == b).sum()) for b in BANDS} if not df.empty else {b: 0 for b in BANDS}
    exposure = {b: float(df.loc[df["band"] == b, "total_outstanding"].sum()) for b in BANDS} if not df.empty else {}
    total_exposure = float(df["total_outstanding"].sum()) if not df.empty else 0.0
    elevated = df[df["band"].isin(ELEVATED)] if not df.empty else df
    scored = df[df["score"].notna()] if not df.empty else df

    hist = np.histogram(scored["score"], bins=20, range=(0, 100))[0].tolist() if len(scored) else [0] * 20
    thresholds = [{"threshold": t, "customers": int((scored["score"] >= t).sum()) if len(scored) else 0,
                   "exposure": float(scored.loc[scored["score"] >= t, "total_outstanding"].sum()) if len(scored) else 0.0}
                  for t in range(5, 101, 5)]
    signal_counts: dict[str, dict] = {}
    pillar_counts = {name: 0 for name in PILLARS.values()}
    for r in run.results.values():
        fired_pillars = set()
        for s in r.signals:
            if s.evaluated and s.points > 0:
                entry = signal_counts.setdefault(s.signal_id, {"signal_id": s.signal_id, "name": s.name,
                                                               "pillar": PILLARS.get(s.pillar, s.pillar), "customers": 0})
                entry["customers"] += 1
                fired_pillars.add(PILLARS.get(s.pillar, s.pillar))
        for p in fired_pillars:
            pillar_counts[p] = pillar_counts.get(p, 0) + 1

    decisions: dict[str, int] = {}
    for rev in latest_reviews.values():
        decisions[rev["decision"]] = decisions.get(rev["decision"], 0) + 1
    reviewed_elevated = int(elevated["review_decision"].notna().sum()) if len(elevated) else 0

    top = df[df["band"].isin(ELEVATED)].head(8) if not df.empty else df
    return {
        "run": run.meta,
        "as_of": next(iter(run.results.values())).as_of if run.results else None,
        "customers": int(len(df)),
        "bands": bands,
        "exposure_by_band": exposure,
        "total_exposure": total_exposure,
        "exposure_at_risk": exposure.get("High", 0.0) + exposure.get("Critical", 0.0),
        "elevated": int(len(elevated)),
        "average_confidence": float(df["confidence"].mean()) if not df.empty else 0.0,
        "score_histogram": hist,
        "thresholds": thresholds,
        "top_signals": sorted(signal_counts.values(), key=lambda e: e["customers"], reverse=True)[:6],
        "pillar_prevalence": pillar_counts,
        "reviews": {"elevated": int(len(elevated)), "reviewed": reviewed_elevated, "decisions": decisions},
        "actions": _action_counts(run),
        "priority": watchlist_rows(top),
        "clusters": [cluster_dict(c, run, df) for c in run.clusters[:4]],
        "quality": quality,
    }


def cluster_dict(c, run: Run, df: pd.DataFrame) -> dict:
    members = df[df["customer_id"].isin(c.customer_ids)] if not df.empty else df
    d = asdict(c)
    d["exposure"] = float(members["total_outstanding"].sum()) if len(members) else 0.0
    d["elevated_exposure"] = float(members.loc[members["band"].isin(ELEVATED), "total_outstanding"].sum()) \
        if len(members) else 0.0
    names = {}
    for r in run.results.values():
        for s in r.signals:
            names[s.signal_id] = s.name
    d["top_signal_names"] = [names.get(s, s) for s in c.top_signals]
    d["members"] = watchlist_rows(members)
    return d


# --------------------------------------------------------------------------- quality
def quality_report(ds: Dataset) -> dict:
    issues = [asdict(i) for i in ds.issues]
    count = lambda key, val: sum(1 for i in issues if i[key] == val)
    return {
        "tables": {name: int(len(df)) for name, df in ds.tables.items()},
        "issue_count": len(issues),
        "severity": {"error": count("severity", "error"), "warning": count("severity", "warning")},
        "action": {a: count("action", a) for a in ("quarantined", "repaired", "kept")},
        "quarantined": {name: int(len(df)) for name, df in ds.quarantined.items()},
        "blocking": [i for i in issues if i["severity"] == "error" and i["action"] == "kept"],
        "has_signal_config": ds.signal_config is not None,
        "issues": issues,
    }


# --------------------------------------------------------------------------- customer
def _for(ds: Dataset, table: str, cid: str) -> pd.DataFrame:
    df = ds.tables.get(table)
    if df is None or df.empty or "customer_id" not in df:
        return pd.DataFrame()
    return df[df["customer_id"] == cid]


def customer_detail(run: Run, cid: str, row: dict | None) -> dict:
    ds, r = run.dataset, run.results[cid]
    profile = _for(ds, "customers", cid)
    info = frame_records(profile)[0] if not profile.empty else {"customer_id": cid}

    rep = _for(ds, "repayments", cid)
    as_of = pd.Timestamp(r.as_of)
    repayment_months = []
    if not rep.empty:
        due = rep[rep["due_date"] <= as_of].copy()
        due["month"] = due["due_date"].dt.strftime("%Y-%m")
        for month, g in due.groupby("month"):
            repayment_months.append({
                "month": month, "worst_dpd": _num(g["dpd"].max()), "instalments": int(len(g)),
                "late": int((g["dpd"].fillna(0) > 0).sum()),
                "partial": int((g["repayment_status"] == "Partially Paid").sum()),
                "unpaid": int(g["repayment_status"].isin(["Overdue", "Missed"]).sum()),
                "amount_due": _num(g["amount_due"].sum()), "amount_paid": _num(g["amount_paid"].sum()),
            })
    recent_repayments = frame_records(rep.sort_values("due_date", ascending=False), limit=36)

    def monthly(table, cols):
        df = _for(ds, table, cid)
        if df.empty:
            return []
        keep = ["month", *[c for c in cols if c in df.columns]]
        return frame_records(df.sort_values("month")[keep])

    signals = []
    for s in r.signals:
        d = asdict(s)
        d["pillar_name"] = PILLARS.get(s.pillar, s.pillar)
        d["status"] = signal_status(s)
        signals.append(d)

    return {
        "customer": info,
        "row": row,
        "result": {**{k: v for k, v in asdict(r).items() if k != "signals"}, "signals": signals},
        "facilities": frame_records(_for(ds, "facilities", cid)),
        "delinquency": frame_records(_for(ds, "delinquency", cid)),
        "repayment_months": repayment_months,
        "recommended_actions": [asdict(a) for a in run.actions.get(cid, [])],
        "repayments": recent_repayments,
        "transactions": monthly("transactions", ["income_receipts", "other_inflows", "total_inflows",
                                                 "total_outflows", "avg_balance", "closing_balance", "bounced_txns"]),
        "exposure": monthly("exposure", ["num_active_facilities", "total_outstanding", "total_credit_limit",
                                         "utilisation_pct", "monthly_obligations", "external_bureau_obligations",
                                         "new_credit_inquiries_90d"]),
        "sme": monthly("sme_indicators", ["tax_reported_turnover", "tax_filing_status", "receivable_days",
                                          "payable_days"]),
    }


def _action_counts(run: Run) -> dict:
    by_owner: dict[str, int] = {}
    by_action: dict[str, dict] = {}
    for recs in run.actions.values():
        for a in recs:
            by_owner[a.owner] = by_owner.get(a.owner, 0) + 1
            entry = by_action.setdefault(a.action_id, {"action_id": a.action_id, "title": a.title,
                                                      "owner": a.owner, "customers": 0})
            entry["customers"] += 1
    return {"customers_with_actions": sum(1 for r in run.actions.values() if r),
            "by_owner": dict(sorted(by_owner.items(), key=lambda kv: -kv[1])),
            "by_action": sorted(by_action.values(), key=lambda e: -e["customers"])}
