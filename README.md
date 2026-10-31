# BreadAhead: Early Warning System

**BreadAhead** is a credit-risk early warning workspace. It ingests customer, facility, repayment, delinquency, exposure and transaction data, then:

- validates and links the data;
- scores every customer 0–100 (higher = riskier) with an explanation for each score;
- surfaces a filterable watchlist and portfolio risk clusters;
- lets analysts record decisions without ever changing the original evidence.

- **Engine** (`ews/engine`): validation, 15 configurable signals, an unusual-behaviour model (isolation forest), scoring, cluster detection. See [ENGINE.md](ENGINE.md).
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

**Development (from the repository root):**

```powershell
npm install                            # installs the web dependencies too
./.venv/Scripts/python -m pip install -r requirements.txt
```

Start the API in one terminal:

```powershell
./.venv/Scripts/python -m api --reload  # http://127.0.0.1:8000
```

Start the front end in a second terminal, also from the repository root:

```powershell
npm run dev                            # http://localhost:5173
```

The Vite server proxies `/api` requests to the Python API, so both processes must run. Root-level `npm run build` and `npm run typecheck` also forward to the web app. Running the npm commands directly inside `web/` still works. On macOS/Linux, use `.venv/bin/python` in place of `.venv/Scripts/python`.

| Setting | Default | Purpose |
|---|---|---|
| `EWS_VAR_DIR` | `var/` | Stored datasets and the evidence database |
| `EWS_DB_PATH` | `var/ews.sqlite3` | Evidence database file |
| `EWS_DATA_ROOT` | `data/` | Sample portfolios |

## Recommended actions and AI case notes

Every alert gets **recommended actions** from a rules playbook ([config/interventions.json](config/interventions.json)): who acts (collections, RM, credit, operations), by when, and the reasons and signals that triggered it. The watchlist shows each customer's next action; the Overview counts open actions by owner.

On a customer page, **Draft case note** produces a short note: summary, cited findings, ranked next steps, questions for the customer, data gaps, and a suggested decision. **Use in review** copies it into the review form. The analyst still decides, and the review records which note was used.

Put these settings in a `.env` file in the project root: copy [.env.example](.env.example) to `.env` and fill in your key. Git ignores `.env`. It's read by `python -m api`, and variables already set in the environment take priority.

| Setting | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | not set | Enables AI drafting with OpenAI. Without it, notes are drafted from rules |
| `EWS_AI_MODEL` | `gpt-4.1-mini` | OpenAI model used for notes. Set this to a model your key can use |
| `EWS_AI_ENABLED` | `1` | Set to `0` to turn AI drafting off |
| `EWS_AI_SEND_NAMES` | not set | Set to `1` to include customer names in what is sent to OpenAI (off by default) |

Safeguards:
- **Limited input:** the model sees only the saved alert, the actions that already fired, and segment, product and region facts.
- **Fixed output:** the output schema is fixed.
- **Checked after drafting:** actions not in the playbook are removed, and citations or numbers not found in the alert are flagged as "Check before use".
- **Saved and reused:** notes are add-only and reused when the input hasn't changed.
- **Fallback:** if the call fails, a rules-based note is shown with the reason.

### Other AI assistants

They use the same OpenAI settings and the same safeguards: limited input, a fixed output schema, checks in code, add-only storage, and a fallback that works without a key.

| Feature | Where | What it does | Without a key |
|---|---|---|---|
| **Ask EWS** | Watchlist | Turns a question ("critical SMEs in Tamil Nadu not yet reviewed") into watchlist filters chosen only from the assessment's real values; the applied filters stay visible and editable | Keyword matching |
| **Cluster briefing** | Portfolio & clusters | Headline, pattern, cited shared drivers, whether it looks segment-wide, segment actions and customers to review first | Built from the cluster's figures |
| **Risk memo** | Risk memo | One-page management summary with changes since the previous assessment of the same portfolio; downloadable as Markdown | Built from the summary figures |
| **Column mapping** | Data → Upload files → Map my column names | Maps a bank's own file and column names to ours; you review and edit it before uploading | Fuzzy name matching |
| **Evidence check** | Customer page | Reads a PDF or image explaining a late payment and reports whether it supports the claim; you accept or reject it, and the score is never changed | Stores the document for manual review |

What is sent to OpenAI:
- **Ask EWS:** your question and the list of filter values.
- **Briefings and memos:** aggregated figures and customer IDs.
- **Column mapping:** file names, column headers and three sample values per column.
- **Evidence check:** the document and the customer's late instalments.
- **Customer names:** never sent, unless `EWS_AI_SEND_NAMES=1`.

All outputs are also checked for wording the EWS must not use, such as "default rate" or "probability of default", since it measures deterioration, not default.

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
