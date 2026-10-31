import json
import sqlite3
from dataclasses import asdict
from io import BytesIO

import pandas as pd
import pytest
from app.views import monthly_chart, watchlist
from ews import fake_engine as engine
from ews.store.db import Store

@pytest.fixture(scope="module")
def dataset():
    folder = engine.SAMPLE_ROOT / "clean"
    return engine.load_dataset({f"{name}.csv": str(folder / f"{name}.csv") for name in engine.TABLES})


def test_csv_json_excel_equivalence(dataset):
    folder = engine.SAMPLE_ROOT / "clean"
    for filename in ("portfolio.json", "early_warning_data.xlsx"):
        loaded = engine.load_dataset({filename: (folder / filename).read_bytes()})
        assert {k: len(v) for k, v in loaded.tables.items()} == {k: len(v) for k, v in dataset.tables.items()}


def test_fake_results_are_repeatable_and_contract_shaped(dataset):
    results = engine.score_portfolio(dataset)
    assert len(results) == 300
    assert results == engine.score_portfolio(dataset)
    for r in results:
        assert 0 <= r.confidence <= 1
        assert len(r.signals) == 3
        assert r.as_of == "2026-10-31"
        if r.status == "Insufficient data":
            assert r.score is None and r.band is None
            assert all(not s.evaluated for s in r.signals)
        else:
            assert 0 <= r.score <= 100
            assert r.band == ("Low" if r.score < 25 else "Medium" if r.score < 50 else "High" if r.score < 75 else "Critical")
            assert sum(s.points for s in r.signals) == pytest.approx(r.score)
    assert engine.score_portfolio(dataset, "gcc_islamic") != results
    clusters = engine.detect_clusters(dataset, results)
    assert clusters and set(clusters[0].customer_ids) <= {r.customer_id for r in results}


def test_dirty_manifest_explicitly_not_validation():
    folder = engine.SAMPLE_ROOT / "dirty"
    sources = {f"{name}.csv": str(folder / f"{name}.csv") for name in engine.TABLES}
    sources["data_issues_manifest.csv"] = str(folder / "data_issues_manifest.csv")
    ds = engine.load_dataset(sources)
    assert len(ds.issues) == 43
    assert not ds.quarantined
    assert all(i.action == "kept" and "not validated" in i.issue for i in ds.issues)


def test_bad_uploads_and_duplicate_tables(dataset):
    with pytest.raises(ValueError, match="Missing tables"):
        engine.load_dataset({"customers.csv": b"customer_id\nC1\n"})
    folder = engine.SAMPLE_ROOT / "clean"
    with pytest.raises(ValueError, match="twice"):
        engine.load_dataset({"portfolio.json": str(folder / "portfolio.json"), "customers.csv": str(folder / "customers.csv")})


def test_reviews_preserve_scores_across_restarts(tmp_path, dataset):
    path = tmp_path / "evidence.sqlite3"
    store = Store(path)
    results = engine.score_portfolio(dataset)[:2]
    run = store.save_run(results, "india", "Demo")
    alert = store.alert(run, results[0].customer_id)
    original = alert["result_json"]
    store.add_review(alert["alert_id"], "Confirm", "Repeated delay reviewed", "Analyst A")
    store.add_review(alert["alert_id"], "Dismiss", "Payment confirmed", "Analyst B")
    reopened = Store(path)
    assert [r["decision"] for r in reopened.reviews(alert["alert_id"])] == ["Dismiss", "Confirm"]
    assert reopened.alert(run, results[0].customer_id)["result_json"] == original
    assert json.loads(original) == asdict(results[0])
    for table in ("runs", "alerts", "reviews"):
        for statement in (f"DELETE FROM {table}", f"UPDATE {table} SET " + {"runs": "profile='changed'", "alerts": "result_json='{}'", "reviews": "reason='changed'"}[table]):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                with reopened.connect() as db:
                    db.execute(statement)
    with pytest.raises(ValueError):
        store.add_review(alert["alert_id"], "Confirm", " ", "A")
    with pytest.raises(sqlite3.IntegrityError):
        store.add_review(99999, "Monitor", "Reason", "A")
    with pytest.raises(sqlite3.IntegrityError):
        store.save_run([results[0], results[0]], "india", "Demo")
    assert len(store.runs()) == 1  # Failed run was rolled back atomically.


def test_watchlist_and_charts(dataset):
    frame = watchlist(dataset, engine.score_portfolio(dataset))
    assert len(frame) == 300
    assert frame.score.dropna().is_monotonic_decreasing
    assert frame.total_outstanding.notna().all()
    sample = pd.DataFrame({"month": ["2026-01", "2026-03", "2026-03"], "dpd": [2, 3, 10]})
    chart = monthly_chart(sample, "month", ["dpd"], worst=True)
    assert pd.isna(chart.iloc[1].dpd)
    assert chart.iloc[2].dpd == 10
