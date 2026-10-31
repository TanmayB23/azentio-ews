"""Adapter-specific integration checks, without changing the engine's tests."""
from copy import deepcopy
from dataclasses import replace
import json

import pandas as pd
import pytest

from app.service import assess, sample_sources, source_bytes, source_hash
from app.views import monthly_chart, signal_rows, watchlist
from ews import engine
from ews.contracts import Dataset
from ews.store.db import Store


def test_sample_sources_never_include_ground_truth():
    for profile in engine.available_profiles():
        sources = sample_sources(profile, "clean")
        assert "sme_indicators.csv" in sources
        assert all("ground_truth" not in name for name in sources)
        assert source_bytes({"ground_truth.csv": "does-not-exist", "customers.csv": b"x"}) == {"customers.csv": b"x"}


def test_watchlist_uses_largest_facility_and_current_bucket(clean_ds, clean_results):
    cid = next(iter(clean_results))
    facilities = pd.DataFrame({"customer_id": [cid]*3, "product_type": ["A", "A", "B"], "outstanding_balance": [60, 60, 100]})
    delinquency = pd.DataFrame({"customer_id": [cid, cid], "current_dpd": [0, 40], "delinquency_bucket": ["Current", "31-60 DPD"], "dpd_bucket_3m_ago": ["90+", "90+"]})
    ds = replace(clean_ds, tables={**clean_ds.tables, "facilities": facilities, "delinquency": delinquency})
    row = watchlist(ds, [clean_results[cid]]).iloc[0]
    assert row.main_product == "B"  # Individual facility, not aggregate by product.
    assert row.delinquency_bucket == "31-60 DPD"
    frame = watchlist(clean_ds, list(clean_results.values()))
    assert frame.score.dropna().is_monotonic_decreasing
    insufficient = frame.loc[frame.band == "Insufficient data"]
    assert not insufficient.empty and insufficient.score.isna().all()
    assert set(insufficient.monitoring_status) == {"Collect data"}
    assert frame.iloc[-len(insufficient):].score.isna().all()


def test_all_signal_states_and_named_pillars(clean_ds, clean_results):
    rows = [row for result in clean_results.values() for row in signal_rows(result.signals)]
    assert {"Active", "Evaluated - no warning", "Missing data", "Not applicable"} <= {r["Status"] for r in rows}
    assert {"Repayment", "Cash flow", "Exposure", "Business"} == {r["Pillar"] for r in rows}
    assert all(r["Reason"] for r in rows if r["Status"] in ("Missing data", "Not applicable"))
    for table, date, values in (("repayments", "due_date", ["dpd"]), ("transactions", "month", ["total_inflows", "total_outflows"]), ("exposure", "month", ["utilisation_pct"])):
        assert not monthly_chart(clean_ds.tables[table], date, values, worst=True).empty


def test_cache_uses_contents_profile_and_custom_signal_definitions(monkeypatch, clean_ds, clean_results, tmp_path):
    calls = []
    results = list(clean_results.values())[:1]
    def score(ds, profile="india"):
        calls.append((profile, ds.signal_config))
        return results
    monkeypatch.setattr(engine, "score_portfolio", score)
    monkeypatch.setattr(engine, "detect_clusters", lambda ds, rs: [])
    cache = {}
    sources = {"customers.csv": b"original", "risk_signal_definitions.json": b"defaults"}
    fingerprint = source_hash(sources)
    assert fingerprint == source_hash(dict(reversed(list(sources.items()))))
    assess(clean_ds, fingerprint, "india", cache)
    assess(clean_ds, fingerprint, "india", cache)
    assess(clean_ds, fingerprint, "gcc_islamic", cache)
    custom = replace(clean_ds, signal_config={"version": "custom"})
    custom_hash = source_hash({**sources, "risk_signal_definitions.json": b"changed thresholds"})
    assess(custom, custom_hash, "india", cache)
    assert len(calls) == 3
    assert calls[-1][1] == custom.signal_config
    store = Store(tmp_path / "cache.sqlite3")
    run1 = store.save_run(assess(clean_ds, fingerprint, "india", cache)[0], "india", "Real")
    run2 = store.save_run(assess(custom, custom_hash, "india", cache)[0], "india", "Real")
    assert run1 != run2 and len(store.runs()) == 2


def test_uploaded_signal_config_reaches_real_score(clean_ds, clean_results, tmp_path):
    cid = clean_ds.tables["customers"].customer_id.iloc[0]
    sources = {f"{name}.csv": frame.loc[frame.customer_id == cid].to_csv(index=False).encode() for name, frame in clean_ds.tables.items()}
    # A real uploaded JSON definition file is passed through validation and scoring.
    from pathlib import Path
    config = json.loads((Path(__file__).resolve().parents[1] / "config/risk_signal_definitions.json").read_text())
    config["version"] = "integration-custom"
    config["signals"][0]["weight"] = 77
    sources["risk_signal_definitions.json"] = json.dumps(config).encode()
    ds = engine.load_dataset(sources)
    assert ds.signal_config["version"] == "integration-custom"
    result = engine.score_portfolio(ds)[0]
    assert "integration-custom" in result.rules_version
    assert next(s for s in result.signals if s.signal_id == config["signals"][0]["signal_id"]).weight == 77

    store = Store(tmp_path / "custom.sqlite3")
    original_run = store.save_run([clean_results[cid]], "india", "Real")
    original = store.alert(original_run, cid)["result_json"]
    custom_run = store.save_run([result], "india", "Real")
    assert store.alert(original_run, cid)["result_json"] == original
    assert "integration-custom" in store.alert(custom_run, cid)["result_json"]
    assert store.alert(custom_run, cid)["result_json"] != original
