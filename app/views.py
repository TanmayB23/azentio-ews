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
                    grouped = facilities.assign(_amount=totals).groupby("product_type")._amount.sum(min_count=1)
                    product = str(grouped.idxmax()) if grouped.notna().any() else (products[0] if products else "Unknown")
                else:
                    product = products[0] if products else "Unknown"
            if "outstanding_balance" in facilities:
                outstanding = pd.to_numeric(facilities.outstanding_balance, errors="coerce").sum(min_count=1)
        if not exposure.empty and {"month", "total_outstanding"}.issubset(exposure.columns):
            dated = exposure.assign(_month=pd.to_datetime(exposure.month, format="%Y-%m", errors="coerce"))
            dated = dated.loc[dated._month <= pd.Timestamp(result.as_of)].sort_values("_month")
            if not dated.empty:
                outstanding = pd.to_numeric(pd.Series([dated.iloc[-1].total_outstanding]), errors="coerce").iloc[0]
        dpd = pd.to_numeric(delinquency.get("current_dpd", pd.Series(dtype=float)), errors="coerce").max()
        bucket = "Unknown" if pd.isna(dpd) else "Current" if dpd <= 0 else "1-30" if dpd <= 30 else "31-60" if dpd <= 60 else "61-90" if dpd <= 90 else "90+"
        top = sorted((s for s in result.signals if s.evaluated), key=lambda s: s.points, reverse=True)[:3]
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
