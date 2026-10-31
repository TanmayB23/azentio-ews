# Early-Warning-System-the-walking-bread

Streamlit analyst workspace, deterministic fake engine, and append-only SQLite evidence store. Person A's production engine is intentionally not implemented here. The shared dataclasses in `ews/contracts.py` reproduce the team plan without adding fields.

## Run (PowerShell)

Python 3.11+ is supported (verified locally on Python 3.13).

```powershell
python -m venv .venv
./.venv/Scripts/python -m pip install -r requirements.txt
./.venv/Scripts/python -m streamlit run app/main.py
```

Open http://localhost:8501. Select **Data ? Sample data ? clean ? Load dataset ? Score portfolio**, then open **Watchlist**. Demo results are reproducible placeholders, not calculated credit risk. The app never reads ground truth.

## Person B features

- Data: multiple CSV uploads, a multi-sheet `.xlsx`, or table-keyed JSON; bundled clean/dirty samples; quality issues and quarantined tables from the contract; CSV downloads.
- Watchlist: highest score first; main product by largest outstanding facility, total outstanding from latest exposure; product (any held product), segment, band, worst current delinquency bucket, and portfolio filters; row selection opens customer details.
- Detail: all signal contributions and evidence, confidence, special rules, repayment records, worst monthly DPD, inflows/outflows, utilisation, and the original immutable JSON alert. Missing chart months remain gaps.
- Reviews: Confirm, Monitor, Dismiss, Escalate. Analyst and reason are mandatory; each decision adds a row with a UTC timestamp. Database triggers block updates/deletions of runs, alerts, and reviews. These four labels were chosen because the team plan does not specify them.
- Portfolio: all four risk bands plus insufficient data; cluster table and customer drill-down.
- Region: India (`india`) or Gulf-Islamic (`gcc_islamic`) passed to `score_portfolio`. Click **Score portfolio** to apply a change; prior evidence stays unchanged.
- Saved evidence: reopen previous runs and append reviews after an app restart. Historical source tables/charts are not persisted; full original CustomerResult evidence is.

The database defaults to `data/ews.sqlite3` (ignored by git). Override with `$env:EWS_DB_PATH = "path/to/evidence.sqlite3"`. Each explicit scoring action creates one atomic run; navigation and review submissions do not rescore.

## Merge with Person A

Keep the contract coordinated with the engine owner. The real package must export these names from `ews/engine/__init__.py`:

```python
load_dataset(sources: dict[str, str | bytes], fmt_hint: str | None = None) -> Dataset
score_portfolio(ds: Dataset, profile: str = "india") -> list[CustomerResult]
detect_clusters(ds: Dataset, results: list[CustomerResult]) -> list[Cluster]
```

Choose **Real** in the sidebar, reload the data using the real loader, and score. No app code change is required. A missing engine shows a clear error; it does not fall back silently. The engine must accept the six source filenames as mapping keys and file paths or uploaded bytes as values, as defined by the plan.

The demo loader only reads data, without validation or quarantine. For the bundled dirty sample it displays the 43 supplied manifest annotations as warnings marked ?not validated? and leaves rows in place. Uploading arbitrary dirty data requires the real loader for actual checks. The UI renders `Dataset.issues` and `Dataset.quarantined` directly when that loader arrives.

## Verify

```powershell
./.venv/Scripts/python -m pytest -q
```

Tests exercise CSV/Excel/JSON loading, fake-engine contract consistency, score ordering, missing chart months, SQL immutability, transaction rollback, persistence, review history, and Streamlit analyst flows. The shared contract checks run against Person A's engine automatically when available; until then the real-engine cases are skipped.

Original synthetic assets remain in `files/ews_synthetic_data/ews_synthetic_data/`.
