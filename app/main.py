"""Run with: python -m streamlit run app/main.py"""
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st
from app.views import customer_table, monthly_chart, signal_rows, watchlist
from app.ui import apply_styles, badge, band_style, empty_state, page_header, topbar
from ews import engine
from app.service import assess, sample_sources, source_bytes, source_hash
from ews.store.db import DECISIONS, Store

st.set_page_config(page_title="EWS | Analyst workspace", page_icon="\U0001F4CA", layout="wide")
apply_styles()


def sync_sample_profile():
    st.session_state.profile = st.session_state.sample_profile


def navigate_customer(cid):
    st.session_state.customer_id = cid
    st.session_state[f"detail_customer_{st.session_state.run_id}"] = cid
    st.session_state.pending_page = "Customer detail"
    st.session_state.selection_epoch = st.session_state.get("selection_epoch", 0) + 1
    st.rerun()


def show_customers(frame, key):
    if frame.empty:
        empty_state("No matching customers", "Try removing a filter or changing your search.")
        return
    st.caption("Tick the checkbox at the left of a row to open that customer's detail screen.")
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


def data_page(profile):
    page_header("Data workspace", "Load a portfolio, inspect validation results, and create an evidence-backed assessment.", "01 / Prepare")
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
        sample_profile = st.selectbox("Sample portfolio", profiles, index=profiles.index(profile),
            format_func=profile_label, key="sample_profile", on_change=sync_sample_profile)
        variant = st.selectbox("Sample dataset", ["clean", "dirty"])
        sources = sample_sources(sample_profile, variant)
        source_label = f"{profile_label(sample_profile)} / {variant}"
        if profile != sample_profile:
            st.info("The region differs from this sample portfolio. Select its matching region, or score explicitly under the selected profile.")
    else:
        st.caption("Upload named CSV tables, a multi-sheet Excel workbook, or table-keyed JSON. sme_indicators is optional. Include risk_signal_definitions.csv or .json to override signal thresholds and weights.")
        uploads = st.file_uploader("CSV, Excel or JSON files", type=["csv", "xlsx", "xlsm", "json"], accept_multiple_files=True)
        if any(Path(file.name).stem.lower() == "ground_truth" for file in uploads):
            st.error("ground_truth is a test answer key. Remove it from your upload; it is never loaded by this app.")
            return
        sources = {file.name: file.getvalue() for file in uploads}
        source_label = "Uploaded portfolio"
        if len(sources) != len(uploads):
            st.error("Files must have distinct names.")
            return
    if st.button("Load dataset", type="primary", disabled=not sources):
        try:
            with st.spinner("Loading and validating data..."):
                raw = source_bytes(sources)
                ds = engine.load_dataset(raw)
            st.session_state.update(dataset=ds, dataset_hash=source_hash(raw), source_label=source_label)
            for key in ("results", "clusters", "run_id", "customer_id"):
                st.session_state.pop(key, None)
            st.session_state.selection_epoch = st.session_state.get("selection_epoch", 0) + 1
            st.success("Dataset loaded. Review validation results before scoring.")
        except (ValueError, OSError) as exc:
            st.error(f"Dataset could not be loaded: {exc}")
    ds = st.session_state.get("dataset")
    if ds is None:
        empty_state("Your workspace is ready", "Choose a source above and select Load dataset to begin.")
        return
    st.divider()
    st.subheader("Data quality")
    st.caption(f"Loaded portfolio: {st.session_state.source_label}")
    one, two, three = st.columns(3)
    one.metric("Source tables", sum(not frame.empty for frame in ds.tables.values()))
    two.metric("Reported issues", len(ds.issues))
    three.metric("Quarantined records", sum(len(frame) for frame in ds.quarantined.values()))
    st.dataframe(pd.DataFrame([{"table": name, "rows": len(frame)} for name, frame in ds.tables.items()]), hide_index=True)
    if ds.issues:
        issues = pd.DataFrame([asdict(issue) for issue in ds.issues])
        severity, actions = st.columns(2)
        with severity.container(border=True):
            st.markdown("**Severity counts**")
            st.write(" | ".join(f"{label.title()}: {int((issues.severity == label).sum())}" for label in ("error", "warning")))
        with actions.container(border=True):
            st.markdown("**Action counts**")
            st.write(" | ".join(f"{label.title()}: {int((issues.action == label).sum())}" for label in ("repaired", "quarantined", "kept")))
        colors = {"repaired": "background-color: #e8f5ee; color: #17633c", "quarantined": "background-color: #fdebed; color: #ac2538", "kept": "background-color: #fff5d6; color: #855c00"}
        st.dataframe(issues.style.map(lambda value: colors.get(value, ""), subset=["action"]), hide_index=True, width="stretch")
        st.download_button("Download quality report", issues.to_csv(index=False), "quality_report.csv", "text/csv")
    else:
        st.success("No validation issues reported.")
    for table, frame in ds.quarantined.items():
        if not frame.empty:
            with st.expander(f"Quarantined: {table} ({len(frame)} rows)"):
                st.dataframe(frame, hide_index=True)
                st.download_button("Download quarantined rows", frame.to_csv(index=False), f"{table}_quarantined.csv", key=f"quarantine_{table}")
    with st.expander("Preview source tables"):
        table = st.selectbox("Table", list(ds.tables))
        st.dataframe(ds.tables[table].head(100), hide_index=True)
    if ds.signal_config:
        st.info("This dataset supplies signal definitions. Its thresholds and weights will be used for scoring.")
    structural_errors = any(issue.severity == "error" and issue.record_key == "*" for issue in ds.issues)
    if structural_errors:
        st.error("Required tables or columns are missing. Correct the errors above and reload before scoring.")
    st.caption(f"Scoring profile: {profile_label(profile)}. Each click saves a new immutable assessment. Previously computed results are reused for identical source contents and profile.")
    if st.button("Score portfolio", type="primary", disabled=structural_errors):
        try:
            with st.spinner("Scoring portfolio and saving original evidence. This may take 10-20 seconds..."):
                cache = st.session_state.setdefault("assessment_cache", {})
                results, clusters = assess(ds, st.session_state.dataset_hash, profile, cache)
                run_id = store.save_run(results, profile, "Real")
            st.session_state.update(results=results, clusters=clusters, run_id=run_id,
                scored_profile=profile, scored_mode="Real")
            st.success(f"Saved scoring run with {len(results)} customer alerts. Open Watchlist.")
        except Exception as exc:
            st.error(f"Scoring could not be completed: {exc}")


def require_scores():
    if "results" not in st.session_state:
        empty_state("No portfolio assessment yet", "Open Data in the sidebar, load a dataset, and select Score portfolio. Your customers will appear here.")
        return False
    st.caption(f"Assessment {st.session_state.run_id[:8]} | {st.session_state.scored_mode} | {st.session_state.scored_profile}")
    return True


def portfolio_frame():
    """Reuse the presentation table while filters/navigation rerun the script."""
    run_id = st.session_state.run_id
    cached = st.session_state.get("watchlist_cache")
    if cached is None or cached[0] != run_id:
        cached = (run_id, watchlist(st.session_state.dataset, st.session_state.results))
        st.session_state.watchlist_cache = cached
    return cached[1]


def watchlist_page():
    page_header("Risk watchlist", "Prioritise customers who need attention, then open their evidence with one click.", "02 / Monitor")
    if not require_scores():
        return
    frame = portfolio_frame()
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
    st.caption(f"{len(frame)} {'customer' if len(frame) == 1 else 'customers'} | Highest risk first")
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
    detail_key = f"detail_customer_{st.session_state.run_id}"
    if detail_key not in st.session_state:
        st.session_state[detail_key] = selected if selected in ids else ids[0]
    cid = st.selectbox("Customer", ids, key=detail_key,
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
    is_sme = not customer.empty and str(customer.iloc[0].get("customer_type", "")) == "SME"
    tab_labels = ["Risk evidence", "Account activity"] + (["SME indicators"] if is_sme else []) + ["Analyst review"]
    tabs = st.tabs(tab_labels)
    evidence, activity, review = tabs[0], tabs[1], tabs[-1]
    with evidence:
        st.subheader("What is driving this assessment?")
        evaluated = sorted((signal for signal in result.signals if signal.applicable and signal.evaluated), key=lambda signal: signal.points, reverse=True)
        if evaluated:
            contributions = pd.DataFrame({"Signal": [signal.name for signal in evaluated], "Points": [signal.points for signal in evaluated]})
            st.bar_chart(contributions.set_index("Signal"), color="#2563eb", height=220)
        else:
            st.info("No signals could be evaluated. Review the reasons below before taking action.")
        st.subheader("Signal contributions and evidence")
        rows = signal_rows(result.signals)
        total_points = sum(signal.points for signal in result.signals)
        st.caption(f"Signal contribution total before score cap and minimum-score rules: {total_points:.2f}. Final score: {'Not scored' if result.score is None else f'{result.score:.1f}'}. Rules and dampeners are listed below.")
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
            column_config={"Strength": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f"),
                "Points": st.column_config.NumberColumn(format="%.2f"),
                "Evidence": st.column_config.TextColumn(width="large")})
        pillars, rules = st.columns(2)
        with pillars.container(border=True):
            st.markdown("**Pillar scores**")
            labels = {"RB": "Repayment", "CF": "Cash flow", "EX": "Exposure", "SM": "Business"}
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
    if is_sme:
        with tabs[2]:
            st.subheader("SME business indicators")
            sme = customer_table(ds, "sme_indicators", cid)
            if sme.empty:
                st.info("No SME indicator observations were supplied. Business signals may be not applicable or missing data; see Risk evidence.")
            else:
                chart("Receivable and payable days", monthly_chart(sme, "month", ["receivable_days", "payable_days"], worst=True))
                st.dataframe(sme.sort_values("month"), hide_index=True, width="stretch")
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
    st.dataframe(pd.DataFrame([asdict(c) for c in clusters]).drop(columns="customer_ids"), hide_index=True,
        column_config={"p_value": st.column_config.NumberColumn("p-value", format="%.3e"),
            "basis": st.column_config.TextColumn("Basis", width="large"),
            "lift": st.column_config.NumberColumn("Lift", format="%.2f")})
    selected = st.selectbox("Drill into cluster", range(len(clusters)), format_func=lambda i: f"{clusters[i].dimension}: {clusters[i].value}")
    frame = portfolio_frame()
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
profiles = engine.available_profiles()

def profile_label(name):
    return {"india": "India", "gcc_islamic": "Gulf-Islamic"}.get(name, name.replace("_", " ").title())

profile = st.sidebar.selectbox("Region", profiles, index=profiles.index("india") if "india" in profiles else 0,
    format_func=profile_label, key="profile")
region = profile_label(profile)
if "pending_page" in st.session_state:
    st.session_state.page = st.session_state.pop("pending_page")
page = st.sidebar.radio("Navigation", ["Data", "Watchlist", "Customer detail", "Portfolio", "Saved evidence"], key="page")
st.sidebar.divider()
st.sidebar.caption("AS OF 31 OCT 2026")
st.sidebar.caption("Review risk. Preserve evidence. Act early.")
topbar(region, "Real engine")
if "results" in st.session_state and profile != st.session_state.scored_profile:
    st.info("The displayed run uses the engine and region shown below. Return to Data and score again to apply your new selection.")
if page == "Data":
    data_page(profile)
elif page == "Watchlist":
    watchlist_page()
elif page == "Customer detail":
    detail_page()
elif page == "Portfolio":
    portfolio_page()
else:
    history_page()
