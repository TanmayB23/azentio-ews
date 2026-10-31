"""Presentation transforms using only contract fields and documented table columns."""
import pandas as pd
from ews.contracts import CustomerResult, Dataset


def customer_table(ds: Dataset, table: str, customer_id: str) -> pd.DataFrame:
    frame = ds.tables.get(table, pd.DataFrame())
    if "customer_id" not in frame:
        return pd.DataFrame()
    return frame.loc[frame.customer_id.astype(str) == customer_id].copy()


def watchlist(ds: Dataset, results: list[CustomerResult]) -> pd.DataFrame:
    rows = []
    for result in results:
        cid = result.customer_id
        customer = customer_table(ds, "customers", cid)
        info = customer.iloc[0] if not customer.empty else pd.Series(dtype=object)
        facilities = customer_table(ds, "facilities", cid)
        exposure = customer_table(ds, "exposure", cid)
        delinquency = customer_table(ds, "delinquency", cid)
        product = "Unknown"
        products = ()
        outstanding = None
        if not facilities.empty:
            if "product_type" in facilities:
                products = tuple(sorted(facilities.product_type.dropna().astype(str).unique()))
                if "outstanding_balance" in facilities:
                    totals = pd.to_numeric(facilities.outstanding_balance, errors="coerce")
                    product = str(facilities.loc[totals.idxmax(), "product_type"]) if totals.notna().any() else (products[0] if products else "Unknown")
                else:
                    product = products[0] if products else "Unknown"
            if "outstanding_balance" in facilities:
                outstanding = pd.to_numeric(facilities.outstanding_balance, errors="coerce").sum(min_count=1)
        if not exposure.empty and {"month", "total_outstanding"}.issubset(exposure.columns):
            dated = exposure.assign(_month=pd.to_datetime(exposure.month, format="%Y-%m", errors="coerce"))
            dated = dated.loc[dated._month <= pd.Timestamp(result.as_of)].sort_values("_month")
            if not dated.empty:
                outstanding = pd.to_numeric(pd.Series([dated.iloc[-1].total_outstanding]), errors="coerce").iloc[0]
        # Pick the current bucket of the facility with the worst current DPD.
        # Never substitute the historical dpd_bucket_3m_ago field.
        dpd = pd.to_numeric(delinquency.get("current_dpd", pd.Series(dtype=float)), errors="coerce")
        bucket = "Unknown"
        if "delinquency_bucket" in delinquency and dpd.notna().any():
            current = delinquency.loc[dpd.idxmax(), "delinquency_bucket"]
            bucket = str(current) if pd.notna(current) else "Unknown"
        top = sorted((s for s in result.signals if s.applicable and s.evaluated), key=lambda s: s.points, reverse=True)[:3]
        rows.append({"customer_id": cid, "customer_name": info.get("customer_name", cid),
            "main_product": product, "total_outstanding": outstanding,
            "score": result.score, "band": result.band or "Insufficient data",
            "top_3_factors": "; ".join(f"{s.name} ({s.points:.1f})" for s in top) or "Not evaluated",
            "monitoring_status": result.monitoring_status, "segment": info.get("segment", "Unknown"),
            "portfolio": info.get("portfolio_classification", "Unknown"), "delinquency_bucket": bucket,
            "_products": products})
    columns = ["customer_id", "customer_name", "main_product", "total_outstanding", "score", "band", "top_3_factors", "monitoring_status", "segment", "portfolio", "delinquency_bucket", "_products"]
    return pd.DataFrame(rows, columns=columns).sort_values(["score", "customer_id"], ascending=[False, True], na_position="last").reset_index(drop=True)


def monthly_chart(frame: pd.DataFrame, date: str, values: list[str], worst: bool = False) -> pd.DataFrame:
    if frame.empty or not {date, *values}.issubset(frame.columns):
        return pd.DataFrame()
    frame = frame.copy()
    frame[date] = pd.to_datetime(frame[date], format="%Y-%m" if date == "month" else "%Y-%m-%d", errors="coerce").dt.to_period("M").dt.to_timestamp()
    for column in values:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=[date])
    if frame.empty:
        return pd.DataFrame()
    grouped = frame.groupby(date)[values].max() if worst else frame.groupby(date)[values].sum(min_count=1)
    # Missing months remain gaps; never invent zero activity or zero delinquency.
    return grouped.reindex(pd.date_range(grouped.index.min(), grouped.index.max(), freq="MS"))


def signal_rows(signals):
    """Distinguish applicability, data coverage, and active/inactive warnings."""
    labels = {"RB": "Repayment", "CF": "Cash flow", "EX": "Exposure", "SM": "Business"}
    return [{"Signal": signal.signal_id, "Factor": signal.name,
        "Pillar": labels.get(signal.pillar, signal.pillar),
        "Status": "Not applicable" if not signal.applicable else "Missing data" if not signal.evaluated else "Active" if signal.strength > 0 else "Evaluated - no warning",
        "Value": signal.value, "Trigger": signal.trigger, "Saturation": signal.saturation,
        "Strength": signal.strength, "Weight": signal.weight, "Points": signal.points,
        "Evidence": "; ".join(signal.evidence),
        "Reason": signal.reason_not_evaluated or ("Does not apply to this customer" if not signal.applicable else "")}
        for signal in signals]
