"""Run with: python -m streamlit run app/main.py"""
from dataclasses import asdict
import importlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st
from app.views import customer_table, monthly_chart, watchlist
from ews import fake_engine
from ews.store.db import DECISIONS, Store

st.set_page_config(page_title="EWS | Analyst workspace", page_icon="\U0001F4CA", layout="wide")


def get_engine(mode):
    if mode == "Demo":
        return fake_engine
    try:
        engine = importlib.import_module("ews.engine")
    except ModuleNotFoundError as exc:
        raise ValueError("Real engine unavailable. Merge Person A's ews/engine package or use Demo.") from exc
    for function in ("load_dataset", "score_portfolio", "detect_clusters"):
        if not callable(getattr(engine, function, None)):
            raise ValueError(f"Real engine must export {function} from ews.engine.")
    return engine


def navigate_customer(cid):
    st.session_state.customer_id = cid
    st.session_state.pending_page = "Customer detail"
    st.session_state.selection_epoch = st.session_state.get("selection_epoch", 0) + 1
    st.rerun()


def show_customers(frame, key):
    if frame.empty:
        st.info("No customers match these filters.")
        return
    event = st.dataframe(frame.drop(columns=["_products"], errors="ignore"), hide_index=True,
        width="stretch", on_select="rerun", selection_mode="single-row", key=f"{key}_{st.session_state.get('selection_epoch', 0)}",
        column_config={"score": st.column_config.NumberColumn("Score", format="%.1f"),
            "total_outstanding": st.column_config.NumberColumn("Total outstanding", format="%.2f")})
    if event.selection.rows:
        navigate_customer(str(frame.iloc[event.selection.rows[0]].customer_id))


def data_page(mode, profile):
    st.title("Data workspace")
    st.write("Load the six source tables, inspect data quality, then score the portfolio.")
    source = st.radio("Source", ["Sample data", "Upload files"], horizontal=True)
    sources = {}
    if source == "Sample data":
        variant = st.selectbox("Sample dataset", ["clean", "dirty"])
        folder = fake_engine.SAMPLE_ROOT / variant
        sources = {f"{name}.csv": str(folder / f"{name}.csv") for name in fake_engine.TABLES}
        if mode == "Demo" and variant == "dirty":
            sources["data_issues_manifest.csv"] = str(folder / "data_issues_manifest.csv")
    else:
        st.caption("CSV names: customers, facilities, repayments, delinquency, exposure, transactions. Alternatively upload one multi-sheet .xlsx or table-keyed .json. Do not mix duplicate representations.")
        uploads = st.file_uploader("CSV, Excel or JSON files", type=["csv", "xlsx", "json"], accept_multiple_files=True)
        sources = {file.name: file.getvalue() for file in uploads}
        if len(sources) != len(uploads):
            st.error("Files must have distinct names.")
            return
    if st.button("Load dataset", type="primary", disabled=not sources):
        try:
            with st.spinner("Loading data..."):
                ds = get_engine(mode).load_dataset(sources)
            st.session_state.dataset = ds
            st.session_state.loaded_mode = mode
            for key in ("results", "clusters", "run_id", "customer_id"):
                st.session_state.pop(key, None)
            st.success("Dataset loaded. Review quality before scoring.")
        except Exception as exc:
            st.error(f"Dataset could not be loaded: {exc}")
    ds = st.session_state.get("dataset")
    if ds is None:
        return
    st.subheader("Data quality")
    st.caption(f"Loaded using {st.session_state.loaded_mode} engine")
    if st.session_state.loaded_mode == "Demo":
        st.warning("Demo loader only reads files. It does not validate or quarantine records. Dirty sample issues come from the supplied manifest; production validation requires the real engine.")
    st.dataframe(pd.DataFrame([{"table": name, "rows": len(frame)} for name, frame in ds.tables.items()]), hide_index=True)
    if ds.issues:
        issues = pd.DataFrame([asdict(issue) for issue in ds.issues])
        st.dataframe(issues, hide_index=True, width="stretch")
        st.download_button("Download quality report", issues.to_csv(index=False), "quality_report.csv", "text/csv")
    else:
        st.info("No issues reported by the selected loader.")
    for table, frame in ds.quarantined.items():
        if not frame.empty:
            with st.expander(f"Quarantined: {table} ({len(frame)} rows)"):
                st.dataframe(frame, hide_index=True)
                st.download_button("Download quarantined rows", frame.to_csv(index=False), f"{table}_quarantined.csv", key=f"quarantine_{table}")
    with st.expander("Preview source tables"):
        table = st.selectbox("Table", list(ds.tables))
        st.dataframe(ds.tables[table].head(100), hide_index=True)
    mismatch = st.session_state.loaded_mode != mode
    if mismatch:
        st.info("Reload the dataset with the selected engine before scoring.")
    if st.button("Score portfolio", type="primary", disabled=mismatch):
        try:
            with st.spinner("Scoring and saving original evidence..."):
                engine = get_engine(mode)
                results = engine.score_portfolio(ds, profile=profile)
                clusters = engine.detect_clusters(ds, results)
                run_id = store.save_run(results, profile, mode)
            st.session_state.update(results=results, clusters=clusters, run_id=run_id,
                scored_profile=profile, scored_mode=mode)
            st.success(f"Saved scoring run with {len(results)} customer alerts. Open Watchlist.")
        except Exception as exc:
            st.error(f"Scoring could not be completed: {exc}")


def require_scores():
    if "results" not in st.session_state:
        st.info("Load and score a dataset on the Data page first.")
        return False
    st.caption(f"Saved run {st.session_state.run_id} | {st.session_state.scored_mode} | {st.session_state.scored_profile}")
    return True


def watchlist_page():
    st.title("Risk watchlist")
    if not require_scores():
        return
    frame = watchlist(st.session_state.dataset, st.session_state.results)
    columns = st.columns(5)
    for box, field, title in zip(columns, ("_products", "segment", "band", "delinquency_bucket", "portfolio"),
            ("Product", "Segment", "Band", "Delinquency bucket", "Portfolio")):
        options = sorted({p for products in frame._products for p in products}) if field == "_products" else sorted(frame[field].dropna().astype(str).unique())
        choices = box.multiselect(title, options, key=f"filter_{field}")
        if choices:
            frame = frame.loc[frame._products.map(lambda items: bool(set(items) & set(choices)))] if field == "_products" else frame.loc[frame[field].isin(choices)]
    st.caption(f"{len(frame)} customers ? highest risk first ? select a row to open evidence")
    st.download_button("Export filtered watchlist", frame.drop(columns="_products").to_csv(index=False), "watchlist.csv", "text/csv")
    show_customers(frame, f"watchlist_{st.session_state.run_id}")


def chart(title, frame):
    st.subheader(title)
    if frame.empty:
        st.info("No usable observations available.")
    else:
        st.line_chart(frame, width="stretch")


def review_panel(alert):
    st.subheader("Analyst review")
    st.caption("Each submission adds a decision. Original scores and evidence remain unchanged. Timestamps are UTC.")
    with st.form(f"review_{alert['alert_id']}", clear_on_submit=True):
        decision = st.selectbox("Decision", DECISIONS)
        analyst = st.text_input("Analyst name (required)")
        reason = st.text_area("Reason (required)")
        submitted = st.form_submit_button("Record review")
    if submitted:
        try:
            store.add_review(alert["alert_id"], decision, reason, analyst)
            st.success("Review appended to history.")
        except (ValueError, OSError) as exc:
            st.error(str(exc))
    history = store.reviews(alert["alert_id"])
    if history:
        st.dataframe(pd.DataFrame(history), hide_index=True, width="stretch")
    else:
        st.info("No reviews recorded for this alert.")


def detail_page():
    st.title("Customer detail")
    if not require_scores():
        return
    results = {r.customer_id: r for r in st.session_state.results}
    if not results:
        st.info("This scoring run has no customers.")
        return
    ids = list(results)
    selected = st.session_state.get("customer_id", ids[0])
    cid = st.selectbox("Customer", ids, index=ids.index(selected) if selected in ids else 0)
    st.session_state.customer_id = cid
    result = results[cid]
    ds = st.session_state.dataset
    customer = customer_table(ds, "customers", cid)
    if not customer.empty:
        st.subheader(str(customer.iloc[0].get("customer_name", cid)))
    a, b, c, d = st.columns(4)
    a.metric("Risk score", "Not scored" if result.score is None else f"{result.score:.1f} / 100")
    b.metric("Band", result.band or result.status)
    c.metric("Confidence", f"{result.confidence:.0%}")
    d.metric("Monitoring", result.monitoring_status)
    st.write(result.summary)
    st.caption(f"As of {result.as_of} | Rules {result.rules_version}")
    st.subheader("Signal contributions and evidence")
    st.dataframe(pd.DataFrame([asdict(s) for s in result.signals]), hide_index=True, width="stretch")
    st.write("Pillar scores", result.pillar_scores)
    st.subheader("Special rules applied")
    for modifier in result.modifiers:
        st.write(modifier)
    if not result.modifiers:
        st.caption("No special rules reported.")
    repayment = customer_table(ds, "repayments", cid)
    chart("Worst monthly repayment DPD", monthly_chart(repayment, "due_date", ["dpd"], worst=True))
    with st.expander("Repayment records"):
        st.dataframe(repayment, hide_index=True, width="stretch")
    chart("Monthly inflows and outflows", monthly_chart(customer_table(ds, "transactions", cid), "month", ["total_inflows", "total_outflows"]))
    chart("Monthly utilisation (%)", monthly_chart(customer_table(ds, "exposure", cid), "month", ["utilisation_pct"], worst=True))
    alert = store.alert(st.session_state.run_id, cid)
    with st.expander("Original saved score and evidence"):
        st.json(json.loads(alert["result_json"]))
        st.download_button("Download original alert", alert["result_json"], f"{cid}_alert.json", "application/json")
    review_panel(alert)


def portfolio_page():
    st.title("Portfolio overview")
    if not require_scores():
        return
    results = st.session_state.results
    counts = pd.Series([r.band or "Insufficient data" for r in results]).value_counts().reindex(["Low", "Medium", "High", "Critical", "Insufficient data"], fill_value=0)
    for col, (band, count) in zip(st.columns(5), counts.items()):
        col.metric(band, int(count))
    st.bar_chart(counts.rename("Customers"))
    st.subheader("Risk clusters")
    clusters = st.session_state.clusters
    if not clusters:
        st.info("No clusters reported.")
        return
    st.dataframe(pd.DataFrame([asdict(c) for c in clusters]).drop(columns="customer_ids"), hide_index=True)
    selected = st.selectbox("Drill into cluster", range(len(clusters)), format_func=lambda i: f"{clusters[i].dimension}: {clusters[i].value}")
    frame = watchlist(st.session_state.dataset, results)
    show_customers(frame.loc[frame.customer_id.isin(clusters[selected].customer_ids)], f"cluster_{st.session_state.run_id}_{selected}")


def history_page():
    st.title("Saved evidence")
    runs = store.runs()
    if not runs:
        st.info("No scoring runs saved yet.")
        return
    selected = st.selectbox("Scoring run", range(len(runs)), format_func=lambda i: f"{runs[i]['created_at']} | {runs[i]['engine']} | {runs[i]['profile']} | {runs[i]['run_id']}")
    alerts = store.alerts(runs[selected]["run_id"])
    if not alerts:
        st.info("This run contains no customer alerts.")
        return
    index = st.selectbox("Saved customer alert", range(len(alerts)), format_func=lambda i: alerts[i]["customer_id"])
    alert = alerts[index]
    st.json(json.loads(alert["result_json"]))
    review_panel(alert)


store = Store(os.environ.get("EWS_DB_PATH", str(ROOT / "data/ews.sqlite3")))
st.sidebar.title("EWS")
st.sidebar.caption("Analyst workspace ? as of 31 Oct 2026")
mode = st.sidebar.selectbox("Engine", ["Demo", "Real"])
region = st.sidebar.selectbox("Region", ["India", "Gulf-Islamic"])
profile = {"India": "india", "Gulf-Islamic": "gcc_islamic"}[region]
if "pending_page" in st.session_state:
    st.session_state.page = st.session_state.pop("pending_page")
page = st.sidebar.radio("Navigation", ["Data", "Watchlist", "Customer detail", "Portfolio", "Saved evidence"], key="page")
if mode == "Demo":
    st.warning("Demo mode: synthetic scores, signals and clusters. Use the real engine for calculated risk results.")
if "results" in st.session_state and (profile != st.session_state.scored_profile or mode != st.session_state.scored_mode):
    st.info("The displayed run uses the engine and region shown below. Return to Data and score again to apply your new selection.")
if page == "Data":
    data_page(mode, profile)
elif page == "Watchlist":
    watchlist_page()
elif page == "Customer detail":
    detail_page()
elif page == "Portfolio":
    portfolio_page()
else:
    history_page()
