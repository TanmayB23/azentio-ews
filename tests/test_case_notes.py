"""AI case notes, using fake providers (no network, no cost)."""
import pytest
from fastapi.testclient import TestClient

from api import case_notes
from api.case_notes import ActionPick, AIUnavailable, CaseNote, Finding
from api.main import create_app
from tests.conftest import DATA_ROOT


class FakeProvider:
    """Returns a note with one valid citation and deliberate problems to catch."""
    name, model = "fake", "fake-model-1"

    def __init__(self, fail: bool = False):
        self.fail, self.calls, self.payloads = fail, 0, []

    def draft(self, system, payload):
        self.calls += 1
        self.payloads.append(payload)
        if self.fail:
            raise AIUnavailable("Could not reach the provider.")
        active = [s for s in payload["signals"] if s["status"] == "Active"]
        sid = active[0]["id"] if active else payload["signals"][0]["id"]
        actions = payload["recommended_actions"]
        picks = [ActionPick(action_id=a["action_id"], reason="Matches the findings", cites=[sid]) for a in actions]
        picks.append(ActionPick(action_id="CALL_THE_POLICE", reason="invented", cites=[]))
        return CaseNote(
            summary="Inflows fell 987654 last quarter.",
            key_findings=[Finding(text="Main driver", cites=[sid]), Finding(text="Made up", cites=["ZZ99"])],
            recommended_actions=picks, questions_for_customer=["What changed?"], data_gaps=[],
            suggested_decision="Requires Investigation", suggested_decision_reason="High band",
            caveats=[])


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    provider = FakeProvider()
    client = TestClient(create_app(var_dir=tmp_path_factory.mktemp("var"), data_root=DATA_ROOT,
                                   web_dist=tmp_path_factory.mktemp("nodist") / "none", ai_provider=provider))
    ds = client.post("/api/datasets/sample", json={"profile": "india", "variant": "clean"}).json()
    run = client.post("/api/runs", json={"dataset_id": ds["dataset_id"], "profile": "india"}).json()
    return client, provider, run["run_id"]


def _top_customer(client, run_id):
    return client.get(f"/api/runs/{run_id}/watchlist", params={"page_size": 1}).json()["rows"][0]["customer_id"]


def test_config_reports_ai_status(setup):
    client, *_ = setup
    ai = client.get("/api/config").json()["ai"]
    assert ai == {**ai, "enabled": True, "provider": "fake", "model": "fake-model-1"}


def test_watchlist_and_detail_carry_recommended_actions(setup):
    client, _, run_id = setup
    row = client.get(f"/api/runs/{run_id}/watchlist", params={"page_size": 1}).json()["rows"][0]
    assert row["next_action"] and row["next_action_owner"] and row["action_count"] >= 1
    detail = client.get(f"/api/runs/{run_id}/customers/{row['customer_id']}").json()
    assert detail["recommended_actions"][0]["title"] == row["next_action"]
    summary = client.get(f"/api/runs/{run_id}/summary").json()
    assert summary["actions"]["customers_with_actions"] > 0


def test_note_is_checked_against_its_input(setup):
    client, provider, run_id = setup
    cid = _top_customer(client, run_id)
    note = client.post(f"/api/runs/{run_id}/customers/{cid}/case-notes", json={"analyst": "Tester"}).json()
    assert note["source"] == "fake" and note["model"] == "fake-model-1" and not note["cached"]
    checks = note["verification"]
    assert checks["status"] == "check"
    assert checks["unknown_citations"] == ["ZZ99"]
    assert checks["dropped_actions"] == ["CALL_THE_POLICE"]
    assert 987654 in checks["unverified_numbers"]
    assert all(a["action_id"] != "CALL_THE_POLICE" for a in note["note"]["recommended_actions"])


def test_customer_names_are_not_sent_by_default(setup):
    _, provider, _ = setup
    assert provider.payloads and all("customer_name" not in p["customer"] for p in provider.payloads)


def test_same_input_reuses_the_saved_note(setup):
    client, provider, run_id = setup
    cid = _top_customer(client, run_id)
    url = f"/api/runs/{run_id}/customers/{cid}/case-notes"
    before = provider.calls
    again = client.post(url, json={}).json()
    assert again["cached"] and provider.calls == before
    fresh = client.post(url, json={"regenerate": True}).json()
    assert not fresh["cached"] and provider.calls == before + 1
    assert [n["note_id"] for n in client.get(url).json()][:2] == [fresh["note_id"], again["note_id"]]


def test_review_can_link_its_note_but_only_for_the_same_alert(setup):
    client, _, run_id = setup
    rows = client.get(f"/api/runs/{run_id}/watchlist", params={"page_size": 2}).json()["rows"]
    a, b = rows[0]["customer_id"], rows[1]["customer_id"]
    note_id = client.get(f"/api/runs/{run_id}/customers/{a}/case-notes").json()[0]["note_id"]
    ok = client.post(f"/api/runs/{run_id}/customers/{a}/reviews",
                     json={"decision": "Escalate for Review", "reason": "Per AI draft, checked", "analyst": "T",
                           "ai_note_id": note_id})
    assert ok.status_code == 201 and ok.json()["ai_note_id"] == note_id
    wrong = client.post(f"/api/runs/{run_id}/customers/{b}/reviews",
                        json={"decision": "Continue Monitoring", "reason": "x", "analyst": "T", "ai_note_id": note_id})
    assert wrong.status_code == 422


def test_without_a_provider_notes_come_from_rules(tmp_path):
    client = TestClient(create_app(var_dir=tmp_path, data_root=DATA_ROOT, web_dist=tmp_path / "none", ai_provider=None))
    assert client.get("/api/config").json()["ai"]["enabled"] is False
    ds = client.post("/api/datasets/sample", json={"profile": "india", "variant": "clean"}).json()
    run_id = client.post("/api/runs", json={"dataset_id": ds["dataset_id"], "profile": "india"}).json()["run_id"]
    cid = _top_customer(client, run_id)
    note = client.post(f"/api/runs/{run_id}/customers/{cid}/case-notes", json={}).json()
    assert note["source"] == "template" and note["error"] is None
    assert note["verification"]["status"] == "verified"
    assert note["note"]["recommended_actions"]


def test_provider_failure_falls_back_and_retries_later(tmp_path):
    provider = FakeProvider(fail=True)
    client = TestClient(create_app(var_dir=tmp_path, data_root=DATA_ROOT, web_dist=tmp_path / "none",
                                   ai_provider=provider))
    ds = client.post("/api/datasets/sample", json={"profile": "india", "variant": "clean"}).json()
    run_id = client.post("/api/runs", json={"dataset_id": ds["dataset_id"], "profile": "india"}).json()["run_id"]
    url = f"/api/runs/{run_id}/customers/{_top_customer(client, run_id)}/case-notes"
    first = client.post(url, json={}).json()
    assert first["source"] == "template" and "Could not reach" in first["error"]
    client.post(url, json={})
    assert provider.calls == 2                      # a failed draft is not reused


def test_template_notes_pass_checks_for_every_band(clean_ds, clean_results):
    from ews.engine import detect_clusters
    from ews.engine.config import load_profile
    from ews.interventions import customer_facts, recommend
    facts = customer_facts(clean_ds, detect_clusters(clean_ds, list(clean_results.values())), "india")
    profile = load_profile("india")
    for cid in ["C0040", "C0009", "C0046", "C0273", "C0001", "C0003", "C0066"]:
        payload = case_notes.build_payload(clean_results[cid], recommend(clean_results[cid], facts[cid]), profile,
                                           None, facts[cid].clusters)
        note, checks = case_notes.verify(case_notes.template_note(payload), payload)
        assert checks["status"] == "verified", (cid, checks)
