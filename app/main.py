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
from app.ui import apply_styles, badge, band_style, empty_state, page_header, topbar
from ews import fake_engine
from ews.store.db import DECISIONS, Store

st.set_page_config(page_title="EWS | Analyst workspace", page_icon="\U0001F4CA", layout="wide")
apply_styles()


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
        empty_state("No matching customers", "Try removing a filter or changing your search.")
        return
    display = frame.drop(columns=["_products"], errors="ignore")
    event = st.dataframe(display.style.map(band_style, subset=["band"]), hide_index=True,
        width="stretch", on_select="rerun", selection_mode="single-row",
        column_order=["customer_id", "customer_name", "main_product", "total_outstanding", "score", "band", "monitoring_status", "top_3_factors"], key=f"{key}_{st.session_state.get('selection_epoch', 0)}",
        column_config={"customer_id": st.column_config.TextColumn("Customer ID"),
            "customer_name": st.column_config.TextColumn("Customer name"),
            "main_product": st.column_config.TextColumn("Main product"),
            "score": st.column_config.ProgressColumn("Risk score", min_value=0, max_value=100, format="%.1f"),
            "band": st.column_config.TextColumn("Risk band"),
            "top_3_factors": st.column_config.TextColumn("Leading risk factors", width="large"),
            "monitoring_status": st.column_config.TextColumn("Monitoring"),
            "delinquency_bucket": st.column_config.TextColumn("Delinquency"),
            "total_outstanding": st.column_config.NumberColumn("Total outstanding", format="%.2f")})
    if event.selection.rows:
        navigate_customer(str(frame.iloc[event.selection.rows[0]].customer_id))


def data_page(mode, profile):
    page_header("Data workspace", "Bring your portfolio into view. Load source data, inspect quality, and start a scoring run.", "01 / Prepare")
    one, two, three = st.columns(3)
    for box, title, description in ((one, "1. Connect", "Choose sample data or upload files"),
            (two, "2. Inspect", "Check issues and quarantined records"),
            (three, "3. Score", "Create a saved portfolio assessment")):
        with box.container(border=True):
            st.markdown(f"**{title}**")
            st.caption(description)
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
        empty_state("Your workspace is ready", "Choose a source above and select Load dataset to begin.")
        return
    st.divider()
    st.subheader("Data quality")
    one, two, three = st.columns(3)
    one.metric("Source tables", len(ds.tables))
    two.metric("Reported issues", len(ds.issues))
    three.metric("Quarantined records", sum(len(frame) for frame in ds.quarantined.values()))
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
        empty_state("No portfolio assessment yet", "Open Data in the sidebar, load a dataset, and select Score portfolio. Your customers will appear here.")
        return False
    st.caption(f"Assessment {st.session_state.run_id[:8]} | {st.session_state.scored_mode} | {st.session_state.scored_profile}")
    return True


def watchlist_page():
    page_header("Risk watchlist", "Prioritise customers who need attention, then open their evidence with one click.", "02 / Monitor")
    if not require_scores():
        return
    frame = watchlist(st.session_state.dataset, st.session_state.results)
    total, elevated, insufficient, outstanding = st.columns(4)
    total.metric("Customers", f"{len(frame):,}")
    elevated.metric("High & critical", int(frame.band.isin(["High", "Critical"]).sum()))
    insufficient.metric("Insufficient data", int((frame.band == "Insufficient data").sum()))
    outstanding.metric("Total outstanding", f"{frame.total_outstanding.sum():,.0f}")
    st.subheader("Customer queue")
    search = st.text_input("Search customers", placeholder="Search by customer name or ID")
    if search.strip():
        frame = frame.loc[frame.customer_id.str.contains(search.strip(), case=False, regex=False) |
            frame.customer_name.astype(str).str.contains(search.strip(), case=False, regex=False)]
    columns = st.columns(5)
    for box, field, title in zip(columns, ("_products", "segment", "band", "delinquency_bucket", "portfolio"),
            ("Product", "Segment", "Band", "Delinquency bucket", "Portfolio")):
        options = sorted({p for products in frame._products for p in products}) if field == "_products" else sorted(frame[field].dropna().astype(str).unique())
        choices = box.multiselect(title, options, key=f"filter_{field}")
        if choices:
            frame = frame.loc[frame._products.map(lambda items: bool(set(items) & set(choices)))] if field == "_products" else frame.loc[frame[field].isin(choices)]
    st.caption(f"{len(frame)} customers | Highest risk first | Select a row to open customer detail")
    st.download_button("Export filtered watchlist", frame.drop(columns="_products").to_csv(index=False), "watchlist.csv", "text/csv")
    show_customers(frame, f"watchlist_{st.session_state.run_id}")


def chart(title, frame):
    st.subheader(title)
    if frame.empty:
        st.info("No usable observations available.")
    else:
        st.line_chart(frame, width="stretch", height=260, color=["#2563eb", "#dc7b3c"][:len(frame.columns)])


def review_panel(alert):
    st.subheader("Analyst review")
    st.caption("Each submission adds a decision. Original scores and evidence remain unchanged. Timestamps are UTC.")
    with st.form(f"review_{alert['alert_id']}", clear_on_submit=True):
        decision_column, analyst_column = st.columns(2)
        decision = decision_column.selectbox("Decision", DECISIONS)
        analyst = analyst_column.text_input("Analyst name (required)")
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
        st.markdown("**Decision history**")
        st.dataframe(pd.DataFrame(history)[["decision", "reason", "analyst", "created_at"]].rename(columns={
            "decision": "Decision", "reason": "Reason", "analyst": "Analyst", "created_at": "Recorded at (UTC)"}),
            hide_index=True, width="stretch")
    else:
        st.info("No reviews recorded for this alert.")


def detail_page():
    page_header("Customer detail", "Understand the assessment, explore account activity, and record your decision.", "03 / Investigate")
    if not require_scores():
        return
    if st.button("Back to watchlist"):
        st.session_state.pending_page = "Watchlist"
        st.rerun()
    results = {r.customer_id: r for r in st.session_state.results}
    if not results:
        empty_state("No customers in this run", "Load another dataset to start a new assessment.")
        return
    ds = st.session_state.dataset
    ids = list(results)
    names = {}
    customers = ds.tables.get("customers", pd.DataFrame())
    if {"customer_id", "customer_name"}.issubset(customers.columns):
        names = dict(zip(customers.customer_id.astype(str), customers.customer_name))
    selected = st.session_state.get("customer_id", ids[0])
    cid = st.selectbox("Customer", ids, index=ids.index(selected) if selected in ids else 0,
        format_func=lambda value: f"{value} | {names.get(value, value)}")
    st.session_state.customer_id = cid
    result = results[cid]
    customer = customer_table(ds, "customers", cid)
    with st.container(border=True):
        identity, risk = st.columns([4, 1])
        with identity:
            st.subheader(str(names.get(cid, cid)))
            if not customer.empty:
                info = customer.iloc[0]
                st.caption(" | ".join(str(info.get(field, "Unknown")) for field in ("segment", "industry", "region")))
        with risk:
            badge(result.band or "Insufficient data")
        st.write(result.summary)
        st.caption(f"Assessment date: {result.as_of} | Rules: {result.rules_version}")
    a, b, c, d = st.columns(4)
    a.metric("Risk score", "Not scored" if result.score is None else f"{result.score:.1f} / 100")
    b.metric("Band", result.band or result.status)
    c.metric("Confidence", f"{result.confidence:.0%}")
    d.metric("Monitoring", result.monitoring_status)
    evidence, activity, review = st.tabs(["Risk evidence", "Account activity", "Analyst review"])
    with evidence:
        st.subheader("What is driving this assessment?")
        evaluated = sorted((signal for signal in result.signals if signal.evaluated), key=lambda signal: signal.points, reverse=True)
        if evaluated:
            contributions = pd.DataFrame({"Signal": [signal.name for signal in evaluated], "Points": [signal.points for signal in evaluated]})
            st.bar_chart(contributions.set_index("Signal"), color="#2563eb", height=220)
        else:
            st.info("No signals could be evaluated. Review the reasons below before taking action.")
        st.subheader("Signal contributions and evidence")
        rows = [{"Signal": signal.signal_id, "Factor": signal.name, "Pillar": signal.pillar,
            "Evaluated": signal.evaluated, "Value": signal.value, "Trigger": signal.trigger,
            "Saturation": signal.saturation, "Strength": signal.strength, "Weight": signal.weight,
            "Points": signal.points, "Evidence": "; ".join(signal.evidence),
            "Not evaluated because": signal.reason_not_evaluated} for signal in result.signals]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
            column_config={"Strength": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f"),
                "Points": st.column_config.NumberColumn(format="%.2f"),
                "Evidence": st.column_config.TextColumn(width="large")})
        pillars, rules = st.columns(2)
        with pillars.container(border=True):
            st.markdown("**Pillar scores**")
            labels = {"RB": "Repayment behaviour", "CF": "Cash flow", "EX": "Exposure"}
            for key, value in result.pillar_scores.items():
                st.write(f"{labels.get(key, key)}: **{value:.1f}**")
        with rules.container(border=True):
            st.markdown("**Special rules applied**")
            for modifier in result.modifiers:
                st.write(modifier)
            if not result.modifiers:
                st.caption("No special rules reported.")
        alert = store.alert(st.session_state.run_id, cid)
        with st.expander("Original saved score and evidence"):
            st.caption("This is the immutable assessment captured when the portfolio was scored.")
            st.json(json.loads(alert["result_json"]))
            st.download_button("Download original alert", alert["result_json"], f"{cid}_alert.json", "application/json")
    with activity:
        st.caption("Monthly observations from the loaded dataset. Missing months remain gaps.")
        repayment = customer_table(ds, "repayments", cid)
        left, right = st.columns(2)
        with left:
            chart("Repayment DPD", monthly_chart(repayment, "due_date", ["dpd"], worst=True))
            st.caption("Worst DPD across facilities in each due month")
        with right:
            chart("Utilisation (%)", monthly_chart(customer_table(ds, "exposure", cid), "month", ["utilisation_pct"], worst=True))
        chart("Monthly inflows and outflows", monthly_chart(customer_table(ds, "transactions", cid), "month", ["total_inflows", "total_outflows"]))
        with st.expander("Repayment records"):
            st.dataframe(repayment, hide_index=True, width="stretch")
    with review:
        with st.container(border=True):
            review_panel(alert)


def portfolio_page():
    page_header("Portfolio overview", "Track risk across your book and explore concentrations that deserve a closer look.", "04 / Overview")
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
    page_header("Saved evidence", "Revisit original assessments and the complete analyst decision trail.", "05 / Audit")
    runs = store.runs()
    if not runs:
        empty_state("No saved assessments yet", "Each scoring run is saved automatically. Score a portfolio on the Data page to create your first assessment.")
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
st.sidebar.markdown('<div class="ews-brand">EWS<span>.</span></div>', unsafe_allow_html=True)
st.sidebar.caption("EARLY WARNING SYSTEM")
st.sidebar.divider()
mode = st.sidebar.selectbox("Engine", ["Demo", "Real"])
region = st.sidebar.selectbox("Region", ["India", "Gulf-Islamic"])
profile = {"India": "india", "Gulf-Islamic": "gcc_islamic"}[region]
if "pending_page" in st.session_state:
    st.session_state.page = st.session_state.pop("pending_page")
page = st.sidebar.radio("Navigation", ["Data", "Watchlist", "Customer detail", "Portfolio", "Saved evidence"], key="page")
st.sidebar.divider()
st.sidebar.caption("AS OF 31 OCT 2026")
st.sidebar.caption("Review risk. Preserve evidence. Act early.")
topbar(region, mode)
if mode == "Demo":
    st.info("Demo workspace: scores, signals and clusters are synthetic placeholders.", icon="\u2139")
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
