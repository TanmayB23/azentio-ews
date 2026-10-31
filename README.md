# Early-Warning-System-the-walking-bread

Real-engine credit Early Warning System with a Streamlit analyst workspace and an append-only SQLite evidence store. See [ENGINE.md](ENGINE.md) for validation, signals, scoring, and expected scenario results.

## Run

Python 3.11+ (verified locally on Python 3.13):

```powershell
python -m venv .venv
./.venv/Scripts/python -m pip install -r requirements.txt
./.venv/Scripts/python -m streamlit run app/main.py
```

Open http://localhost:8501. On **Data**, choose the **India** or **Gulf-Islamic** sample portfolio, choose **clean**, then **Load dataset** and **Score portfolio**. Changing the sample portfolio selects its matching scoring profile. The sidebar **Region** options come from `available_profiles()` and can also be set explicitly. All app results use `ews.engine`; the fake engine is retained only for its regression tests.

## Data and scoring

- Samples use `data/india/` (500 customers) and `data/gcc_islamic/` (400 customers), each with clean and dirty variants. The app never loads ground_truth.csv.
- Upload named CSVs, a multi-sheet `.xlsx`/`.xlsm`, or table-keyed JSON. Six core tables are required; the seventh, `sme_indicators`, is optional. Missing required tables/columns appear as quality issues and block scoring until corrected.
- Upload `risk_signal_definitions.csv` or `.json` (or its matching workbook sheet) with the data to override thresholds and weights. The Data screen indicates when custom definitions are present.
- Quality reports include severity/action counts, all repaired/kept/quarantined issues, and quarantined rows with their issue reasons. Individual dirty rows do not block assessment of usable records.
- Scoring and clustering can take 10-20 seconds. Results are cached within the session by a SHA-256 hash of all loaded filenames and bytes, including custom signal definitions, plus profile. The cache holds up to four assessments. Navigation and review submissions do not rescore.
- Every explicit **Score portfolio** action saves a new immutable alert run, even when cached calculations are reused. A changed profile or configuration creates separate alerts and never overwrites prior evidence.

## Analyst screens

- **Watchlist:** risk-first ordering with insufficient data grouped last; search by name/ID; filters for any held product, segment, band, current delinquency bucket, and portfolio. Main product is the individual facility with the largest outstanding balance; total outstanding uses the latest exposure observation, falling back to facility balances. Select a row to open customer detail.
- **Customer detail:** summary, confidence, named pillar scores, signal contributions and evidence, applicability/data-coverage states, and special rules. The signal contribution total is displayed separately from the final score so minimum-score rules can be traced. Thin history displays no score or band and the engine's explanation.
- **Account activity:** repayments, worst monthly DPD, inflows/outflows and utilisation. Missing months remain gaps. Gulf-specific facilities require no conventional interest-rate column.
- **SME indicators:** SMEs have an additional tab with monthly tax filing status, reported turnover, receivable days, and payable days. The tab explains when optional indicators are absent.
- **Analyst review:** Confirm, Monitor, Dismiss, Escalate; analyst and reason required. Each submission appends a timestamped decision. Original full CustomerResult JSON includes rules version, all signals, thresholds, applicability, and evidence. SQL triggers prohibit updates/deletions of saved runs, alerts, and reviews.
- **Portfolio:** all risk bands and insufficient data; cluster basis, lift, p-value, leading signals and customer drill-down.
- **Saved evidence:** reopen past assessments after a restart and add reviews. Source tables/charts are session-local; original scored evidence and reviews persist.

The database defaults to `data/ews.sqlite3` (ignored by Git); override with `$env:EWS_DB_PATH = "path/to/evidence.sqlite3"`. No engine-owned source data is modified.

## Verify

```powershell
./.venv/Scripts/python -m pytest -q
```

The combined suite includes Person A's unchanged engine tests, fake-engine compatibility checks, storage immutability/rollback tests, upload/config/cache checks, and Streamlit flows using real India and Gulf results. No engine or contract changes are required for the integration.

## Interface

The theme is in `.streamlit/config.toml`; presentation components and scroll-safe header styling are in `app/ui.py`. The app uses navy navigation, a light workspace, risk colours, summary cards, and customer detail tabs. Use **Back to watchlist** to return to the queue.
