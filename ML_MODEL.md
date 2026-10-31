# Three-month serious-delinquency forecast

The customer screen pairs the existing deterministic rule assessment with a separate XGBoost gradient-boosted-tree estimate of reaching **30 or more DPD within the next three calendar months**. It uses the same fifteen rule-signal metric functions as numeric features. It never modifies the rule score, its band, confidence, saved alert or analyst reviews.

**Synthetic-data prototype: the method is ready for real data, not evidence of predictive accuracy.** The model can learn the generator's deliberately planted patterns. The shipped holdout contains very few positive outcomes; its diagnostics are not a claim of real-world forecasting performance.

## Run and retrain

Install the updated backend requirements and build the existing web application:

```powershell
./.venv/Scripts/python -m pip install -r requirements.txt
npm --prefix web ci
npm --prefix web run build
./.venv/Scripts/python -m api
```

A trained synthetic model is included under `models/delinquency_3m/`, so normal application startup does not train or require an external service. Open a saved assessment and then a customer's screen. No API key is required.

Reproduce training explicitly from the repository root:

```powershell
./.venv/Scripts/python -m ews.ml.train
```

This reads the generated clean India and GCC tables, builds six mature monthly forecast origins ending three months before their observation cutoff, and writes a versioned native XGBoost model, metadata and a `current.json` pointer. Intermediate training rows are written to ignored `var/ml/training_rows.csv`. Ground-truth files, names, customer IDs, scenario labels, review decisions and the final rule score are never feature columns. Identifiers are used only to join/split records.

`EWS_ML_MODEL_DIR` can select another server-controlled model directory. Missing, incompatible or checksum-invalid model artifacts produce Forecast unavailable; the rest of the app remains usable. Custom signal windows/measurement definitions require a compatible retrained model. Changes only to rule thresholds/weights do not change the raw feature measurement definition.

## Exact target and eligible population

A forecast origin is a month-end; mid-month forecasts are suppressed because complete monthly aggregates would not yet be available. The horizon ends three calendar months later using a calendar date offset (with day-of-month clipping for shorter months), for example 2026-07-31 through 2026-10-31, or 2026-10-31 through 2027-01-31.

For an instalment due on D, a recorded payment-delay episode first reaches 30 DPD on **D + 30 days** if the payment is still outstanding then. A recorded payment on day 30 counts; day 29 does not. The threshold is >=30, not >30 and not the engine's supplied ever_30plus flag.

A positive target means such a threshold crossing occurs strictly after the origin and on/before the horizon end. Previously due instalments can cross during that future interval. Positive evidence comes from a recorded payment on/after the crossing date, or an explicitly Overdue/Missed record still unpaid at the observation cutoff.

A negative label requires the entire three-month horizon to be observed, future scheduled repayment months present, and no proven crossing. Incomplete follow-up, missing scheduled months, invalid payment outcomes, and ambiguous partial-payment crossings without positive proof are censored, not labelled healthy. A partial receipt does not establish when the remaining balance was fully settled.

The model population requires at least four observed repayment months, at least 50% applicable signal-weight coverage, and current DPD below 30. At inference, existing Insufficient data rule results also suppress a numerical forecast. Customers already at 30+ DPD show **Already 30+ DPD**, not a fabricated 100% incident probability. The current rule assessment stays visible.

Labels use the recorded repayment history, not a full balance-level collections ledger. Real deployment requires reliable settlement/partial-payment histories and explicit outcome completeness.

## Preventing future leakage

`ews/ml/features.py` reconstructs an as-of dataset for every origin:

1. Remove future monthly transactions/exposure/SME records, future disbursements and customers not yet onboarded.
2. Hide payment dates, amounts, eventual statuses and exception evidence that were not known by the origin.
3. Recompute paid/unpaid DPD at that date and rebuild current delinquency instead of using the final delinquency snapshot.
4. Use the existing rule metric functions on that reconstructed history. Only applicable, evaluated signal values are features; unavailable values remain missing for XGBoost to handle.
5. Keep future repayment outcomes exclusively in the label builder.

The feature builder and inference use the same versioned path. The fifteen feature names/order and measurement/calendar signatures are checked against the saved model. No score, future band, generator scenario, customer ID or future observation is a predictor.

The synthetic monthly aggregates are assumed available at month-end; real data needs trustworthy availability timestamps. Customer type and facility properties are assumed stable where no effective-dated history is supplied. This is a reproducible point-in-time reconstruction under those assumptions, not a substitute for a real historical feature store.

## Training, calibration and evaluation

Default XGBoost settings are fixed in `ews/ml/train.py`: binary logistic objective, depth 3, 100 boosting rounds, learning rate .05, minimum child weight 5, L2 regularisation 5, L1 regularisation .1, seed 42, and two CPU threads. There is no class reweighting or holdout-driven hyperparameter tuning.

The synthetic histories contain recorded 30+ DPD crossings mainly in September/October 2026. A three-month purged chronological train/calibration/test split would have insufficient earlier positive outcomes. The default **customer-demo** split therefore uses disjoint customer groups across all three sets, stratified by whether a group has any eligible positive label. All rows for one profile/customer stay in one split. This is a same-period held-customer demonstration, **not an out-of-time backtest**.

The initial artifact has 3,309 training rows/560 customers/12 positive rows; 817 calibration rows/140 customers/2 positives; and 1,046 held-out rows/176 customers/2 positives. These are customer-month rows, so repeated outcomes can be correlated. Exact counts and metrics are in the artifact metadata.

A constrained non-negative-slope sigmoid is fitted to native model margins using only the separate calibration customers. The sigmoid maps raw log-odds to a probability estimate. With so few positives, calibration remains highly uncertain and must not be described as validated real-world calibration.

Held-out diagnostics include ROC AUC, average precision, Brier loss, log loss, calibration bins and a constant training-prevalence Brier baseline. Low Brier loss can largely reflect rare events. The shipped model does not outperform that constant baseline on Brier loss; this is intentionally reported, not hidden or presented as a success metric.

For suitable longer histories:

```powershell
./.venv/Scripts/python -m ews.ml.train --data-root path/to/portfolios --origins 24 --split temporal
```

This mode purges training labels that reach the calibration period and calibration labels that reach the test period. It refuses to train when any partition lacks both classes. It does not silently substitute a random split. The currently bundled data cannot support that stricter backtest. The CLI is currently a synthetic-demo trainer; adapting it to real observation cutoffs and data governance is a separate validation step, not automatic production approval.

## Factors that drove a forecast

XGBoost's native exact TreeSHAP contributions explain the raw model margin. For sigmoid calibration with slope a and intercept b:

```text
calibrated log-odds = a * raw margin + b
reference log-odds = a * native SHAP bias + b
factor_i = a * native SHAP contribution_i
probability = sigmoid(reference log-odds + sum(all 15 factors))
```

The API checks that this reconciles numerically. Factors raise/lower the estimate relative to the model reference, in **log-odds**, not percentage points, rule points, causal effects or global feature importance. Missing/non-applicable feature routing can also affect a learned model; it is labelled in the factor list. The customer card initially shows the leading factors and allows expansion.

## Saved forecasts and API

Forecasts are stored in a separate append-only `ml_predictions` table keyed by original alert, model ID and input fingerprint. Repeated requests reuse the saved forecast. New model versions create new records; earlier forecasts and original rule evidence remain unchanged. SQL triggers block prediction updates/deletions. The existing evidence schema and scoring contract are unchanged.

- `GET /api/ml/model`: availability and synthetic-training metadata.
- `GET /api/runs/{run_id}/customers/{customer_id}/ml`: forecast/status and factor attribution.
- `GET /api/runs/{run_id}/customers/{customer_id}/ml/history`: saved forecast versions.

Training is an offline CLI operation; no public training endpoint or startup retraining is added. Models use XGBoost's native UBJ format with checksums, not arbitrary Python pickle objects. Keep the model directory under server/deployment control.

## Verification

```powershell
./.venv/Scripts/python -m pytest -q
npm --prefix web run build
```

ML tests cover future-value invariance, censoring eventual payment outcomes, exact 30-day boundaries, incomplete labels, empty history, disjoint customer splits, purged temporal horizons, probabilities, exact contribution reconciliation, model availability/schema/checksum cases, append-only forecasts, new-model versions, API errors and preservation of original alerts.

## Demo wording

'The rule score measures today's monitoring signals. Alongside it, a gradient-boosting model estimates the chance of a new recorded 30-plus-DPD event over the next three months, using the same signal measurements reconstructed at each historical month-end. Its factors show which measurements raised or lowered the model estimate. This is trained on synthetic data and may learn the generator's patterns. We are demonstrating the method, ready to be validated on real historical data, not claiming predictive accuracy.'

## Technical references

- [XGBoost prediction and native feature contributions](https://xgboost.readthedocs.io/en/stable/prediction.html).
- [Time-ordered evaluation and gaps](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html).
- [Probability calibration and proper scoring diagnostics](https://scikit-learn.org/stable/modules/calibration.html).
