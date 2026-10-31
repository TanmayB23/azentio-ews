# Synthetic EWS data (as-of 2026-10-31, seed 42)

- `clean/` : valid data. Ingest these. Also available as one Excel workbook and one JSON.
- `dirty/` : same data with injected defects; `data_issues_manifest.csv` lists every defect.
- `ground_truth.csv` : planted scenario per customer. Use only for testing, never as a feature.
- `clean/risk_signal_definitions.*` : starter thresholds/weights. Score is 0-100, higher = riskier.

## Scenario counts

| scenario | customers |
|---|---|
| S0_healthy | 123 |
| S0_volatile_but_stable | 12 |
| S1_repeated_repayment_delays | 21 |
| S2_declining_income_cashflow | 18 |
| S3_increasing_exposure | 18 |
| S4_temporary_missed_payment | 21 |
| S5_early_delinquency_recovering | 9 |
| S5_early_delinquency_worsening | 12 |
| S6_sme_financial_stress | 15 |
| S7_thin_or_missing_history | 18 |
| S7_transaction_gap_otherwise_healthy | 11 |
| S8_cluster_gig_workers_karnataka | 8 |
| S8_cluster_textiles_tamil_nadu | 14 |
