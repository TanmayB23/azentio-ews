# EWS: Early Warning System

A credit-risk early warning workspace. It ingests customer, facility, repayment, delinquency, exposure and transaction data, then:

- validates and links the data;
- scores every customer 0–100 (higher = riskier) with an explanation for each score;
- surfaces a filterable watchlist and portfolio risk clusters;
- lets analysts record decisions without ever changing the original evidence.

- **Engine** (`ews/engine`): validation, 15 configurable signals, scoring, cluster detection. See [ENGINE.md](ENGINE.md).
- **API** (`api/`): FastAPI service with an append-only SQLite evidence store.
- **Web app** (`web/`): React + TypeScript single-page app, served by the API.

## Run it

Requires Python 3.11+ and Node 20+.

```bash
python -m venv .venv
.venv/Scripts/activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cd web && npm ci && npm run build && cd ..
python -m api                     # http://127.0.0.1:8000  (API docs at /docs)
```

Then open the app and go to **Data & validation**:

1. Pick a sample portfolio (India or GCC Islamic, clean or dirty) or upload your own CSV, Excel or JSON files.
2. Review the validation report.
3. Click **Run assessment**.

**Development:** run `python -m api --reload` and, in `web/`, `npm run dev` (http://localhost:5173, with `/api` proxied to the API).

| Setting | Default | Purpose |
|---|---|---|
| `EWS_VAR_DIR` | `var/` | Stored datasets and the evidence database |
| `EWS_DB_PATH` | `var/ews.sqlite3` | Evidence database file |
| `EWS_DATA_ROOT` | `data/` | Sample portfolios |

## What the app covers

| Screen | Purpose |
|---|---|
| Overview | Exposure at risk, band mix, customers above each score threshold, review progress, priority customers, emerging clusters |
| Watchlist | Every customer with product, outstanding, score, band, contributing indicators, DPD, confidence and monitoring status. Filters for band, product, segment, delinquency, portfolio, type, region and review status; sortable, paged, CSV export, shareable URLs |
| Customer | Score ring and breakdown, why-this-score summary, every signal's points, evidence charts (repayments, cash flow, exposure, SME), repayment history, facilities, analyst review with full decision history |
| Portfolio & clusters | Statistically significant concentrations by industry, region, product, segment and portfolio, with drill-down |
| Data & validation | Upload or sample data, issue report (quarantined / repaired / kept), quarantined rows, region profile, run assessment |
| Audit trail | Every saved assessment and every analyst decision |
| How scoring works | Plain-language explanation of signals, score, adjustments, bands and decisions |

Analyst decisions are **Continue Monitoring**, **Requires Investigation**, **False Positive** and **Escalate for Review**, and each needs a reason. Decisions are appended to a history. The original score and evidence are stored once, and database triggers reject any update or delete.

## Tests

```bash
python -m pytest                  # engine, contract and API tests
cd web && npm run typecheck
```

## Layout

```
api/            FastAPI app, dataset registry, screen read models
ews/engine/     validation, signals, scoring, clusters (pure Python)
ews/store/      append-only SQLite evidence store
ews/contracts.py  shared data contract
web/            React + TypeScript front end (Vite)
config/         signal definitions and region profiles
data/           generated sample portfolios (ground_truth.csv is for tests only)
scripts/        synthetic data generator
```

Not included yet: authentication. Analysts enter their name in Settings and it is recorded on each decision. In production, put the app behind SSO and take the analyst identity from the session.

## Three-month delinquency forecast (ML)

Customer detail now pairs the rule score with a separate gradient-boosting estimate of reaching **30+ DPD within the next three months**, including local TreeSHAP factors. A trained synthetic demonstration artifact is included; retraining is offline with `python -m ews.ml.train`. Install the updated requirements before starting the API.

**Synthetic-data prototype: the method is ready for real data, not evidence of predictive accuracy.** The generated history has very few serious outcomes; held-out diagnostics, counts and limitations are shown in model details. Current 30+ DPD and insufficient-history cases receive an explicit status instead of an invented incident probability. Saved ML forecasts are versioned separately from immutable rule evidence.

See [ML_MODEL.md](ML_MODEL.md) for target construction, point-in-time features, censoring, splits, calibration, reproducibility, API endpoints and validation limitations.
