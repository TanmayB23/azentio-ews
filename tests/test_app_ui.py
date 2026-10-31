"""Run the actual Streamlit pages against the generated real-engine portfolios."""
from dataclasses import asdict
import json
from pathlib import Path

from streamlit.testing.v1 import AppTest
from ews.store.db import Store

MAIN = str(Path(__file__).resolve().parents[1] / "app/main.py")


def button(app, label):
    return next(widget for widget in app.button if widget.label == label)


def select(app, label):
    return next(widget for widget in app.selectbox if widget.label == label)


def go(app, page):
    app.sidebar.radio[0].set_value(page).run()
    assert not app.exception


def test_real_analyst_flow(tmp_path, monkeypatch):
    path = tmp_path / "ui.sqlite3"
    monkeypatch.setenv("EWS_DB_PATH", str(path))
    app = AppTest.from_file(MAIN, default_timeout=120).run()
    assert not app.exception
    assert app.session_state.profile == "india"
    button(app, "Load dataset").click().run()
    assert not app.exception
    assert len(app.session_state.dataset.tables["customers"]) == 500
    button(app, "Score portfolio").click().run()
    assert not app.exception
    run_id = app.session_state.run_id
    results = app.session_state.results
    assert len(results) == 500
    assert all(not r.rules_version.startswith("demo") for r in results)
    roll = next(r for r in results if any("Roll-forward" in m for m in r.modifiers))
    assert roll.band == "Critical"
    thin = next(r for r in results if r.status == "Insufficient data")
    assert thin.score is None and thin.band is None and thin.monitoring_status == "Collect data"
    store = Store(path)
    alert = store.alert(run_id, roll.customer_id)
    original = alert["result_json"]
    go(app, "Watchlist")
    assert len(app.dataframe[0].value) == 500
    next(m for m in app.multiselect if m.label == "Band").set_value(["Insufficient data"]).run()
    assert set(app.dataframe[0].value.monitoring_status) == {"Collect data"}
    assert app.dataframe[0].value.score.isna().all()
    next(m for m in app.multiselect if m.label == "Band").set_value(["Critical"]).run()
    next(t for t in app.text_input if t.label == "Search customers").set_value(roll.customer_id).run()
    assert len(app.dataframe[0].value) == 1
    app.session_state[app.dataframe[0].key] = {"selection": {"rows": [0], "columns": [], "cells": []}}
    app.run()
    assert not app.exception
    assert app.session_state.page == "Customer detail"
    assert app.session_state.customer_id == roll.customer_id
    assert any("Signal contribution total" in caption.value for caption in app.caption)
    assert set(app.dataframe[0].value.Status) <= {"Active", "Evaluated - no warning", "Missing data", "Not applicable"}
    app.text_input[0].set_value("Hackathon analyst")
    app.text_area[0].set_value("Reviewed roll-forward evidence")
    button(app, "Record review").click().run()
    assert not app.exception
    select(app, "Decision").set_value("Dismiss")
    app.text_input[0].set_value("Hackathon analyst")
    app.text_area[0].set_value("Updated after follow-up")
    button(app, "Record review").click().run()
    assert not app.exception
    assert [r["decision"] for r in store.reviews(alert["alert_id"])] == ["Dismiss", "Confirm"]
    assert store.alert(run_id, roll.customer_id)["result_json"] == original
    assert json.loads(original) == asdict(roll)
    # Thin history is explained rather than assigned a risk band.
    select(app, "Customer").set_value(thin.customer_id).run()
    assert not app.exception
    assert any(m.value == "Not scored" for m in app.metric)
    assert any(thin.summary in m.value for m in app.markdown)
    # SME-only tab includes tax filing status and receivable/payable days.
    customers = app.session_state.dataset.tables["customers"]
    sme_id = customers.loc[customers.customer_type == "SME", "customer_id"].iloc[0]
    select(app, "Customer").set_value(sme_id).run()
    assert not app.exception
    assert "SME indicators" in [tab.label for tab in app.tabs]
    assert any("tax_filing_status" in frame.value.columns for frame in app.dataframe)
    go(app, "Portfolio")
    assert len(app.metric) == 5
    clusters = app.dataframe[0].value
    assert {"Textiles|Tamil Nadu", "Gig Economy|Karnataka", "Logistics & Transport"} <= set(clusters.value)
    assert {"basis", "p_value", "lift"} <= set(clusters.columns)
    # Cluster rows open the same detail screen.
    chosen = app.dataframe[1].value.iloc[0].customer_id
    app.session_state[app.dataframe[1].key] = {"selection": {"rows": [0], "columns": [], "cells": []}}
    app.run()
    assert not app.exception and app.session_state.customer_id == chosen
    go(app, "Data")
    cache_size = len(app.session_state.assessment_cache)
    button(app, "Score portfolio").click().run()
    assert not app.exception
    assert app.session_state.run_id != run_id
    assert len(app.session_state.assessment_cache) == cache_size
    assert store.alert(run_id, roll.customer_id)["result_json"] == original
    # Choosing Gulf samples defaults to the corresponding engine profile.
    select(app, "Sample portfolio").set_value("gcc_islamic").run()
    assert app.session_state.profile == "gcc_islamic"
    button(app, "Load dataset").click().run()
    assert len(app.session_state.dataset.tables["customers"]) == 400
    button(app, "Score portfolio").click().run()
    assert not app.exception
    assert app.session_state.scored_profile == "gcc_islamic"
    assert all("gcc_islamic" in r.rules_version for r in app.session_state.results)
    go(app, "Watchlist")
    assert not app.exception
    go(app, "Customer detail")
    assert not app.exception
    go(app, "Portfolio")
    assert "Construction & Contracting|Dubai" in set(app.dataframe[0].value.value)
    go(app, "Saved evidence")
    assert not app.exception
    assert len(store.runs()) == 3


def test_dirty_validation_ui(tmp_path, monkeypatch):
    monkeypatch.setenv("EWS_DB_PATH", str(tmp_path / "dirty.sqlite3"))
    app = AppTest.from_file(MAIN, default_timeout=120).run()
    select(app, "Sample dataset").set_value("dirty").run()
    button(app, "Load dataset").click().run()
    assert not app.exception
    ds = app.session_state.dataset
    assert {i.action for i in ds.issues} == {"kept", "repaired", "quarantined"}
    assert any(not frame.empty and "issue" in frame for frame in ds.quarantined.values())
    assert any("Action counts" in m.value for m in app.markdown)
    assert any("Repaired:" in m.value for m in app.markdown)
    assert any(expander.label.startswith("Quarantined:") for expander in app.expander)


def test_missing_required_tables_render_issues(tmp_path, monkeypatch):
    from ews.engine import load_dataset
    monkeypatch.setenv("EWS_DB_PATH", str(tmp_path / "missing.sqlite3"))
    app = AppTest.from_file(MAIN, default_timeout=60).run()
    app.session_state.dataset = load_dataset({"customers.csv": b"customer_id\nC1\n"})
    app.session_state.dataset_hash = "missing"
    app.session_state.source_label = "Incomplete upload"
    app.run()
    assert not app.exception
    assert any("Required tables or columns are missing" in e.value for e in app.error)
    assert button(app, "Score portfolio").disabled
    assert any("issue" in frame.value.columns for frame in app.dataframe)
