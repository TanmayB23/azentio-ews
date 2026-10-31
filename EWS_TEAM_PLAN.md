# EWS build plan: two people, separate work, planned merges

## How the split works

The app splits into two halves that meet at a single interface:

- **Person A (Engine):** loading and validating data, signals, scoring, clusters. Pure Python; no user interface.
- **Person B (App):** the user interface, storage, watchlist, customer detail screen, analyst review.

Both start by agreeing a **contract**: the function names and output format the engine provides. Person B builds against a **fake engine** that returns correctly shaped dummy results, so B never waits for A. At merge time, the fake is swapped for the real engine. If both follow the contract, nothing else needs to change.

**Stack:** Python 3.11, pandas, Streamlit, SQLite, pytest.

## Repository layout and ownership

```
ews/
  contracts.py          # SHARED: data shapes; change only when both agree
  engine/               # A
    loader.py           #   CSV/Excel/JSON → tables
    validate.py         #   checks, quarantine, link checks between tables
    views.py            #   one row per customer per month
    signals.py          #   the 13 signals + region-specific extras
    scoring.py          #   area scores, special rules, confidence, band
    clusters.py         #   scenario 8
    explain.py          #   plain-English summary of a score
  fake_engine.py        # B: same function names as engine/, returns dummy results
  store/                # B
    db.py               #   SQLite: alerts (never changed), reviews (add-only)
app/                    # B
  main.py               #   Streamlit pages
config/                 # A
  risk_signal_definitions.json
  profiles/india.json, profiles/gcc_islamic.json
tests/
  engine/               # A
  test_contract.py      # SHARED: real engine output matches the contract
data/                   # the clean and dirty sample folders, copied in
```

**Git workflow:**

- Branches are `engine` (A) and `app` (B), merged into `main` at each checkpoint.
- Each person edits only their own folders.
- `contracts.py` changes only when both agree.
- `requirements.txt` is add-only (new lines only).

## Step 0: write the contract together (first 20 minutes)

Write `ews/contracts.py` together and don't change it without agreeing:

```python
from dataclasses import dataclass, field
from typing import Literal
import pandas as pd

@dataclass
class ValidationIssue:
    table: str; record_key: str; field: str | None
    issue: str; severity: Literal["error", "warning"]
    action: Literal["quarantined", "kept"]

@dataclass
class Dataset:
    tables: dict[str, pd.DataFrame]          # customers, facilities, repayments,
                                             # delinquency, exposure, transactions
    issues: list[ValidationIssue]
    quarantined: dict[str, pd.DataFrame]

@dataclass
class SignalResult:
    signal_id: str; name: str; pillar: Literal["RB", "CF", "EX"]
    evaluated: bool; reason_not_evaluated: str | None
    value: float | None; trigger: float; saturation: float
    strength: float; weight: float; points: float
    evidence: list[str]                      # e.g. repayment_ids / months used

@dataclass
class CustomerResult:
    customer_id: str; as_of: str; rules_version: str
    status: Literal["Scored", "Insufficient data"]
    score: float | None                      # 0-100, higher = riskier
    band: Literal["Low", "Medium", "High", "Critical"] | None
    monitoring_status: str                   # Routine/Watch/Investigate/Escalate
    confidence: float                        # 0-1
    pillar_scores: dict[str, float]
    signals: list[SignalResult]
    modifiers: list[str]                     # e.g. "Temporary-miss dampener x0.25 (evidence)"
    summary: str

@dataclass
class Cluster:
    dimension: str; value: str               # e.g. "industry×region", "Textiles|Tamil Nadu"
    n_customers: int; n_elevated: int; lift: float
    top_signals: list[str]; customer_ids: list[str]

# Engine API (A implements in ews/engine, B fakes in ews/fake_engine.py)
def load_dataset(sources: dict[str, "str | bytes"], fmt_hint: str | None = None) -> Dataset: ...
def score_portfolio(ds: Dataset, profile: str = "india") -> list[CustomerResult]: ...
def detect_clusters(ds: Dataset, results: list[CustomerResult]) -> list[Cluster]: ...
```

Also agree on these fixed decisions:

- The as-of date is **2026-10-31**.
- A higher score means higher risk.
- Bands are Low 0–24, Medium 25–49, High 50–74 and Critical 75–100.
- Table and column names are exactly those in the clean CSV files.

## Person A: Engine

| Time | Task | Done when |
|---|---|---|
| 0:20–1:00 | `loader.py` + `validate.py`: read CSV, Excel and JSON; check data types, allowed values, ranges, duplicates, links between tables and contradictory values; move bad rows to quarantine with a reason | Run on `dirty/`, it finds all 43 defects in `data_issues_manifest.csv` (pytest). On `clean/`, it reports 0 errors. |
| 1:00 | **Merge 1:** push `load_dataset` to `main` | B's upload page loads real data |
| 1:00–1:50 | `views.py` + `signals.py`: monthly views (worst DPD across loans, gaps left as gaps); RB01–04, CF01–05, EX01–04, marking a signal "not evaluated" when data is insufficient | Unit tests on 3 hand-picked customers (one repeated-delays, one temporary-miss, one thin-history) |
| 1:50–2:20 | `scoring.py`: score each area (repayment, cash flow, exposure), combine as highest + 0.35 × second + 0.15 × third; temporary-miss dampener; roll-forward rule (score at least 75); recent-episode rule (score at least 25); confidence; "Insufficient data" result | `tests/engine/test_ground_truth.py` prints a table of expected vs. actual bands by scenario. Targets: 0 healthy customers above Medium; thin-history customers all "Insufficient data"; worsening-delinquency customers mostly High or Critical. |
| 2:00 | **Merge 2:** push `score_portfolio` | B's watchlist shows real scores |
| 2:20–2:40 | `clusters.py`: group by industry×region, product, segment and portfolio; compare each group's share of elevated customers with the portfolio average (lift); `explain.py` summaries; `profiles/gcc_islamic.json` | The textile SMEs in Tamil Nadu and the gig workers in Karnataka show up as clusters |

**Rule for A:** never import Streamlit or anything from `app/`. The engine must run from the command line on its own: `python -m ews.engine data/clean`.

## Person B: App

| Time | Task | Done when |
|---|---|---|
| 0:20–0:30 | `fake_engine.py`: same function names as the contract. It loads the clean CSVs with plain pandas and returns made-up `CustomerResult`s (random score, 2–3 made-up signals) and one fake cluster. | B can run the app without any of A's code |
| 0:30–0:50 | Streamlit app: sidebar navigation; **Data** page with upload (CSV, Excel or JSON, several files at once) plus a "use sample data" option; data-quality report table built from `Dataset.issues` | Uploading the dirty folder shows a list of issues |
| 0:50–1:40 | **Watchlist** page: customer ID, main product, total outstanding, score, band, top 3 factors, monitoring status. Filters: product, segment, band, delinquency bucket, portfolio. **Customer detail** page: list of each signal's contribution, repayment table, DPD chart over time, inflows and outflows chart, utilisation chart, special rules applied, confidence. | Clicking a row opens the detail page, built from the dataset tables and the result |
| 1:40–2:20 | `store/db.py`: an `alerts` table written once per scoring run (full `CustomerResult` saved as JSON, never edited) and a `reviews` table that only ever gets new rows (decision, reason required, analyst, timestamp). Review panel on the detail page with the 4 decisions, plus review history. | Changing a decision adds a new row; the original score and evidence stay visible |
| 2:20–2:40 | **Portfolio** page: count of customers in each band, cluster table with a drill-down into its customers. Region dropdown (India / Gulf-Islamic) that is passed to `score_portfolio`. | Works with fake data first, then real |

**Rule for B:** use only fields defined in `contracts.py`. If a field is missing, ask A to add it to the contract; don't work around it.

## Merge checkpoints

1. **1:00, loader:** B switches the Data page from the fake to `ews.engine.load_dataset`. Run `test_contract.py`.
2. **2:00, scoring:** B changes one line, `from ews import fake_engine as engine` → `from ews import engine`. Check the watchlist and detail pages using the real explanations.
3. **2:40, final:** merge both branches into `main` and run every test together (start here: 2:40–3:00 below).

`test_contract.py` runs both the fake and the real engine on `data/clean`. It checks that every result has the correct types, scores between 0 and 100, a band consistent with its score, and signal points that add up. A failing test points straight at the mismatch.

## 2:40–3:00: integration and demo rehearsal (together)

1. Upload `dirty/` and show the data-quality report and quarantined rows.
2. Load `clean/` and score. The watchlist sorts highest risk first; filter to SME + High.
3. Open a worsening-delinquency customer: roll-forward rule fired, DPD chart rising, score explained signal by signal.
4. Open a temporary-miss customer: dampener applied, band Low, evidence shown.
5. Open a thin-history customer: "Insufficient data", low confidence, no made-up risk.
6. Record a review, then change it, to show the original evidence is kept.
7. Portfolio page: open the Tamil Nadu textiles cluster.
8. Switch region to Gulf-Islamic as the innovation point.

## Risks and how to handle them

| Risk | Mitigation |
|---|---|
| A runs late on scoring | B is never blocked, because the fake engine keeps the app demo-ready |
| The contract needs a new field | Add it only as an optional field with a default, both agree, and B updates the fake engine at the same time |
| Merge conflicts | Each person owns separate folders; `requirements.txt` is add-only |
| Scores look wrong in the demo | A's ground-truth table is the evidence; keep it in the repo |
