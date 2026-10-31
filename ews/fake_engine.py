"""Deterministic synthetic results for app development, not a risk model."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import pandas as pd
from ews.contracts import Cluster, CustomerResult, Dataset, SignalResult, ValidationIssue

TABLES = ("customers", "facilities", "repayments", "delinquency", "exposure", "transactions")
SAMPLE_ROOT = Path(__file__).resolve().parents[1] / "files/ews_synthetic_data/ews_synthetic_data"


def load_dataset(sources: dict[str, str | bytes], fmt_hint: str | None = None) -> Dataset:
    tables, issues = {}, []
    for name, source in sources.items():
        suffix = (fmt_hint or Path(name).suffix.lstrip(".") or "csv").lower()
        stream = BytesIO(source) if isinstance(source, bytes) else source
        stem = Path(name).stem
        if suffix == "xlsx":
            loaded = pd.read_excel(stream, sheet_name=None)
        elif suffix == "json":
            content = source.decode("utf-8-sig") if isinstance(source, bytes) else Path(source).read_text(encoding="utf-8-sig")
            payload = json.loads(content)
            loaded = {key: pd.DataFrame(value) for key, value in payload.items()} if isinstance(payload, dict) else {stem: pd.DataFrame(payload)}
        elif suffix == "csv":
            loaded = {stem: pd.read_csv(stream)}
        else:
            raise ValueError(f"Unsupported file format: {suffix}")
        for table, frame in loaded.items():
            if table == "data_issues_manifest":
                issues.extend(ValidationIssue(str(r.table), str(r.record_key), None,
                    f"Sample manifest (not validated): {r.issue}", "warning", "kept") for r in frame.itertuples())
            elif table in TABLES:
                if table in tables:
                    raise ValueError(f"Table {table!r} supplied twice. Upload one representation per table.")
                tables[table] = frame
    missing = set(TABLES) - tables.keys()
    if missing:
        raise ValueError(f"Missing tables: {', '.join(sorted(missing))}. Use six named CSVs, portfolio.json, or early_warning_data.xlsx.")
    for name, table in tables.items():
        if "customer_id" not in table.columns:
            raise ValueError(f"{name}: required column customer_id is missing")
    return Dataset(tables, issues, {})


def score_portfolio(ds: Dataset, profile: str = "india") -> list[CustomerResult]:
    if profile not in ("india", "gcc_islamic"):
        raise ValueError(f"Unknown profile: {profile}")
    results = []
    for cid in ds.tables["customers"]["customer_id"].dropna().astype(str).unique():
        seed = int(sha256(f"{cid}:{profile}".encode()).hexdigest()[:8], 16)
        score = float(seed % 101)
        thin = seed % 19 == 0
        signals = [SignalResult(sid, name, pillar, not thin,
            "Demo: insufficient observations" if thin else None,
            None if thin else score / 100, 0.25, 1.0,
            0.0 if thin else score / 100, weight, 0.0 if thin else score * weight / 100,
            [f"Synthetic demo evidence for {cid}; not a calculated risk signal"])
            for sid, name, pillar, weight in (
                ("RB01", "Demo repayment delays", "RB", 50.0),
                ("CF01", "Demo cash-flow pressure", "CF", 30.0),
                ("EX01", "Demo exposure growth", "EX", 20.0))]
        band = "Low" if score < 25 else "Medium" if score < 50 else "High" if score < 75 else "Critical"
        results.append(CustomerResult(cid, "2026-10-31", f"demo-v1:{profile}",
            "Insufficient data" if thin else "Scored", None if thin else score,
            None if thin else band, "Watch" if thin else {"Low": "Routine", "Medium": "Watch", "High": "Investigate", "Critical": "Escalate"}[band],
            0.15 if thin else 0.85, {s.pillar: s.points for s in signals}, signals,
            ["Demo only: no production special rules applied"],
            "Synthetic demo result. Scores and evidence are placeholders unrelated to actual customer risk."))
    return results


def detect_clusters(ds: Dataset, results: list[CustomerResult]) -> list[Cluster]:
    customers = ds.tables["customers"]
    if not {"industry", "region"}.issubset(customers.columns) or not results:
        return []
    members = customers.loc[(customers.industry == "Textiles") & (customers.region == "Tamil Nadu"), "customer_id"].drop_duplicates().tolist()
    if not members:
        return []
    elevated = {r.customer_id for r in results if r.band in ("High", "Critical")}
    count = len(set(members) & elevated)
    baseline = len(elevated) / len(results)
    return [Cluster("Demo industry x region", "Textiles | Tamil Nadu (synthetic cluster)",
        len(members), count, count / len(members) / baseline if baseline else 0.0,
        ["RB01", "CF01"], members)]
