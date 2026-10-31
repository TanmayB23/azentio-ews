"""HTTP API: ingestion, validation, scoring runs, watchlist, customer detail and
append-only analyst review. Uses a temporary store and dataset folder."""
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from ews.store.db import DECISIONS
from tests.conftest import DATA_ROOT

BRIEF_DECISIONS = ["Continue Monitoring", "Requires Investigation", "False Positive", "Escalate for Review"]


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    var = tmp_path_factory.mktemp("var")
    dist = tmp_path_factory.mktemp("dist")
    (dist / "assets").mkdir()
    (dist / "index.html").write_text("<html>app</html>", encoding="utf-8")
    client = TestClient(create_app(var_dir=var, data_root=DATA_ROOT, web_dist=dist))
    ds = client.post("/api/datasets/sample", json={"profile": "india", "variant": "clean"}).json()
    run = client.post("/api/runs", json={"dataset_id": ds["dataset_id"], "profile": "india"})
    assert run.status_code == 201
    return client, ds, run.json(), var


def test_decisions_match_the_brief(ctx):
    client, *_ = ctx
    assert list(DECISIONS) == BRIEF_DECISIONS
    assert client.get("/api/config").json()["decisions"] == BRIEF_DECISIONS


def test_samples_never_ingest_ground_truth(ctx):
    _, ds, _, _ = ctx
    assert not any("ground_truth" in f for f in ds["files"])
    assert "sme_indicators.csv" in ds["files"]


def test_dirty_sample_reports_validation(ctx):
    client, *_ = ctx
    d = client.post("/api/datasets/sample", json={"profile": "india", "variant": "dirty"}).json()
    q = d["quality"]
    assert q["action"]["quarantined"] > 0 and q["action"]["repaired"] > 0
    assert not q["blocking"]
    rows = client.get(f"/api/datasets/{d['dataset_id']}/quarantined/repayments").json()
    assert rows and all(r["issue"] for r in rows)


def test_upload_rejects_bad_files_and_flags_missing_tables(ctx):
    client, *_ = ctx
    bad = client.post("/api/datasets/upload", files=[("files", ("notes.txt", b"x", "text/plain"))])
    assert bad.status_code == 422
    partial = client.post("/api/datasets/upload",
                          files=[("files", ("customers.csv", (DATA_ROOT / "india/clean/customers.csv").read_bytes(), "text/csv"))])
    assert partial.status_code == 200
    blocking = partial.json()["quality"]["blocking"]
    assert any("repayments" in i["issue"] for i in blocking)
    blocked = client.post("/api/runs", json={"dataset_id": partial.json()["dataset_id"], "profile": "india"})
    assert blocked.status_code == 422


def test_summary_counts_add_up(ctx):
    client, _, run, _ = ctx
    s = client.get(f"/api/runs/{run['run_id']}/summary").json()
    assert sum(s["bands"].values()) == s["customers"] == run["customer_count"]
    assert s["exposure_at_risk"] <= s["total_exposure"]
    assert any(c["value"] == "Textiles|Tamil Nadu" for c in s["clusters"])


def test_watchlist_sorts_filters_and_pages(ctx):
    client, _, run, _ = ctx
    url = f"/api/runs/{run['run_id']}/watchlist"
    page = client.get(url, params={"page_size": 500}).json()
    scores = [r["score"] for r in page["rows"]]
    scored = [s for s in scores if s is not None]
    assert scored == sorted(scored, reverse=True)
    assert all(s is None for s in scores[len(scored):])          # insufficient data last
    crit = client.get(url, params={"band": "Critical", "page_size": 5}).json()
    assert crit["total"] > 5 and len(crit["rows"]) == 5 and {r["band"] for r in crit["rows"]} == {"Critical"}
    product = page["facets"]["main_product"][0]
    by_product = client.get(url, params={"main_product": product, "page_size": 500}).json()
    assert all(product in r["products"] for r in by_product["rows"])
    found = client.get(url, params={"q": "C0001"}).json()
    assert found["rows"][0]["customer_id"] == "C0001"
    csv = client.get(f"/api/runs/{run['run_id']}/watchlist.csv", params={"band": "High"})
    assert csv.status_code == 200 and csv.text.startswith("customer_id,")


def test_customer_detail_has_evidence(ctx):
    client, _, run, _ = ctx
    top = client.get(f"/api/runs/{run['run_id']}/watchlist", params={"page_size": 1}).json()["rows"][0]
    d = client.get(f"/api/runs/{run['run_id']}/customers/{top['customer_id']}").json()
    assert d["result"]["score"] == top["score"]
    assert d["repayment_months"] and d["facilities"] and d["transactions"]
    statuses = {s["status"] for s in d["result"]["signals"]}
    assert "Active" in statuses
    assert client.get(f"/api/runs/{run['run_id']}/customers/NOPE").status_code == 404


def test_reviews_append_and_preserve_original(ctx):
    client, _, run, var = ctx
    base = f"/api/runs/{run['run_id']}/customers/C0001"
    original = client.get(f"{base}/alert.json").content
    bad = client.post(f"{base}/reviews", json={"decision": "Confirm", "reason": "x", "analyst": "A"})
    assert bad.status_code == 422
    empty = client.post(f"{base}/reviews", json={"decision": "False Positive", "reason": " ", "analyst": "A"})
    assert empty.status_code == 422
    for decision in ("Requires Investigation", "False Positive"):
        r = client.post(f"{base}/reviews", json={"decision": decision, "reason": f"because {decision}", "analyst": "Analyst"})
        assert r.status_code == 201
    d = client.get(base).json()
    assert [r["decision"] for r in d["reviews"]] == ["False Positive", "Requires Investigation"]
    assert client.get(f"{base}/alert.json").content == original
    assert json.loads(original)["score"] == d["result"]["score"]
    row = client.get(f"/api/runs/{run['run_id']}/watchlist", params={"q": "C0001"}).json()["rows"][0]
    assert row["review_decision"] == "False Positive"
    with sqlite3.connect(var / "ews.sqlite3") as db, pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.execute("UPDATE alerts SET result_json = '{}'")
    with sqlite3.connect(var / "ews.sqlite3") as db, pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.execute("DELETE FROM reviews")


def test_runs_survive_a_restart(ctx):
    _, _, run, var = ctx
    fresh = TestClient(create_app(var_dir=var, data_root=DATA_ROOT, web_dist=var / "no-dist"))
    s = fresh.get(f"/api/runs/{run['run_id']}/summary")
    assert s.status_code == 200 and s.json()["customers"] == run["customer_count"]


def test_serves_single_page_app(ctx):
    client, *_ = ctx
    assert client.get("/watchlist").text == "<html>app</html>"
    assert client.get("/api/unknown").status_code == 404
