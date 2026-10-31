"""Ask EWS, cluster briefings, risk memos and column mapping: rules fallback and fake-AI paths (no network)."""
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api import ask, briefings, mapping
from api.main import create_app
from tests.conftest import DATA_ROOT

BANK_NAMES = {   # a bank extract using its own file and column names
    "customers": ("Client_Master.csv", {"customer_id": "Cust_No", "customer_type": "Cust Type",
                                        "declared_monthly_income": "Declared Income", "onboarding_date": "Onboarding Dt",
                                        "portfolio_classification": "Portfolio"}),
    "facilities": ("loan_accounts.csv", {"loan_id": "Loan No", "customer_id": "Cust_No",
                                         "outstanding_balance": "OS Balance", "sanctioned_amount": "Sanctioned Amt",
                                         "instalment_amount": "EMI Amount", "disbursement_date": "Disb Date"}),
    "repayments": ("EMI_schedule.csv", {"repayment_id": "Repayment Ref", "loan_id": "Loan No", "customer_id": "Cust_No",
                                        "due_date": "Due Dt", "payment_date": "Paid Dt", "amount_due": "Amt Due",
                                        "amount_paid": "Amt Paid", "dpd": "Days Past Due"}),
    "delinquency": ("arrears.csv", {"loan_id": "Loan No", "customer_id": "Cust_No", "current_dpd": "Current DPD"}),
    "exposure": ("bureau_exposure.csv", {"customer_id": "Cust_No", "utilisation_pct": "Utilization %"}),
    "transactions": ("bank_statements_txn.csv", {"customer_id": "Cust_No", "total_inflows": "Total Inflow"}),
}


class FakeAI:
    """Returns schema-valid answers containing deliberate mistakes the checks must catch."""
    name, model = "fake", "fake-1"

    def parse(self, system, content, schema, max_tokens=4000):
        data = json.loads(content)
        if schema is ask.WatchQuery:
            return ask.WatchQuery(search="", band=["Critical", "Severe"], main_product=[], segment=[], portfolio=[],
                                  delinquency_bucket=[], customer_type=["SME"], region=["Tamil Nadu"], industry=[],
                                  signals=["SM02", "ZZ01"], score_min=None, score_max=None, review="unreviewed",
                                  sort="score", order="desc", explanation="Critical SMEs in Tamil Nadu", unsupported=[])
        if schema is briefings.ClusterBriefing:
            first = data["members"][0]["id"]
            return briefings.ClusterBriefing(
                headline="Receivables slowing", pattern=f"Exposure {data['cluster']['exposure']} at risk.",
                shared_drivers=[briefings.Driver(text="Slower collections", cites=["SM02", "XX99"])],
                segment_wide=True, segment_wide_reason="Most members affected", segment_actions=["Sector review"],
                customers_to_prioritise=[first, "C9999"], caveats=["Losses of 123456789 expected"])
        if schema is briefings.RiskMemo:
            return briefings.RiskMemo(title="Memo", headline=f"At risk: {data['exposure_at_risk_high_critical']}",
                                      key_points=[briefings.MemoPoint(text="Fine")], changes_since_last=[],
                                      clusters=[], actions_due=[], data_quality="ok", recommendations=[])
        raise AssertionError(schema)


@pytest.fixture(scope="module")
def apps(tmp_path_factory):
    def make(provider):
        var = tmp_path_factory.mktemp("var")
        client = TestClient(create_app(var_dir=var, data_root=DATA_ROOT, web_dist=var / "none", ai_provider=provider))
        ds = client.post("/api/datasets/sample", json={"profile": "india", "variant": "clean"}).json()
        run = client.post("/api/runs", json={"dataset_id": ds["dataset_id"], "profile": "india"}).json()["run_id"]
        return client, run
    return {"rules": make(None), "ai": make(FakeAI())}


# ----------------------------------------------------------------- Ask EWS
def test_keyword_questions_become_filters(apps):
    client, run = apps["rules"]
    r = client.post(f"/api/runs/{run}/ask", json={"question": "critical SMEs in Tamil Nadu not reviewed"}).json()
    f = r["filters"]
    assert r["source"] == "keywords"
    assert f["band"] == ["Critical"] and f["customer_type"] == ["SME"] and f["region"] == ["Tamil Nadu"]
    assert f["review"] == "unreviewed" and r["total"] > 0
    assert all(row["band"] == "Critical" and row["region"] == "Tamil Nadu" for row in r["rows"])
    r = client.post(f"/api/runs/{run}/ask", json={"question": "textiles customers with receivable days rising"}).json()
    assert r["filters"]["industry"] == ["Textiles"] and r["filters"]["signals"] == ["SM02"]
    assert all("SM02" in row["active_signals"] for row in r["rows"])


def test_ai_filters_are_limited_to_real_values(apps):
    client, run = apps["ai"]
    r = client.post(f"/api/runs/{run}/ask", json={"question": "anything"}).json()
    assert r["source"] == "fake"
    assert r["filters"]["band"] == ["Critical"] and r["filters"]["signals"] == ["SM02"]
    assert set(r["dropped"]) == {"band=Severe", "signals=ZZ01"}


def test_watchlist_accepts_the_new_filters(apps):
    client, run = apps["rules"]
    page = client.get(f"/api/runs/{run}/watchlist", params={"industry": "Textiles", "signals": "SM02",
                                                            "score_min": 50, "page_size": 500}).json()
    assert page["total"] > 0
    assert all(r["industry"] == "Textiles" and "SM02" in r["active_signals"] and r["score"] >= 50 for r in page["rows"])


# ----------------------------------------------------------------- cluster briefing
def _first_cluster(client, run):
    c = client.get(f"/api/runs/{run}/clusters").json()[0]
    return {"dimension": c["dimension"], "value": c["value"]}


def test_rules_briefing_passes_its_checks(apps):
    client, run = apps["rules"]
    b = client.post(f"/api/runs/{run}/clusters/briefing", json=_first_cluster(client, run)).json()
    assert b["source"] == "template" and b["verification"]["status"] == "verified"
    assert b["output"]["customers_to_prioritise"]
    again = client.post(f"/api/runs/{run}/clusters/briefing", json=_first_cluster(client, run)).json()
    assert again["cached"] and again["output_id"] == b["output_id"]


def test_ai_briefing_mistakes_are_caught(apps):
    client, run = apps["ai"]
    b = client.post(f"/api/runs/{run}/clusters/briefing", json=_first_cluster(client, run)).json()
    checks = b["verification"]
    assert checks["status"] == "check"
    assert checks["unknown_citations"] == ["XX99"] and checks["dropped_customers"] == ["C9999"]
    assert 123456789 in checks["unverified_numbers"]
    assert "C9999" not in b["output"]["customers_to_prioritise"]


def test_unknown_cluster_is_404(apps):
    client, run = apps["rules"]
    assert client.post(f"/api/runs/{run}/clusters/briefing", json={"dimension": "x", "value": "y"}).status_code == 404


# ----------------------------------------------------------------- risk memo
def test_memo_compares_with_the_previous_assessment(apps):
    client, run = apps["rules"]
    first = client.post(f"/api/runs/{run}/memo", json={}).json()
    assert first["compared_with"] is None and first["verification"]["status"] == "verified"
    ds = client.post("/api/datasets/sample", json={"profile": "india", "variant": "dirty"}).json()
    run2 = client.post("/api/runs", json={"dataset_id": ds["dataset_id"], "profile": "india"}).json()["run_id"]
    memo = client.post(f"/api/runs/{run2}/memo", json={}).json()
    assert memo["compared_with"]["run_id"] == run
    assert memo["output"]["changes_since_last"][0].startswith("Since")
    md = client.get(f"/api/runs/{run2}/memo/{memo['output_id']}.md")
    assert md.status_code == 200 and md.text.startswith("# Portfolio risk memo")


def test_ai_memo_may_quote_formatted_amounts(apps):
    client, run = apps["ai"]
    memo = client.post(f"/api/runs/{run}/memo", json={}).json()
    assert memo["source"] == "fake" and memo["verification"]["status"] == "verified"


# ----------------------------------------------------------------- column mapping
def _bank_files():
    files = []
    for table, (name, renames) in BANK_NAMES.items():
        df = pd.read_csv(DATA_ROOT / "india" / "clean" / f"{table}.csv", dtype=str).rename(columns=renames)
        files.append(("files", (name, df.to_csv(index=False).encode(), "text/csv")))
    return files


def test_mapping_fixes_a_bank_extract(apps):
    client, _ = apps["rules"]
    files = _bank_files()
    raw = client.post("/api/datasets/upload", files=files, data={"label": "raw"}).json()
    assert raw["quality"]["blocking"]
    proposal = client.post("/api/datasets/propose-mapping", files=files).json()
    assert proposal["source"] == "fuzzy" and not proposal["missing_required"]
    assert {f["file"]: f["table"] for f in proposal["files"]} == {name: t for t, (name, _) in BANK_NAMES.items()}
    mapped = client.post("/api/datasets/upload", files=files, data={
        "label": "mapped", "column_mapping": json.dumps({"files": proposal["files"], "notes": proposal["notes"]})}).json()
    assert not mapped["quality"]["blocking"] and mapped["quality"]["severity"]["error"] == 0
    assert mapped["quality"]["tables"]["repayments"] > 10000


def test_mapping_cleaning_rejects_invalid_targets():
    described = [{"file": "x.csv", "columns": [{"name": "a", "samples": []}, {"name": "b", "samples": []}]}]
    proposal = mapping.MappingProposal(files=[mapping.FileMap(file="x.csv", table="customers", columns=[
        mapping.ColumnMap(source="a", target="customer_id"), mapping.ColumnMap(source="b", target="customer_id")])],
        notes=[])
    cleaned, checks = mapping.clean(proposal, described)
    targets = [c.target for c in cleaned.files[0].columns]
    assert targets == ["customer_id", ""] and checks["dropped"] == ["x.csv: b -> customer_id"]
    assert "customer_type" in checks["missing_required"]["customers"]


# ----------------------------------------------------------------- evidence checker
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


class FakeEvidenceAI:
    name, model = "fake", "fake-vision"

    def __init__(self):
        self.content = None

    def parse(self, system, content, schema, max_tokens=4000):
        from api.evidence import EvidenceAssessment
        self.content = content
        ids = [r["repayment_id"] for r in json.loads(content[0]["text"])["late_instalments"]]
        return EvidenceAssessment(document_type="salary delay letter", issuer="Employer Ltd", document_date="2026-05-02",
                                  verdict="supports", repayment_ids=ids[:1] + ["R999999"], matched_details=["May 2026"],
                                  concerns=[], summary="Letter confirms salary was paid late in May.")


def _late_customer(client, run):
    rows = client.get(f"/api/runs/{run}/watchlist", params={"band": "Critical", "page_size": 5}).json()["rows"]
    for r in rows:
        reps = client.get(f"/api/runs/{run}/customers/{r['customer_id']}").json()["repayments"]
        late = [x for x in reps if (x["dpd"] or 0) > 0]
        if late:
            return r["customer_id"], late[0]["repayment_id"]
    raise AssertionError("no late payment found")


def test_evidence_without_ai_is_stored_and_decided_by_the_analyst(apps):
    client, run = apps["rules"]
    cid, rid = _late_customer(client, run)
    url = f"/api/runs/{run}/customers/{cid}"
    bad = client.post(f"{url}/evidence-checks", files={"file": ("note.txt", b"x", "text/plain")})
    assert bad.status_code == 422
    check = client.post(f"{url}/evidence-checks", files={"file": ("letter.png", PNG, "image/png")},
                        data={"repayment_id": rid, "claim": "Salary paid late"}).json()
    assert check["output"]["verdict"] == "not assessed" and check["output"]["file_name"] == "letter.png"
    decision = client.post(f"{url}/evidence-decisions", json={"repayment_id": rid, "accepted": True,
                                                              "note": "Letter checked by hand", "analyst": "T",
                                                              "output_id": check["output_id"]})
    assert decision.status_code == 201 and decision.json()["accepted"] == 1
    assert client.get(f"{url}/evidence-decisions").json()[0]["repayment_id"] == rid
    foreign = client.post(f"{url}/evidence-decisions", json={"repayment_id": "R-not-theirs", "accepted": True,
                                                             "note": "x", "analyst": "T"})
    assert foreign.status_code == 422


def test_ai_evidence_reads_the_document_and_unknown_instalments_are_dropped(tmp_path):
    ai = FakeEvidenceAI()
    client = TestClient(create_app(var_dir=tmp_path, data_root=DATA_ROOT, web_dist=tmp_path / "none", ai_provider=ai))
    ds = client.post("/api/datasets/sample", json={"profile": "india", "variant": "clean"}).json()
    run = client.post("/api/runs", json={"dataset_id": ds["dataset_id"], "profile": "india"}).json()["run_id"]
    cid, _ = _late_customer(client, run)
    check = client.post(f"/api/runs/{run}/customers/{cid}/evidence-checks",
                        files={"file": ("letter.png", PNG, "image/png")}).json()
    assert check["source"] == "fake" and check["output"]["verdict"] == "supports"
    assert check["verification"]["unknown_repayments"] == ["R999999"]
    assert "R999999" not in check["output"]["repayment_ids"]
    assert ai.content[1]["type"] == "image_url" and ai.content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "customer_name" not in ai.content[0]["text"]
    assert any((tmp_path / "evidence").iterdir())
