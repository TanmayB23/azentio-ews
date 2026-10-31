"""The engine's output matches ews/contracts.py, which the API and web app rely on."""
from ews.contracts import Cluster, CustomerResult, Dataset, SignalResult, ValidationIssue
from ews.engine import detect_clusters

BANDS = {"Low": (0, 24.999), "Medium": (25, 49.999), "High": (50, 74.999), "Critical": (75, 100)}


def test_dataset_shape(dirty_ds):
    assert isinstance(dirty_ds, Dataset)
    assert all(isinstance(i, ValidationIssue) for i in dirty_ds.issues)
    assert {i.severity for i in dirty_ds.issues} <= {"error", "warning"}
    assert {i.action for i in dirty_ds.issues} <= {"quarantined", "kept", "repaired"}
    assert all("issue" in df.columns for df in dirty_ds.quarantined.values())


def test_results_shape(clean_results):
    for r in clean_results.values():
        assert isinstance(r, CustomerResult)
        assert r.status in ("Scored", "Insufficient data")
        assert 0 <= r.confidence <= 1
        assert r.summary
        assert all(isinstance(s, SignalResult) for s in r.signals)
        if r.status == "Scored":
            lo, hi = BANDS[r.band]
            assert lo <= r.score <= hi, (r.customer_id, r.score, r.band)
        else:
            assert r.score is None and r.band is None


def test_points_add_up_to_score(clean_results):
    for r in clean_results.values():
        if r.status != "Scored":
            continue
        total = sum(s.points for s in r.signals)
        floored = any("score raised to at least" in m for m in r.modifiers)
        if floored:
            assert r.score >= min(total, 100) - 0.1
        else:
            assert abs(min(total, 100) - r.score) < 0.1, (r.customer_id, total, r.score)


def test_clusters_shape(clean_ds, clean_results):
    for c in detect_clusters(clean_ds, list(clean_results.values())):
        assert isinstance(c, Cluster)
        assert c.n_elevated <= c.n_customers == len(c.customer_ids)


def test_cluster_lift_is_explained_by_its_own_figures(clean_ds, clean_results):
    """The multiplier shown must follow from the hits and rates reported with it."""
    scored = [r for r in clean_results.values() if r.status == "Scored"]
    elevated_rate = sum(r.score >= 25 for r in scored) / len(scored)
    for c in detect_clusters(clean_ds, list(clean_results.values())):
        assert c.group_rate == round(c.basis_hits / c.n_customers, 4)
        assert abs(c.lift - c.group_rate / c.portfolio_rate) < 0.02
        assert abs(c.elevated_lift - (c.n_elevated / c.n_customers) / elevated_rate) < 0.02
        if c.basis == "elevated risk":
            assert c.basis_hits == c.n_elevated and abs(c.lift - c.elevated_lift) < 0.02
