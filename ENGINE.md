# EWS engine (Person A)

Pure-Python engine behind the app. Contract: `ews/contracts.py`.

## Use

```python
from ews.engine import load_dataset, load_dir, score_portfolio, detect_clusters

ds = load_dataset({"customers.csv": b"...", "facilities.csv": path, ...})   # CSV / .xlsx / .json
ds = load_dir("files/ews_synthetic_data/ews_synthetic_data/clean")           # or a whole folder
results = score_portfolio(ds, profile="india")                               # or "gcc_islamic"
clusters = detect_clusters(ds, results)
```

Command line: `python -m ews.engine <folder> [--profile india] [--top 20]`
Tests: `python -m pytest` (`-s tests/engine/test_ground_truth.py` prints the scenario table).

## Validation

| Action | When | Examples |
|---|---|---|
| quarantined (error) | row unusable | orphan loan/customer, duplicate key, month `2026-13` |
| repaired (warning) | value derivable | `total_inflows` = income + other; utilisation = drawn / limit; customer type from portfolio or nearest spelling; status vs DPD |
| kept (warning) | field blanked | negative amounts, unparseable dates, tenure 0, missing obligations |

Quarantined rows are in `ds.quarantined[table]` with an `issue` column.

## Score (0-100, higher = riskier)

1. Signals from `config/risk_signal_definitions.json`. Each signal goes from strength 0 at its trigger to 1 at its saturation. Signals without enough data are "not evaluated"; signals that don't fit the customer are "not applicable", e.g. utilisation with no revolving facility.
2. Pillar score (Repayment, Cash flow, Exposure) = weighted strength of the evaluated signals in that pillar, 0-100.
3. Score = highest pillar + 0.35 × second + 0.15 × third. Each signal's `points` is its share of this, so the points add up to the score.
4. Modifiers (`result.modifiers`):
   - Temporary-miss dampener: one late month in 6, clean before, recovered after → repayment signals ×0.25 with evidence, ×0.6 without.
   - Roll-forward: latest instalment unpaid after ≥2 late payments with non-decreasing delays → score ≥ 75.
   - Recent episode: ≥3 late months in 6 with a delay of ≥10 days → score ≥ 25.
5. Confidence = share of applicable signal weight evaluated. If there are fewer than 4 repayment months or confidence is below 0.5, the status is "Insufficient data" with no score or band.

Bands: Low 0-24 (Routine), Medium 25-49 (Watch), High 50-74 (Investigate), Critical 75-100 (Escalate).
Region-specific settings (calendar, holiday exceptions, scoring factors, rule thresholds) are in `config/profiles/*.json`.

## Results on the clean sample (ground truth used only in tests)

| Scenario | Low | Medium | High | Critical | Insufficient |
|---|---|---|---|---|---|
| Healthy (123) | 122 | 1 | | | |
| Volatile but stable (12) | 11 | 1 | | | |
| Temporary missed payment (21) | 21 | | | | |
| Transaction gap, otherwise healthy (11) | 11 | | | | |
| Thin / missing history (18) | | | | | 18 |
| Repeated delays (21) | | 6 | 6 | 9 | |
| Declining cash flow (18) | 2 | 9 | 6 | 1 | |
| Increasing exposure (18) | 1 | 4 | 11 | 2 | |
| Early delinquency, recovering (9) | | 9 | | | |
| Early delinquency, worsening (12) | | | | 12 | |
| SME stress (15) | | | 3 | 12 | |
| Cluster: textiles, Tamil Nadu (14) | | | 3 | 11 | |
| Cluster: gig workers, Karnataka (8) | 1 | 3 | 4 | | |

Clusters detected: Textiles|Tamil Nadu (lift 2.2) and Gig Economy|Karnataka (lift 2.2), both from industry x region grouping.
