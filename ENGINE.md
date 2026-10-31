# EWS engine (Person A)

Pure-Python engine behind the app. Contract: `ews/contracts.py`.

## Use

```python
from ews.engine import load_dataset, load_dir, score_portfolio, detect_clusters

ds = load_dataset({"customers.csv": b"...", "facilities.csv": path, ...})   # CSV / .xlsx / .json
ds = load_dir("data/india/clean")                                            # or a whole folder
results = score_portfolio(ds, profile="india")                               # or "gcc_islamic"
clusters = detect_clusters(ds, results)
```

Command line: `python -m ews.engine data/india/clean [--profile india] [--top 20]`
Tests: `python -m pytest` (`-s tests/engine/test_ground_truth.py -k print` prints the scenario tables).

## Data

`scripts/generate_data.py` writes `data/<profile>/` with 18 months of history (as-of 2026-10-31):

| Portfolio | Customers | Notes |
|---|---|---|
| `data/india` | 500 | INR, Indian states, conventional products |
| `data/gcc_islamic` | 400 | AED, GCC cities, Islamic contracts (`contract_type`, `profit_rate_pct`, `resident_type`) |

Each has `clean/` (CSV, Excel, JSON), `dirty/` (with injected defects listed in `data_issues_manifest.csv`) and `ground_truth.csv` (tests only). Tables: customers, facilities, repayments, delinquency, exposure, transactions, plus the optional `sme_indicators` table (monthly tax filing status, receivable and payable days). The original sample in `files/` is kept for reference, but tests use `data/`.

## Validation

| Action | When | Examples |
|---|---|---|
| quarantined (error) | row unusable | orphan loan/customer, duplicate key, month `2026-13` |
| repaired (warning) | value derivable | `total_inflows` = income + other; utilisation = drawn / limit; customer type from portfolio, nearest spelling or case; `1,20,000` parsed as a number; status vs DPD |
| kept (warning) | field blanked | negative amounts, unparseable dates, tenure 0, missing obligations |

Quarantined rows are in `ds.quarantined[table]` with an `issue` column. A missing `sme_indicators` table is not an error; its signals become "not applicable".

## Score (0-100, higher = riskier)

1. 15 signals from `config/risk_signal_definitions.json`, each with a plain-language `condition`. Each signal goes from strength 0 at its trigger to 1 at its saturation. Signals without enough data are "not evaluated". Signals that don't fit the customer are "not applicable", e.g. utilisation with no revolving facility, or SME signals for individuals.
2. Pillar score (Repayment RB, Cash flow CF, Exposure EX, Business SM) = weighted strength of the evaluated signals in that pillar, 0-100.
3. Score = highest pillar + 0.35 × second + 0.15 × third + 0.10 × fourth, capped at 100. Each signal's `points` is its share of this, so the points add up to the score.
4. Modifiers (`result.modifiers`):
   - Temporary-miss dampener: one material late month in 6 (more than 3 days), clean before, recovered after → repayment signals ×0.25 with evidence, ×0.6 without.
   - Seasonal dampener: with 15+ months of transactions, if the last 3 months' income is no more than 5% below the same months last year, the inflow-decline signals are ×0.3.
   - Roll-forward: latest instalment unpaid after ≥2 late payments with non-decreasing delays (or earlier instalments also unpaid) → score ≥ 75.
   - Recent episode: ≥3 late months in 6 with a delay of ≥10 days → score ≥ 25.
   - A late payment on a weekend or profile holiday, cleared within 3 days, is recorded as an exception with evidence.
5. Confidence = share of applicable signal weight evaluated. If there are fewer than 4 repayment months or confidence is below 0.5, the status is "Insufficient data" with no score or band.

Bands: Low 0-24 (Routine), Medium 25-49 (Watch), High 50-74 (Investigate), Critical 75-100 (Escalate).
Region-specific settings (calendar, scoring factors, rule thresholds) are in `config/profiles/*.json`.

## Clusters

For each group (industry x region, industry, region, segment, portfolio, main product) two one-sided binomial tests run against the portfolio:

- **Elevated risk:** share of customers scoring Medium or above (lift ≥ 1.5, p ≤ 0.001).
- **Shared signal:** share of customers with the same warning signal active (lift ≥ 2.5, p ≤ 0.0001). This catches early-stage clusters before scores are high.

A broader group must still be significant after removing the members of stronger clusters inside it. This stops a region from being reported only because it holds one hot industry. `Cluster.basis` says which test fired.

## Results (ground truth used only in tests)

| Scenario | India L/M/H/C/Insuff | GCC L/M/H/C/Insuff |
|---|---|---|
| Healthy | 307/2/0/0/0 | 252/1/0/0/0 |
| Volatile but stable | 15/0/0/0/0 | 12/0/0/0/0 |
| Seasonal SME | 10/0/0/0/0 | 8/0/0/0/0 |
| Temporary miss, with evidence | 10/0/0/0/0 | 8/0/0/0/0 |
| Temporary miss, no evidence | 10/0/0/0/0 | 8/0/0/0/0 |
| No transaction data | 5/0/0/0/0 | 4/0/0/0/0 |
| Transaction gap | 10/0/0/0/0 | 8/0/0/0/0 |
| Thin history | 0/0/0/0/12 | 0/0/0/0/10 |
| Repeated delays | 0/5/2/13/0 | 0/6/4/6/0 |
| Declining cash flow | 0/4/14/0/0 | 0/6/6/2/0 |
| Increasing exposure | 0/2/12/4/0 | 0/3/9/2/0 |
| Early delinquency, recovering | 0/10/0/0/0 | 0/8/0/0/0 |
| Early delinquency, worsening | 0/0/0/12/0 | 0/0/0/10/0 |
| SME stress | 0/0/0/12/0 | 0/0/0/10/0 |
| Cluster scenarios | textiles TN 0/0/0/12, gig KA 0/1/7/0, logistics 0/1/1/7 | contractors Dubai 0/0/0/10, riders Riyadh 0/4/3/0 |

Planted clusters detected: Textiles|Tamil Nadu, Gig Economy|Karnataka and Logistics & Transport (India); Construction & Contracting|Dubai and Delivery & Ride-hailing|Riyadh (GCC).
