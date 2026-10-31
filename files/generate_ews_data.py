#!/usr/bin/env python3
"""
Synthetic data generator for the Early Warning System (EWS) hackathon problem.

Every customer is generated from a *planted scenario* (repeated delays, temporary
missed payment, declining cash flow, ...), so you get ground truth to test your
detection and scoring against. Nothing here is random noise on top of random noise:
each archetype has a deliberate, time-based pattern.

Usage:
    python generate_ews_data.py --customers 300 --seed 42 --as-of 2026-10-31 --out ./synthetic_data

Outputs (in --out):
    clean/   customers, facilities, repayments, delinquency, exposure, transactions (CSV)
             + early_warning_data.xlsx (one sheet per table) + portfolio.json
             + risk_signal_definitions.json / .csv
    dirty/   same tables with injected data-quality defects + data_issues_manifest.csv
    ground_truth.csv   planted scenario per customer (DO NOT ingest into the app)
    README.md
"""
import argparse
import json
import math
import os
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

# --------------------------------------------------------------------------- #
# Reference data
# --------------------------------------------------------------------------- #
FIRST = ["Aarav", "Priya", "Rohan", "Ananya", "Karthik", "Meera", "Imran", "Sneha", "Arjun", "Divya",
         "Vikram", "Neha", "Suresh", "Lakshmi", "Farhan", "Pooja", "Manoj", "Kavya", "Rajesh", "Isha"]
LAST = ["Sharma", "Iyer", "Reddy", "Nair", "Khan", "Patel", "Gupta", "Menon", "Singh", "Das",
        "Kulkarni", "Mehta", "Rao", "Joshi", "Pillai", "Naidu", "Bose", "Chawla", "Shetty", "Verma"]
REGIONS = ["Karnataka", "Tamil Nadu", "Maharashtra", "Gujarat", "Delhi NCR", "Telangana",
           "West Bengal", "Kerala", "Uttar Pradesh"]
SME_INDUSTRIES = ["Textiles", "Retail & Trading", "Manufacturing", "Food & Beverage", "IT Services",
                  "Logistics & Transport", "Construction", "Agri-processing"]
IND_CATS = {
    "Salaried - Private": ["IT / Software", "Banking & Finance", "Healthcare", "Manufacturing", "Retail"],
    "Salaried - Government": ["Public Sector", "Education"],
    "Self-employed Professional": ["Healthcare", "Legal & Consulting", "Education"],
    "Gig / Platform Worker": ["Gig Economy"],
}
RMS = ["Anita Rao", "Vikram Shah", "Meera Pillai", "Rahul Verma", "Sana Qureshi", "Karthik Iyer"]

PRODUCTS = {
    "Personal Loan": dict(rev=False, tenures=[24, 36, 48, 60], rate=(12, 18)),
    "Auto Loan": dict(rev=False, tenures=[36, 48, 60, 84], rate=(9, 12)),
    "Home Loan": dict(rev=False, tenures=[120, 180, 240], rate=(8.5, 9.5)),
    "Business Term Loan": dict(rev=False, tenures=[24, 36, 60, 84], rate=(11, 15)),
    "Credit Card": dict(rev=True, rate=(36, 42)),
    "Working Capital Limit": dict(rev=True, rate=(10, 14)),
}

# (reason, evidence_available, delay_range_days)
TEMP_OPTS_IND = [
    ("Bank holiday on due date", True, (1, 3)),
    ("NACH/UPI processing delay", True, (2, 5)),
    ("Salary credit delayed by employer", True, (8, 20)),
    ("Customer-reported, no supporting document", False, (6, 15)),
    (None, False, (8, 25)), (None, False, (8, 25)),
]
TEMP_OPTS_SME = [
    ("Bank holiday on due date", True, (1, 3)),
    ("NACH/UPI processing delay", True, (2, 5)),
    ("Large receivable delayed by buyer", True, (8, 20)),
    ("Owner-reported, no supporting document", False, (6, 15)),
    (None, False, (8, 25)), (None, False, (8, 25)),
]
GLITCH_REASONS = {"Salary credit delayed by employer", "Large receivable delayed by buyer"}
ALL_FACILITIES_BEHAVE = {"repeated_delay", "early_delinq_worsening", "early_delinq_recovering"}


# --------------------------------------------------------------------------- #
# Date helpers.  Month index 0..11 where 11 == month of --as-of
# --------------------------------------------------------------------------- #
def add_months(d, k):
    y = d.year + (d.month - 1 + k) // 12
    m = (d.month - 1 + k) % 12 + 1
    return date(y, m, min(d.day, 28))


def month_anchor(as_of, i):
    return add_months(date(as_of.year, as_of.month, 1), i - 11)


def month_label(as_of, i):
    d = month_anchor(as_of, i)
    return f"{d.year}-{d.month:02d}"


def due_date(as_of, i, day):
    d = month_anchor(as_of, i)
    return date(d.year, d.month, day)


# --------------------------------------------------------------------------- #
# Facility model
# --------------------------------------------------------------------------- #
@dataclass
class Facility:
    loan_id: str
    customer_id: str
    product: str
    revolving: bool
    emi: int
    rate: float
    tenure: int
    sanctioned: int
    limit: int
    disb_idx: int
    due_day: int
    util: list = field(default_factory=list)
    util_base: float = 0.0
    is_new: bool = False
    primary: bool = False

    def balance(self, i):
        if i < self.disb_idx:
            return 0
        if self.revolving:
            return int(self.limit * self.util[i])
        k = i - self.disb_idx
        r = self.rate / 1200
        bal = self.sanctioned * (1 + r) ** k - self.emi * (((1 + r) ** k - 1) / r)
        return max(0, int(bal))

    def due_amount(self, i):
        if not self.revolving:
            return self.emi
        return max(500, int(round(self.emi * self.util[i] / max(self.util_base, 0.05), -2)))


def make_util(base, ramp_from, target, rng):
    path = []
    for i in range(12):
        if ramp_from is not None and i >= ramp_from:
            frac = (i - ramp_from + 1) / (12 - ramp_from)
            v = base + (target - base) * frac + rng.gauss(0, 0.015)
        else:
            v = base + rng.gauss(0, 0.02)
        path.append(min(0.99, max(0.03, v)))
    return path


def make_term(cid, prod, emi, disb_idx, rng, ctr, primary=False, is_new=False):
    spec = PRODUCTS[prod]
    n = rng.choice(spec["tenures"])
    rate = round(rng.uniform(*spec["rate"]), 2)
    r = rate / 1200
    emi = max(1500, int(round(emi, -2)))
    principal = int(round(emi * (1 - (1 + r) ** -n) / r, -3))
    if disb_idx is None:
        cap = max(1, min(n - 13, 40))
        disb_idx = -rng.randint(1, cap)
    ctr["L"] += 1
    return Facility(f"L{ctr['L']:05d}", cid, prod, False, emi, rate, n, principal, 0,
                    disb_idx, rng.randint(1, 28), primary=primary, is_new=is_new)


def make_rev(cid, prod, inflow0, is_sme, disb_idx, base, ramp_from, target, rng, ctr, is_new=False):
    spec = PRODUCTS[prod]
    limit = int(round(inflow0 * (rng.uniform(1.5, 3.0) if is_sme else rng.uniform(1.5, 3.5)), -3))
    factor = 0.02 if prod == "Working Capital Limit" else 0.05
    emi = max(500, int(round(factor * limit * base, -2)))
    if disb_idx is None:
        disb_idx = -rng.randint(6, 40)
    ctr["L"] += 1
    return Facility(f"L{ctr['L']:05d}", cid, prod, True, emi, round(rng.uniform(*spec["rate"]), 2), 12,
                    limit, limit, disb_idx, rng.randint(1, 28),
                    util=make_util(base, ramp_from, target, rng), util_base=base, is_new=is_new)


# --------------------------------------------------------------------------- #
# Behaviour models
# --------------------------------------------------------------------------- #
def base_delay(rng):
    r = rng.random()
    if r < 0.94:
        return 0
    if r < 0.985:
        return rng.randint(1, 4)
    return rng.randint(5, 7)


def payment_outcome(beh, i, p, rng):
    """Return (delay_days or None if unpaid, paid_fraction, exception_tuple or None)."""
    if beh == "repeated_delay" and i >= p["i0"]:
        j = i - p["i0"]
        if j == 0 or rng.random() < 0.75:
            delay = min(80, int(3 + j * rng.uniform(2, 5) + rng.randint(0, 5)))
            frac = rng.uniform(0.4, 0.8) if rng.random() < 0.3 else 1.0
            return delay, frac, None
        return rng.randint(0, 2), 1.0, None
    if beh == "early_delinq_worsening" and i in p["delays"]:
        frac = 0.6 if (i == 10 and p["partial_10"]) else 1.0
        return p["delays"][i], frac, None
    if beh == "early_delinq_recovering" and i in p["delays"]:
        return p["delays"][i], 1.0, None
    if beh == "temporary_miss":
        if i == p["e"]:
            return p["delay"], 1.0, p["exc"]
        if i == p["e"] + 1:
            return 0, 1.0, None
    if beh == "sme_stress" and i >= 10 and rng.random() < 0.5:
        return rng.randint(2, 7), 1.0, None
    return base_delay(rng), 1.0, None


def delinquency_bucket(dpd):
    if dpd <= 0:
        return "Current"
    if dpd <= 30:
        return "1-30"
    if dpd <= 60:
        return "31-60"
    if dpd <= 90:
        return "61-90"
    return "90+"


# --------------------------------------------------------------------------- #
# Scenario plan
# --------------------------------------------------------------------------- #
# (scenario label, behaviour, share, customer-type rule, expected band)
PLAN = [
    ("S0_volatile_but_stable", "volatile_stable", 0.04, None, "Low (volatility alone is not deterioration)"),
    ("S1_repeated_repayment_delays", "repeated_delay", 0.07, None, "High"),
    ("S4_temporary_missed_payment", "temporary_miss", 0.07, None, "Low to Low-Medium"),
    ("S2_declining_income_cashflow", "declining_cashflow", 0.06, "mixed", "Medium to High"),
    ("S3_increasing_exposure", "increasing_exposure", 0.06, None, "Medium to High"),
    ("S5_early_delinquency_worsening", "early_delinq_worsening", 0.04, None, "High to Critical"),
    ("S5_early_delinquency_recovering", "early_delinq_recovering", 0.03, None, "Low-Medium to Medium"),
    ("S6_sme_financial_stress", "sme_stress", 0.05, "SME", "High"),
    ("S7_thin_or_missing_history", "thin_file", 0.06, None, "Insufficient data (must NOT be High)"),
]
CLUSTERS = [
    ("S8_cluster_textiles_tamil_nadu", "sme_stress", 0.045, "SME",
     dict(industry="Textiles", region="Tamil Nadu"), "Medium to High (cluster of SMEs)"),
    ("S8_cluster_gig_workers_karnataka", "declining_cashflow", 0.025, "Individual",
     dict(category="Gig / Platform Worker", region="Karnataka"), "Medium to High (cluster of gig workers)"),
]


def build_plan(n, rng):
    items = []
    used = 0
    for scen, beh, share, ctype_rule, over_name, over, exp in [(c[0], c[1], c[2], c[3], None, c[4], c[5]) for c in CLUSTERS]:
        k = round(n * share)
        used += k
        items += [(scen, beh, ctype_rule, over, exp)] * k
    for scen, beh, share, ctype_rule, exp in PLAN:
        k = round(n * share)
        used += k
        items += [(scen, beh, ctype_rule, {}, exp)] * k
    items += [("S0_healthy", "healthy", None, {}, "Low")] * max(0, n - used)
    items = items[:n]
    rng.shuffle(items)
    return items


# --------------------------------------------------------------------------- #
# One customer
# --------------------------------------------------------------------------- #
def gen_customer(cid, scen, beh, ctype_rule, over, expected, rng, as_of, ctr, out):
    if ctype_rule == "SME":
        ctype = "SME"
    elif ctype_rule == "Individual":
        ctype = "Individual"
    elif ctype_rule == "mixed":
        ctype = "SME" if rng.random() < 0.5 else "Individual"
    else:
        ctype = "Individual" if rng.random() < 0.65 else "SME"
    is_sme = ctype == "SME"
    thin = beh == "thin_file"
    hist_start = 12 - rng.randint(1, 3) if thin else 0
    facts = []

    # ---- profile ----------------------------------------------------------
    if is_sme:
        inflow0 = float(round(rng.uniform(3e5, 4e6), -4))
        industry = over.get("industry") or rng.choice(SME_INDUSTRIES)
        category = rng.choice(["Proprietorship", "Partnership", "Private Limited"])
        name = f"{rng.choice(LAST)} {industry.split(' ')[0]} {rng.choice(['Enterprises', 'Traders', 'Industries', '& Sons'])}"
        portfolio, segment = "SME Banking", rng.choice(["SME Core", "SME Emerging"])
    else:
        category = over.get("category") or rng.choices(list(IND_CATS), [0.5, 0.2, 0.18, 0.12])[0]
        industry = rng.choice(IND_CATS[category])
        inflow0 = float(round(rng.uniform(25000, 70000) if category.startswith("Gig")
                              else rng.uniform(25000, 220000), -3))
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        portfolio, segment = "Retail Banking", rng.choice(["Prime", "Near Prime"])
    region = over.get("region") or rng.choice(REGIONS)

    # ---- behaviour parameters --------------------------------------------
    p = {}
    if beh == "repeated_delay":
        p["k"] = rng.randint(4, 7)
        p["i0"] = 12 - p["k"]
        facts.append(f"payment deterioration began {p['k']} months ago; delays growing")
    elif beh == "early_delinq_worsening":
        p["delays"] = {8: rng.randint(4, 6), 9: rng.randint(9, 13), 10: rng.randint(16, 22), 11: None}
        p["partial_10"] = rng.random() < 0.5
        facts.append(f"delays {p['delays'][8]}/{p['delays'][9]}/{p['delays'][10]} days then latest instalment unpaid")
    elif beh == "early_delinq_recovering":
        p["delays"] = {8: rng.randint(14, 18), 9: rng.randint(8, 11), 10: rng.randint(3, 5), 11: 0}
        facts.append(f"delays {p['delays'][8]}/{p['delays'][9]}/{p['delays'][10]} days then back on time")
    elif beh == "temporary_miss":
        reason, evid, (lo, hi) = rng.choice(TEMP_OPTS_SME if is_sme else TEMP_OPTS_IND)
        p.update(e=rng.randint(3, 9), delay=rng.randint(lo, hi),
                 exc=(reason, evid) if reason else None, glitch=reason in GLITCH_REASONS)
        expected = "Low" if evid else "Low to Low-Medium"
        facts.append(f"single late payment in {month_label(as_of, p['e'])} ({p['delay']}d), "
                     f"reason={reason}, evidence={evid}; clean before/after")
    elif beh == "thin_file":
        p["no_txn"] = rng.random() < 0.4
        facts.append(f"only {12 - hist_start} month(s) of history; transactions missing={p['no_txn']}")
    elif beh == "healthy" and rng.random() < 0.06:
        p["gap"] = (rng.randint(2, 8), 2)
        scen, expected = "S7_transaction_gap_otherwise_healthy", "Low (reduced confidence)"
        facts.append(f"transaction data missing for months {p['gap'][0]}-{p['gap'][0] + 1}")

    decl = None
    if beh == "declining_cashflow":
        decl = (rng.randint(3, 6),) + ((0.07, 0.13) if is_sme else (0.05, 0.09))
    elif beh == "sme_stress":
        decl = (rng.randint(4, 6), 0.08, 0.14)
    elif beh == "early_delinq_worsening":
        decl = (4, 0.05, 0.09)
    elif beh == "repeated_delay":
        decl = (p["k"], 0.02, 0.04)

    # ---- facilities -------------------------------------------------------
    term_prod = (lambda: "Business Term Loan") if is_sme else \
                (lambda: rng.choices(["Personal Loan", "Auto Loan", "Home Loan"], [0.45, 0.25, 0.30])[0])
    rev_prod = "Working Capital Limit" if is_sme else "Credit Card"
    if beh in ("increasing_exposure", "sme_stress"):
        prods = [term_prod(), rev_prod]
    else:
        nfac = rng.choices([1, 2], [0.5, 0.5])[0] if is_sme else rng.choices([1, 2, 3], [0.5, 0.35, 0.15])[0]
        prods = [term_prod()] + [rng.choice([term_prod(), rev_prod]) for _ in range(nfac - 1)]
    budget = inflow0 * (rng.uniform(0.08, 0.25) if is_sme else rng.uniform(0.15, 0.38))
    facs, n_term = [], 0
    for idx, prod in enumerate(prods):
        if PRODUCTS[prod]["rev"]:
            base = rng.uniform(0.25, 0.5) if is_sme else rng.uniform(0.15, 0.45)
            ramp_from, target = None, None
            if beh == "increasing_exposure":
                base, ramp_from, target = rng.uniform(0.25, 0.4), 4, rng.uniform(0.82, 0.97)
            elif beh == "sme_stress":
                base, ramp_from, target = rng.uniform(0.35, 0.5), 5, rng.uniform(0.80, 0.95)
            disb = hist_start - 1 if thin else None
            facs.append(make_rev(cid, prod, inflow0, is_sme, disb, base, ramp_from, target, rng, ctr))
        else:
            share = 0.6 if n_term == 0 else 0.25
            n_term += 1
            disb = hist_start - 1 if thin else None
            facs.append(make_term(cid, prod, budget * share, disb, rng, ctr))
    facs[0].primary = True
    if beh in ("increasing_exposure", "sme_stress"):
        extras = rng.randint(1, 2) if beh == "increasing_exposure" else (1 if rng.random() < 0.5 else 0)
        for _ in range(extras):
            d_idx = rng.randint(5, 9)
            if rng.random() < 0.6 or not is_sme and rng.random() < 0.5:
                facs.append(make_term(cid, term_prod(), inflow0 * rng.uniform(0.06, 0.12), d_idx, rng, ctr, is_new=True))
            else:
                facs.append(make_rev(cid, rev_prod, inflow0, is_sme, d_idx, 0.2, d_idx + 1,
                                     rng.uniform(0.7, 0.9), rng, ctr, is_new=True))
        facts.append(f"{sum(f.is_new for f in facs)} new facility(ies) in last 6 months; revolving utilisation ramping up")

    # ---- transactions -----------------------------------------------------
    sigma = {"volatile_stable": 0.18, "repeated_delay": 0.04}.get(beh, 0.05 if is_sme else 0.01)
    amp = 0.06 if is_sme else 0.0
    if decl:
        sigma, amp = (0.01 if beh != "repeated_delay" else 0.04), (0.01 if is_sme else 0.0)
    phase = rng.uniform(0, 6.28)
    mult = [(1 + amp * math.sin(2 * math.pi * i / 12 + phase)) * max(0.3, rng.gauss(1, sigma)) for i in range(12)]
    trend = [1.0] * 12
    if decl:
        k, lo, hi = decl
        cur = 1.0
        for i in range(12 - k, 12):
            cur *= 1 - rng.uniform(lo, hi)
            trend[i] = cur
        if beh != "repeated_delay":
            facts.append(f"inflows fell {100 * (1 - trend[11]):.0f}% over the last {k} consecutive months")
    if beh == "early_delinq_recovering":
        trend[7] = trend[8] = 0.78
        trend[9] = 0.9
    inc_pre = [inflow0 * mult[i] * trend[i] for i in range(12)]
    inc = list(inc_pre)
    if beh == "temporary_miss" and p["glitch"]:
        inc[p["e"]] *= 0.3 if is_sme else 0.15
        inc[p["e"] + 1] *= 1.7 if is_sme else 1.85

    out_base = rng.uniform(0.90, 0.99)
    ramp_total = {"sme_stress": 0.16, "early_delinq_worsening": 0.10, "repeated_delay": 0.06,
                  "increasing_exposure": 0.08}.get(beh, 0.0)
    ramp_k = decl[0] if decl else (6 if beh == "increasing_exposure" else 0)
    stress_bounce = {"sme_stress": 0.5, "early_delinq_worsening": 0.5, "repeated_delay": 0.3,
                     "declining_cashflow": 0.15}.get(beh, 0.0)
    base_cnt = rng.randint(40, 110) if is_sme else rng.randint(2, 6)
    bal_prev = inflow0 * rng.uniform(0.8, 1.8)
    txn_rows = []
    for i in range(12):
        in_ramp = ramp_k and i >= 12 - ramp_k
        ratio = out_base + (ramp_total * (i - (12 - ramp_k) + 1) / ramp_k if in_ramp else 0)
        total_in = inc[i] * (1 + rng.uniform(0, 0.1))
        outflow = inc_pre[i] * ratio * rng.gauss(1, 0.03)
        closing = max(bal_prev + total_in - outflow, 0.03 * inflow0)
        bounced = rng.randint(1, 3) if (in_ramp and rng.random() < stress_bounce) else (1 if rng.random() < 0.03 else 0)
        emit = i >= hist_start and not p.get("no_txn") and not (
            "gap" in p and p["gap"][0] <= i < p["gap"][0] + p["gap"][1])
        if emit:
            txn_rows.append({
                "customer_id": cid, "month": month_label(as_of, i),
                "income_receipts": int(inc[i]), "other_inflows": int(total_in - inc[i]),
                "total_inflows": int(total_in), "total_outflows": int(outflow),
                "avg_balance": int((bal_prev + closing) / 2), "closing_balance": int(closing),
                "min_balance": int(min(bal_prev, closing) * rng.uniform(0.6, 0.95)),
                "inflow_txn_count": max(1, round(base_cnt * mult[i] * trend[i])), "bounced_txns": bounced,
            })
        bal_prev = closing
    out["transactions"] += txn_rows

    # ---- repayments + delinquency ----------------------------------------
    for f in facs:
        apply_beh = (not f.is_new) and (f.primary or beh in ALL_FACILITIES_BEHAVE)
        frows = []
        for i in range(max(f.disb_idx + 1, hist_start, 0), 12):
            due = due_date(as_of, i, f.due_day)
            amt_due = f.due_amount(i)
            delay, frac, exc = payment_outcome(beh, i, p, rng) if apply_beh else (base_delay(rng), 1.0, None)
            pay = None if delay is None else due + timedelta(days=delay)
            if pay is None or pay > as_of:
                paid, pay, dpd = 0, None, (as_of - due).days
                status = "Missed" if dpd > 30 else "Overdue"
            else:
                paid, dpd = int(round(amt_due * frac)), delay
                status = "Partially Paid" if frac < 0.999 else ("Paid Late" if delay > 0 else "Paid On Time")
            ctr["R"] += 1
            frows.append({
                "repayment_id": f"R{ctr['R']:06d}", "loan_id": f.loan_id, "customer_id": cid,
                "installment_no": i - f.disb_idx, "due_date": due.isoformat(),
                "payment_date": pay.isoformat() if pay else None,
                "amount_due": amt_due, "amount_paid": paid, "dpd": dpd, "repayment_status": status,
                "exception_reason": exc[0] if exc else None,
                "exception_evidence_available": ("Y" if exc[1] else "N") if exc else None,
            })
        out["repayments"] += frows
        if frows:
            unpaid = [r for r in frows if r["repayment_status"] in ("Overdue", "Missed")]
            cur = max([r["dpd"] for r in unpaid], default=0)
            overdue = sum(r["amount_due"] - r["amount_paid"] for r in unpaid)
            last = frows[-1]
            if last["repayment_status"] == "Partially Paid":
                cur = max(cur, (as_of - date.fromisoformat(last["due_date"])).days)
                overdue += last["amount_due"] - last["amount_paid"]
            dpds = [r["dpd"] for r in frows]
            out["delinquency"].append({
                "loan_id": f.loan_id, "customer_id": cid, "current_dpd": cur, "overdue_balance": overdue,
                "delinquency_bucket": delinquency_bucket(cur), "max_dpd_12m": max(dpds),
                "late_instalments_12m": sum(d > 0 for d in dpds),
                "instalments_30plus_dpd_12m": sum(d > 30 for d in dpds),
                "partial_payments_12m": sum(r["repayment_status"] == "Partially Paid" for r in frows),
                "ever_late_flag": "Y" if max(dpds) > 0 else "N",
                "ever_30plus_flag": "Y" if max(dpds) > 30 else "N",
            })
        disb_date = add_months(date(as_of.year, as_of.month, 1), f.disb_idx - 11).replace(day=f.due_day)
        out["facilities"].append({
            "loan_id": f.loan_id, "customer_id": cid, "product_type": f.product,
            "facility_type": "Revolving" if f.revolving else "Term Loan",
            "sanctioned_amount": f.sanctioned, "credit_limit": f.limit if f.revolving else None,
            "outstanding_balance": f.balance(11), "interest_rate_pct": f.rate, "tenure_months": f.tenure,
            "instalment_amount": f.due_amount(11), "repayment_frequency": "Monthly", "due_day": f.due_day,
            "disbursement_date": disb_date.isoformat(),
            "first_due_date": due_date(as_of, f.disb_idx + 1, f.due_day).isoformat()
            if f.disb_idx + 1 <= 11 else None,
            "maturity_date": add_months(disb_date, f.tenure).isoformat(), "facility_status": "Active",
        })

    # ---- exposure (monthly snapshots) --------------------------------------
    ext_base = inflow0 * rng.uniform(0.03 if beh == "increasing_exposure" else 0.0, 0.1)
    inq_base = rng.choice([0, 0, 1])
    for i in range(max(hist_start, 0), 12):
        active = [f for f in facs if f.disb_idx <= i]
        if not active:
            continue
        rev = [f for f in active if f.revolving]
        limit = sum(f.limit for f in rev)
        drawn = sum(f.balance(i) for f in rev)
        ext = ext_base * (1 + 1.5 * (i - 4) / 7) if (beh == "increasing_exposure" and i >= 5) else ext_base
        inq = inq_base
        if beh == "increasing_exposure" and i >= 6:
            inq = rng.randint(2, 6)
        elif beh == "sme_stress" and i >= 7:
            inq = rng.randint(1, 3)
        out["exposure"].append({
            "customer_id": cid, "month": month_label(as_of, i), "num_active_facilities": len(active),
            "total_outstanding": sum(f.balance(i) for f in active), "total_credit_limit": limit or None,
            "revolving_drawn": drawn or None,
            "utilisation_pct": round(100 * drawn / limit, 1) if limit else None,
            "monthly_obligations": sum(f.due_amount(i) for f in active),
            "external_bureau_obligations": int(round(ext * rng.uniform(0.97, 1.03), -2)),
            "new_credit_inquiries_90d": inq,
        })

    # ---- customer profile + ground truth ----------------------------------
    if thin:
        onboard = month_anchor(as_of, hist_start) - timedelta(days=rng.randint(5, 40))
        if rng.random() < 0.4:
            category = None
    else:
        onboard = as_of - timedelta(days=rng.randint(400, 3000))
    out["customers"].append({
        "customer_id": cid, "customer_name": name, "customer_type": ctype,
        "employment_or_business_category": category, "industry": industry, "region": region,
        "portfolio_classification": portfolio, "segment": segment,
        "origination_rating": rng.choices(["A", "B", "C"], [0.45, 0.40, 0.15])[0],
        "declared_monthly_income": int(round(inflow0 * rng.uniform(0.9, 1.1), -3)),
        "relationship_manager": rng.choice(RMS), "onboarding_date": onboard.isoformat(),
    })
    out["ground_truth"].append({
        "customer_id": cid, "scenario": scen, "behaviour": beh, "customer_type": ctype,
        "industry": industry, "region": region, "expected_risk_band_indicative": expected,
        "planted_facts": "; ".join(facts) if facts else "no deterioration planted",
    })


# --------------------------------------------------------------------------- #
# Risk signal definitions (the 'configurable rules' input file)
# --------------------------------------------------------------------------- #
def risk_signal_definitions():
    S = lambda *a: dict(zip(["signal_id", "signal_name", "scenario", "metric", "window_months", "direction",
                             "trigger", "saturation", "weight", "requires", "min_observations"], a))
    signals = [
        S("RB01", "Late payment frequency", "Repayment Behaviour Deterioration",
          "late_instalments_in_window (dpd>0)", 6, "higher_is_worse", 2, 5, 15, "repayments", 3),
        S("RB02", "DPD trend rising", "Repayment Behaviour Deterioration",
          "slope_of_dpd_per_month (days/month)", 6, "higher_is_worse", 1.0, 6.0, 12, "repayments", 4),
        S("RB03", "Partial payment frequency", "Repayment Behaviour Deterioration",
          "partially_paid_instalments_in_window", 6, "higher_is_worse", 1, 3, 6, "repayments", 3),
        S("RB04", "Current delinquency", "Early Delinquency and Roll-Forward Risk",
          "current_dpd", 0, "higher_is_worse", 1, 60, 14, "delinquency", 1),
        S("CF01", "Consecutive inflow decline", "Declining Income and Cash Flow",
          "consecutive_months_total_inflows_declining", 6, "higher_is_worse", 2, 5, 14, "transactions", 4),
        S("CF02", "Inflow level change", "Declining Income and Cash Flow",
          "pct_change_avg_inflow_last3m_vs_prior3m", 6, "lower_is_worse", -10, -35, 6, "transactions", 6),
        S("CF03", "Balance erosion", "SME and Business Financial Stress",
          "pct_change_avg_balance_last3m_vs_prior3m", 6, "lower_is_worse", -15, -50, 5, "transactions", 6),
        S("CF04", "Outflow exceeds inflow", "SME and Business Financial Stress",
          "months_outflow_gt_inflow", 6, "higher_is_worse", 2, 5, 3, "transactions", 4),
        S("CF05", "Bounced / returned transactions", "SME and Business Financial Stress",
          "bounced_txns_in_window", 6, "higher_is_worse", 1, 4, 4, "transactions", 3),
        S("EX01", "Utilisation rise", "Increasing Financial Obligations and Exposure",
          "utilisation_pct_change_in_points", 6, "higher_is_worse", 15, 40, 8, "exposure", 4),
        S("EX02", "New facilities", "Increasing Financial Obligations and Exposure",
          "new_facilities_in_window", 6, "higher_is_worse", 1, 3, 4, "facilities", 1),
        S("EX03", "Obligation-to-inflow ratio trend", "Increasing Financial Obligations and Exposure",
          "change_in_obligation_to_inflow_pct_points", 6, "higher_is_worse", 5, 20, 7, "exposure+transactions", 4),
        S("EX04", "Credit inquiries", "Increasing Financial Obligations and Exposure",
          "new_credit_inquiries_90d_latest", 3, "higher_is_worse", 2, 6, 2, "exposure", 1),
    ]
    assert sum(s["weight"] for s in signals) == 100
    return {
        "version": "1.0",
        "score_scale": {"min": 0, "max": 100, "higher_score_means": "higher credit risk"},
        "scoring_method": "score = sum(weight_i * strength_i); strength_i linearly interpolated 0..1 between "
                          "trigger and saturation; weights sum to 100",
        "classification": [
            {"category": "Low", "min": 0, "max": 24, "monitoring_status": "Routine"},
            {"category": "Medium", "min": 25, "max": 49, "monitoring_status": "Watch"},
            {"category": "High", "min": 50, "max": 74, "monitoring_status": "Investigate"},
            {"category": "Critical", "min": 75, "max": 100, "monitoring_status": "Escalate"},
        ],
        "modifiers": {
            "temporary_missed_payment_dampener": {
                "applies_when": {"late_instalments_in_window_max": 1, "clean_instalments_before_min": 3,
                                 "recovered_within_instalments": 2},
                "multiplier_on_repayment_signals_with_evidence": 0.25,
                "multiplier_on_repayment_signals_without_evidence": 0.60},
            "missing_data_policy": {
                "min_repayment_months": 4, "min_transaction_months": 3,
                "behaviour": "skip signals whose data requirement is unmet and renormalise weights; "
                             "never add points for missing data; if too little data remains, "
                             "report status 'Insufficient data' instead of a risk category"},
            "confidence": "share of total signal weight that could be evaluated with sufficient data (0-1)",
        },
        "signals": signals,
    }


# --------------------------------------------------------------------------- #
# Dirty-data variant
# --------------------------------------------------------------------------- #
def inject_defects(tables, rng):
    t = {k: v.copy().reset_index(drop=True) for k, v in tables.items() if k != "ground_truth"}
    log = []

    def pick(df, k, mask=None):
        pool = list(df.index if mask is None else df.index[mask])
        return rng.sample(pool, min(k, len(pool)))

    def L(table, key, issue):
        log.append({"table": table, "record_key": key, "issue": issue})

    c, f, r, x, e = t["customers"], t["facilities"], t["repayments"], t["transactions"], t["exposure"]
    for ix in pick(c, 2):
        L("customers", c.at[ix, "customer_id"], "missing customer_type"); c.at[ix, "customer_type"] = None
    for ix in pick(c, 1):
        L("customers", c.at[ix, "customer_id"], "invalid customer_type value 'Individul'"); c.at[ix, "customer_type"] = "Individul"
    for ix in pick(c, 1):
        L("customers", c.at[ix, "customer_id"], "invalid onboarding_date"); c.at[ix, "onboarding_date"] = "2026-13-45"

    for ix in pick(f, 1):
        L("facilities", f.at[ix, "loan_id"], "negative sanctioned_amount"); f.at[ix, "sanctioned_amount"] = -abs(f.at[ix, "sanctioned_amount"])
    for ix in pick(f, 2, f["facility_type"] == "Term Loan"):
        L("facilities", f.at[ix, "loan_id"], "outstanding_balance exceeds sanctioned_amount")
        f.at[ix, "outstanding_balance"] = int(f.at[ix, "sanctioned_amount"] * 1.4)
    for ix in pick(f, 1):
        L("facilities", f.at[ix, "loan_id"], "tenure_months = 0"); f.at[ix, "tenure_months"] = 0

    for ix in pick(r, 2):
        L("repayments", r.at[ix, "repayment_id"], "negative amount_paid"); r.at[ix, "amount_paid"] = -abs(r.at[ix, "amount_paid"] or 100)
    for ix in pick(r, 2, r["payment_date"].notna()):
        L("repayments", r.at[ix, "repayment_id"], "unparseable payment_date"); r.at[ix, "payment_date"] = "31/02/2026"
    for ix in pick(r, 3, (r["dpd"] > 10) & (r["repayment_status"] == "Paid Late")):
        L("repayments", r.at[ix, "repayment_id"], "status 'Paid On Time' inconsistent with dpd"); r.at[ix, "repayment_status"] = "Paid On Time"

    f_add = f.loc[pick(f, 2)].copy()
    for n_, ix in enumerate(f_add.index):
        L("facilities", f"L99{n_ + 1:03d}", "orphan facility: customer_id C9999 does not exist")
    f_add["customer_id"] = "C9999"
    f_add["loan_id"] = [f"L99{n_ + 1:03d}" for n_ in range(len(f_add))]
    t["facilities"] = pd.concat([f, f_add], ignore_index=True)

    r_orph = r.loc[pick(r, 5)].copy()
    r_orph["loan_id"] = "L99999"
    r_orph["repayment_id"] = [f"R9{n_:05d}" for n_ in range(len(r_orph))]
    for k_ in r_orph["repayment_id"]:
        L("repayments", k_, "orphan repayment: loan_id L99999 does not exist")
    r_dup = r.loc[pick(r, 3)].copy()
    for k_ in r_dup["repayment_id"]:
        L("repayments", k_, "duplicate repayment_id")
    t["repayments"] = pd.concat([r, r_orph, r_dup], ignore_index=True)

    for ix in pick(x, 2):
        L("transactions", f"{x.at[ix, 'customer_id']}|{x.at[ix, 'month']}", "negative total_inflows"); x.at[ix, "total_inflows"] = -abs(x.at[ix, "total_inflows"])
    for ix in pick(x, 3):
        L("transactions", f"{x.at[ix, 'customer_id']}|{x.at[ix, 'month']}", "missing total_inflows"); x.at[ix, "total_inflows"] = None
    for ix in pick(x, 1):
        L("transactions", f"{x.at[ix, 'customer_id']}|{x.at[ix, 'month']}", "invalid month '2026-13'"); x.at[ix, "month"] = "2026-13"
    x_dup = x.loc[pick(x, 2)].copy()
    for _, row in x_dup.iterrows():
        L("transactions", f"{row['customer_id']}|{row['month']}", "duplicate customer-month record")
    x_orph = x.loc[pick(x, 2)].copy()
    x_orph["customer_id"] = "C9999"
    for _, row in x_orph.iterrows():
        L("transactions", f"C9999|{row['month']}", "orphan transaction: customer_id C9999 does not exist")
    t["transactions"] = pd.concat([x, x_dup, x_orph], ignore_index=True)

    for ix in pick(e, 2, e["utilisation_pct"].notna()):
        L("exposure", f"{e.at[ix, 'customer_id']}|{e.at[ix, 'month']}", "utilisation_pct = 135 (above 100)"); e.at[ix, "utilisation_pct"] = 135.0
    for ix in pick(e, 3):
        L("exposure", f"{e.at[ix, 'customer_id']}|{e.at[ix, 'month']}", "missing monthly_obligations"); e.at[ix, "monthly_obligations"] = None

    dup_c = c.loc[pick(c, 3)].copy()
    for k_ in dup_c["customer_id"]:
        L("customers", k_, "duplicate customer row")
    t["customers"] = pd.concat([c, dup_c], ignore_index=True)
    return t, pd.DataFrame(log)


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def write_excel(tables, path):
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, df in tables.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
        for ws in xw.book.worksheets:
            ws.freeze_panes = "A2"
            for row in ws.iter_rows():
                for cell in row:
                    cell.font = Font(name="Arial", size=10, bold=(cell.row == 1))
            for idx, col in enumerate(ws.iter_cols(min_row=1, max_row=1), start=1):
                ws.column_dimensions[get_column_letter(idx)].width = min(30, max(12, len(str(col[0].value)) + 3))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--customers", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--as-of", default="2026-10-31", help="snapshot date; history = 12 months ending here")
    ap.add_argument("--out", default="./synthetic_data")
    a = ap.parse_args()

    rng = random.Random(a.seed)
    as_of = date.fromisoformat(a.as_of)
    out = {k: [] for k in ["customers", "facilities", "repayments", "delinquency",
                           "exposure", "transactions", "ground_truth"]}
    ctr = {"L": 0, "R": 0}
    for n, (scen, beh, rule, over, exp) in enumerate(build_plan(a.customers, rng), start=1):
        gen_customer(f"C{n:04d}", scen, beh, rule, over, exp, rng, as_of, ctr, out)

    tables = {k: pd.DataFrame(v) for k, v in out.items()}
    signals = risk_signal_definitions()
    sig_df = pd.DataFrame(signals["signals"])

    clean = os.path.join(a.out, "clean")
    dirty = os.path.join(a.out, "dirty")
    os.makedirs(clean, exist_ok=True)
    os.makedirs(dirty, exist_ok=True)
    ingest = {k: v for k, v in tables.items() if k != "ground_truth"}

    for k, df in ingest.items():
        df.to_csv(os.path.join(clean, f"{k}.csv"), index=False)
    sig_df.to_csv(os.path.join(clean, "risk_signal_definitions.csv"), index=False)
    with open(os.path.join(clean, "risk_signal_definitions.json"), "w") as fh:
        json.dump(signals, fh, indent=2)
    with open(os.path.join(clean, "portfolio.json"), "w") as fh:
        json.dump({k: json.loads(df.to_json(orient="records")) for k, df in ingest.items()}, fh)
    write_excel({**ingest, "risk_signal_definitions": sig_df}, os.path.join(clean, "early_warning_data.xlsx"))

    dirty_tables, manifest = inject_defects(ingest, rng)
    for k, df in dirty_tables.items():
        df.to_csv(os.path.join(dirty, f"{k}.csv"), index=False)
    manifest.to_csv(os.path.join(dirty, "data_issues_manifest.csv"), index=False)
    tables["ground_truth"].to_csv(os.path.join(a.out, "ground_truth.csv"), index=False)

    counts = tables["ground_truth"]["scenario"].value_counts().sort_index()
    with open(os.path.join(a.out, "README.md"), "w") as fh:
        fh.write(f"# Synthetic EWS data (as-of {a.as_of}, seed {a.seed})\n\n")
        fh.write("- `clean/` : valid data. Ingest these. Also available as one Excel workbook and one JSON.\n")
        fh.write("- `dirty/` : same data with injected defects; `data_issues_manifest.csv` lists every defect.\n")
        fh.write("- `ground_truth.csv` : planted scenario per customer. Use only for testing, never as a feature.\n")
        fh.write("- `clean/risk_signal_definitions.*` : starter thresholds/weights. Score is 0-100, higher = riskier.\n\n")
        fh.write("## Scenario counts\n\n| scenario | customers |\n|---|---|\n")
        for s, c_ in counts.items():
            fh.write(f"| {s} | {c_} |\n")
    print(counts.to_string())
    print({k: len(v) for k, v in ingest.items()})


if __name__ == "__main__":
    main()
