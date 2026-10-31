"""Exercise analyst flows through Streamlit's own test runner."""
from pathlib import Path
import json
from streamlit.testing.v1 import AppTest

MAIN = str(Path(__file__).resolve().parents[1] / "app/main.py")


def button(app, label):
    return next(b for b in app.button if b.label == label)


def test_analyst_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("EWS_DB_PATH", str(tmp_path / "ui.sqlite3"))
    app = AppTest.from_file(MAIN, default_timeout=30).run()
    assert not app.exception
    button(app, "Load dataset").click().run()
    assert not app.exception
    button(app, "Score portfolio").click().run()
    assert not app.exception
    run_id = app.session_state.run_id
    app.sidebar.radio[0].set_value("Watchlist").run()
    assert not app.exception
    assert len(app.dataframe[0].value) == 300
    next(m for m in app.multiselect if m.label == "Band").set_value(["High"]).run()
    assert set(app.dataframe[0].value.band) == {"High"}
    chosen_customer = app.dataframe[0].value.iloc[0].customer_id
    app.session_state[app.dataframe[0].key] = {"selection": {"rows": [0], "columns": [], "cells": []}}
    app.run()
    assert not app.exception
    assert app.session_state.page == "Customer detail"
    assert app.session_state.customer_id == chosen_customer
    app.text_input[0].set_value("Hackathon analyst")
    app.text_area[0].set_value("Reviewed payment evidence")
    button(app, "Record review").click().run()
    assert not app.exception
    assert any("Review appended" in s.value for s in app.success)
    next(s for s in app.selectbox if s.label == "Decision").set_value("Dismiss")
    app.text_input[0].set_value("Hackathon analyst")
    app.text_area[0].set_value("Updated decision after follow-up")
    button(app, "Record review").click().run()
    assert not app.exception
    assert len(app.dataframe[-1].value) == 2
    app.sidebar.radio[0].set_value("Portfolio").run()
    assert not app.exception
    assert len(app.metric) == 5
    app.sidebar.selectbox[1].set_value("Gulf-Islamic").run()
    assert app.session_state.run_id == run_id  # Navigation does not silently rescore.
    app.sidebar.radio[0].set_value("Data").run()
    button(app, "Score portfolio").click().run()
    assert not app.exception
    assert app.session_state.scored_profile == "gcc_islamic"
    assert app.session_state.run_id != run_id
    app.sidebar.radio[0].set_value("Saved evidence").run()
    assert not app.exception


def test_dirty_and_missing_real_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("EWS_DB_PATH", str(tmp_path / "dirty.sqlite3"))
    app = AppTest.from_file(MAIN, default_timeout=30).run()
    next(s for s in app.selectbox if s.label == "Sample dataset").set_value("dirty").run()
    button(app, "Load dataset").click().run()
    assert not app.exception
    assert len(app.session_state.dataset.issues) == 43
    button(app, "Score portfolio").click().run()
    assert not app.exception
    app.sidebar.selectbox[0].set_value("Real").run()
    button(app, "Load dataset").click().run()
    assert not app.exception
    assert any("Real engine unavailable" in e.value for e in app.error)
