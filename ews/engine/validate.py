"""Validates raw text tables and links them together.

Each problem is handled one of three ways:
  quarantined - the row is unusable (bad key, orphan, duplicate) and is moved out
  repaired    - the value can be derived from other fields; the fix is recorded
  kept        - the row is kept, the bad field is blanked, a warning is recorded
"""
from __future__ import annotations

import difflib

import numpy as np
import pandas as pd

from ews.contracts import OPTIONAL_TABLES, TABLES, Dataset, ValidationIssue

REQUIRED = {
    "customers": ["customer_id", "customer_type", "employment_or_business_category", "industry", "region",
                  "portfolio_classification", "segment", "declared_monthly_income", "onboarding_date"],
    "facilities": ["loan_id", "customer_id", "product_type", "facility_type", "sanctioned_amount", "credit_limit",
                   "outstanding_balance", "tenure_months", "instalment_amount", "repayment_frequency",
                   "disbursement_date"],
    "repayments": ["repayment_id", "loan_id", "customer_id", "due_date", "payment_date", "amount_due",
                   "amount_paid", "dpd", "repayment_status", "exception_reason", "exception_evidence_available"],
    "delinquency": ["loan_id", "customer_id", "current_dpd", "overdue_balance", "delinquency_bucket",
                    "max_dpd_12m", "late_instalments_12m", "ever_late_flag", "ever_30plus_flag"],
    "exposure": ["customer_id", "month", "num_active_facilities", "total_outstanding", "total_credit_limit",
                 "revolving_drawn", "utilisation_pct", "monthly_obligations", "external_bureau_obligations",
                 "new_credit_inquiries_90d"],
    "transactions": ["customer_id", "month", "income_receipts", "other_inflows", "total_inflows",
                     "total_outflows", "avg_balance", "closing_balance", "min_balance", "inflow_txn_count",
                     "bounced_txns"],
    "sme_indicators": ["customer_id", "month", "tax_reported_turnover", "tax_filing_status", "receivable_days",
                       "payable_days"],
}
NUMERIC = {
    "customers": ["declared_monthly_income"],
    "facilities": ["sanctioned_amount", "credit_limit", "outstanding_balance", "interest_rate_pct", "profit_rate_pct",
                   "tenure_months", "instalment_amount", "due_day"],
    "repayments": ["installment_no", "amount_due", "amount_paid", "dpd"],
    "delinquency": ["current_dpd", "overdue_balance", "max_dpd_12m", "late_instalments_12m",
                    "instalments_30plus_dpd_12m", "partial_payments_12m"],
    "exposure": ["num_active_facilities", "total_outstanding", "total_credit_limit", "revolving_drawn",
                 "utilisation_pct", "monthly_obligations", "external_bureau_obligations", "new_credit_inquiries_90d"],
    "transactions": ["income_receipts", "other_inflows", "total_inflows", "total_outflows", "avg_balance",
                     "closing_balance", "min_balance", "inflow_txn_count", "bounced_txns"],
    "sme_indicators": ["tax_reported_turnover", "receivable_days", "payable_days"],
}
NON_NEGATIVE = {
    "facilities": ["sanctioned_amount", "credit_limit", "outstanding_balance", "instalment_amount"],
    "repayments": ["amount_due", "amount_paid", "dpd"],
    "delinquency": ["current_dpd", "overdue_balance"],
    "exposure": ["total_outstanding", "monthly_obligations", "external_bureau_obligations", "new_credit_inquiries_90d"],
    "transactions": ["income_receipts", "other_inflows", "total_outflows", "inflow_txn_count", "bounced_txns"],
    "sme_indicators": ["tax_reported_turnover", "receivable_days", "payable_days"],
}
CUSTOMER_TYPES = ["Individual", "SME"]
PORTFOLIO_TO_TYPE = {"Retail Banking": "Individual", "SME Banking": "SME"}
FACILITY_TYPES = ["Term Loan", "Revolving"]
REPAYMENT_STATUSES = ["Paid On Time", "Paid Late", "Partially Paid", "Overdue", "Missed"]
TAX_FILING_STATUSES = ["Filed On Time", "Filed Late", "Not Filed"]


class _Log:
    def __init__(self):
        self.issues: list[ValidationIssue] = []
        self.quarantined: dict[str, list[pd.DataFrame]] = {}

    def add(self, table, key, field, issue, severity="warning", action="kept"):
        self.issues.append(ValidationIssue(table, str(key), field, issue, severity, action))

    def quarantine(self, table, df, mask, keys, issue, field=None):
        if not mask.any():
            return df
        bad = df[mask].copy()
        bad["issue"] = issue
        self.quarantined.setdefault(table, []).append(bad)
        for k in keys[mask]:
            self.add(table, k, field, issue, "error", "quarantined")
        return df[~mask].copy()


def validate(raw: dict[str, pd.DataFrame]) -> Dataset:
    log = _Log()
    t: dict[str, pd.DataFrame] = {}
    for name in TABLES:
        df = raw.get(name)
        if df is None:
            if name not in OPTIONAL_TABLES:
                log.add(name, "*", None, f"table '{name}' not provided", "error", "kept")
            df = pd.DataFrame(columns=REQUIRED[name])
        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]
        for col in REQUIRED[name]:
            if col not in df.columns:
                log.add(name, "*", col, f"missing column '{col}'", "error", "kept")
                df[col] = None
        for col in df.columns:
            if df[col].dtype == object:
                df[col] = df[col].map(lambda v: v.strip() if isinstance(v, str) else v).replace({"": None})
        t[name] = df

    t["customers"] = _customers(t["customers"], log)
    cust_ids = set(t["customers"]["customer_id"])
    t["facilities"] = _facilities(t["facilities"], cust_ids, log)
    loans = t["facilities"].set_index("loan_id")["customer_id"].to_dict()
    t["repayments"] = _repayments(t["repayments"], loans, log)
    t["delinquency"] = _delinquency(t["delinquency"], loans, log)
    t["exposure"] = _monthly(t["exposure"], "exposure", cust_ids, log)
    t["transactions"] = _monthly(t["transactions"], "transactions", cust_ids, log)
    t["sme_indicators"] = _monthly(t["sme_indicators"], "sme_indicators", cust_ids, log)
    bad = t["sme_indicators"]["tax_filing_status"].notna() &         ~t["sme_indicators"]["tax_filing_status"].isin(TAX_FILING_STATUSES)
    for k in (t["sme_indicators"]["customer_id"] + "|" + t["sme_indicators"]["month"])[bad]:
        log.add("sme_indicators", k, "tax_filing_status", "invalid tax_filing_status")
    _exposure_checks(t["exposure"], log)
    _transaction_checks(t["transactions"], log)

    quarantined = {k: pd.concat(v, ignore_index=True) for k, v in log.quarantined.items()}
    return Dataset(tables={k: v.reset_index(drop=True) for k, v in t.items()}, issues=log.issues,
                   quarantined=quarantined)


# --------------------------------------------------------------------------- #
def _to_numeric(df, table, key, log):
    for col in NUMERIC.get(table, []):
        if col not in df.columns:
            continue
        num = pd.to_numeric(df[col], errors="coerce")
        text = df[col].astype("string")
        separated = df[col].notna() & num.isna() & text.str.fullmatch(r"-?[\d,]+(\.\d+)?").fillna(False)
        if separated.any():
            num[separated] = pd.to_numeric(text[separated].str.replace(",", ""), errors="coerce")
            for k in key[separated]:
                log.add(table, k, col, f"{col} with thousands separators; parsed as a number", action="repaired")
        bad = df[col].notna() & num.isna()
        for k in key[bad]:
            log.add(table, k, col, f"non-numeric {col}")
        df[col] = num
    for col in NON_NEGATIVE.get(table, []):
        neg = df[col] < 0
        for k in key[neg]:
            log.add(table, k, col, f"negative {col}")
        df.loc[neg, col] = np.nan
    return df


def _to_date(df, col, table, key, log, required=False):
    parsed = pd.to_datetime(df[col], errors="coerce", format="%Y-%m-%d")
    bad = df[col].notna() & parsed.isna()
    if not required:
        for k in key[bad]:
            log.add(table, k, col, f"invalid {col}" if col != "payment_date" else "unparseable payment_date")
    df[col] = parsed
    return df, bad


def _dedupe(df, table, key, log, issue):
    dup = key.duplicated(keep="first")
    return log.quarantine(table, df, dup, key, issue)


def _require_key(df, table, cols, log):
    missing = df[cols].isna().any(axis=1)
    keys = df[cols].astype(str).agg("|".join, axis=1)
    return log.quarantine(table, df, missing, keys, f"missing key field(s) {', '.join(cols)}")


# --------------------------------------------------------------------------- #
def _customers(df, log):
    df = _require_key(df, "customers", ["customer_id"], log)
    df = _dedupe(df, "customers", df["customer_id"], log, "duplicate customer row")
    key = df["customer_id"]
    df = _to_numeric(df, "customers", key, log)
    df, _ = _to_date(df, "onboarding_date", "customers", key, log)

    types = df["customer_type"].copy()
    for idx in df.index:
        val = types[idx]
        if val in CUSTOMER_TYPES:
            continue
        exact = {c.lower(): c for c in CUSTOMER_TYPES}.get(str(val).lower()) if val is not None else None
        if exact:
            types[idx] = exact
            log.add("customers", key[idx], "customer_type", f"customer_type '{val}' in wrong case; set to '{exact}'",
                    action="repaired")
            continue
        inferred = PORTFOLIO_TO_TYPE.get(df.at[idx, "portfolio_classification"])
        if val is None or pd.isna(val):
            issue = "missing customer_type"
        else:
            issue = f"invalid customer_type value '{val}'"
            close = difflib.get_close_matches(str(val), CUSTOMER_TYPES, n=1, cutoff=0.75)
            inferred = close[0] if close else inferred
        if inferred:
            types[idx] = inferred
            log.add("customers", key[idx], "customer_type", f"{issue}; set to '{inferred}'", action="repaired")
        else:
            types[idx] = None
            log.add("customers", key[idx], "customer_type", issue)
    df["customer_type"] = types
    for k in key[df["employment_or_business_category"].isna()]:
        log.add("customers", k, "employment_or_business_category", "missing employment_or_business_category")
    return df


def _facilities(df, cust_ids, log):
    df = _require_key(df, "facilities", ["loan_id", "customer_id"], log)
    df = _dedupe(df, "facilities", df["loan_id"], log, "duplicate loan_id")
    orphan = ~df["customer_id"].isin(cust_ids)
    df = log.quarantine("facilities", df, orphan, df["loan_id"],
                        "orphan facility: customer_id does not exist", "customer_id")
    key = df["loan_id"]
    df = _to_numeric(df, "facilities", key, log)
    for col in ("disbursement_date", "first_due_date", "maturity_date"):
        if col in df.columns:
            df, _ = _to_date(df, col, "facilities", key, log)

    bad_tenure = df["tenure_months"] <= 0
    for k in key[bad_tenure]:
        log.add("facilities", k, "tenure_months", "tenure_months = 0 (must be positive)")
    df.loc[bad_tenure, "tenure_months"] = np.nan

    term = df["facility_type"] == "Term Loan"
    over = term & (df["outstanding_balance"] > df["sanctioned_amount"])
    for k in key[over]:
        log.add("facilities", k, "outstanding_balance", "outstanding_balance exceeds sanctioned_amount")
    bad_type = ~df["facility_type"].isin(FACILITY_TYPES)
    for k in key[bad_type]:
        log.add("facilities", k, "facility_type", "invalid facility_type")
    return df


def _repayments(df, loans, log):
    df = _require_key(df, "repayments", ["repayment_id", "loan_id"], log)
    df = _dedupe(df, "repayments", df["repayment_id"], log, "duplicate repayment_id")
    orphan = ~df["loan_id"].isin(loans)
    df = log.quarantine("repayments", df, orphan, df["repayment_id"],
                        "orphan repayment: loan_id does not exist", "loan_id")
    key = df["repayment_id"]

    df, bad_due = _to_date(df, "due_date", "repayments", key, log, required=True)
    df = log.quarantine("repayments", df, bad_due | df["due_date"].isna(), key, "invalid due_date", "due_date")
    key = df["repayment_id"]
    df = _to_numeric(df, "repayments", key, log)
    df, _ = _to_date(df, "payment_date", "repayments", key, log)

    owner = df["loan_id"].map(loans)
    mismatch = df["customer_id"].notna() & (df["customer_id"] != owner)
    for k in key[mismatch]:
        log.add("repayments", k, "customer_id", "customer_id does not match facility owner; using facility owner",
                action="repaired")
    df["customer_id"] = owner

    # DPD from dates when it is missing
    derived = (df["payment_date"] - df["due_date"]).dt.days.clip(lower=0)
    fill = df["dpd"].isna() & derived.notna()
    for k in key[fill]:
        log.add("repayments", k, "dpd", "missing dpd; derived from dates", action="repaired")
    df.loc[fill, "dpd"] = derived[fill]

    status = df["repayment_status"]
    bad_status = ~status.isin(REPAYMENT_STATUSES)
    for k in key[bad_status & status.notna()]:
        log.add("repayments", k, "repayment_status", "invalid repayment_status")
    on_time_late = (status == "Paid On Time") & (df["dpd"] > 0)
    late_on_time = (status == "Paid Late") & (df["dpd"] == 0)
    for k in key[on_time_late]:
        log.add("repayments", k, "repayment_status", "status 'Paid On Time' inconsistent with dpd; set to 'Paid Late'",
                action="repaired")
    for k in key[late_on_time]:
        log.add("repayments", k, "repayment_status", "status 'Paid Late' inconsistent with dpd 0; set to 'Paid On Time'",
                action="repaired")
    df.loc[on_time_late, "repayment_status"] = "Paid Late"
    df.loc[late_on_time, "repayment_status"] = "Paid On Time"

    ev = df["exception_evidence_available"]
    df["exception_evidence_available"] = ev.where(ev.isin(["Y", "N"]), None)
    return df


def _delinquency(df, loans, log):
    df = _require_key(df, "delinquency", ["loan_id"], log)
    df = _dedupe(df, "delinquency", df["loan_id"], log, "duplicate delinquency row")
    orphan = ~df["loan_id"].isin(loans)
    df = log.quarantine("delinquency", df, orphan, df["loan_id"],
                        "orphan delinquency: loan_id does not exist", "loan_id")
    df = _to_numeric(df, "delinquency", df["loan_id"], log)
    df["customer_id"] = df["loan_id"].map(loans)
    return df


def _monthly(df, table, cust_ids, log):
    df = _require_key(df, table, ["customer_id", "month"], log)
    keys = df["customer_id"] + "|" + df["month"]
    period = pd.to_datetime(df["month"], format="%Y-%m", errors="coerce")
    df = log.quarantine(table, df, period.isna(), keys, "invalid month", "month")
    keys = df["customer_id"] + "|" + df["month"]
    orphan = ~df["customer_id"].isin(cust_ids)
    df = log.quarantine(table, df, orphan, keys, f"orphan {table[:-1] if table.endswith('s') else table}: "
                                                 "customer_id does not exist", "customer_id")
    keys = df["customer_id"] + "|" + df["month"]
    df = _dedupe(df, table, keys, log, "duplicate customer-month record")
    keys = df["customer_id"] + "|" + df["month"]
    df = _to_numeric(df, table, keys, log)
    return df.sort_values(["customer_id", "month"])


def _exposure_checks(df, log):
    keys = df["customer_id"] + "|" + df["month"]
    bad = (df["utilisation_pct"] < 0) | (df["utilisation_pct"] > 100)
    recomputed = 100 * df["revolving_drawn"] / df["total_credit_limit"]
    for idx in df.index[bad]:
        new = recomputed[idx]
        old = df.at[idx, "utilisation_pct"]
        if pd.notna(new) and 0 <= new <= 100:
            df.at[idx, "utilisation_pct"] = round(new, 1)
            log.add("exposure", keys[idx], "utilisation_pct",
                    f"utilisation_pct = {old:g} (outside 0-100); recomputed as {new:.1f} from drawn/limit",
                    action="repaired")
        else:
            df.at[idx, "utilisation_pct"] = np.nan
            log.add("exposure", keys[idx], "utilisation_pct", f"utilisation_pct = {old:g} (outside 0-100)")
    for k in keys[df["monthly_obligations"].isna()]:
        log.add("exposure", k, "monthly_obligations", "missing monthly_obligations")


def _transaction_checks(df, log):
    keys = df["customer_id"] + "|" + df["month"]
    parts = df["income_receipts"] + df["other_inflows"]
    neg = df["total_inflows"] < 0
    missing = df["total_inflows"].isna()
    for idx in df.index[neg | missing]:
        issue = "negative total_inflows" if neg[idx] else "missing total_inflows"
        if pd.notna(parts[idx]):
            df.at[idx, "total_inflows"] = parts[idx]
            log.add("transactions", keys[idx], "total_inflows",
                    f"{issue}; recomputed as income_receipts + other_inflows", action="repaired")
        else:
            df.at[idx, "total_inflows"] = np.nan
            log.add("transactions", keys[idx], "total_inflows", issue)
    off = (df["total_inflows"] - parts).abs() > np.maximum(2, 0.01 * parts.abs())
    for k in keys[off & ~(neg | missing)]:
        log.add("transactions", k, "total_inflows", "total_inflows does not equal income_receipts + other_inflows")
