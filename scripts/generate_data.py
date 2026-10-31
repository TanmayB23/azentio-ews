#!/usr/bin/env python3
"""Synthetic portfolio generator for the Early Warning System.

Every customer follows a planted scenario with a deliberate, time-based pattern,
so detection and scoring can be tested against ground truth. 18 months of
history: a clean baseline year, then the 6-month window where most
deterioration happens. Holiday exceptions use the region profile's calendar.

Usage:
    python scripts/generate_data.py --profile india --customers 500 --seed 42
    python scripts/generate_data.py --profile gcc_islamic --customers 400 --seed 7

Writes data/<profile>/:
    clean/   customers, facilities, repayments, delinquency, exposure, transactions,
             sme_indicators (CSV) + early_warning_data.xlsx + portfolio.json
             + risk_signal_definitions.json / .csv
    dirty/   the same tables with injected defects + data_issues_manifest.csv
    ground_truth.csv   planted scenario per customer (tests only, never a feature)
    README.md
"""
from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MONTHS = 18                      # month index 0..17, 17 = as-of month
LAST = MONTHS - 1
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# --------------------------------------------------------------------------- #
# Region reference data
# --------------------------------------------------------------------------- #
REGION_DATA = {
    "india": dict(
        first=["Aarav", "Priya", "Rohan", "Ananya", "Karthik", "Meera", "Imran", "Sneha", "Arjun", "Divya",
               "Vikram", "Neha", "Suresh", "Lakshmi", "Farhan", "Pooja", "Manoj", "Kavya", "Rajesh", "Isha"],
        last=["Sharma", "Iyer", "Reddy", "Nair", "Khan", "Patel", "Gupta", "Menon", "Singh", "Das",
              "Kulkarni", "Mehta", "Rao", "Joshi", "Pillai", "Naidu", "Bose", "Chawla", "Shetty", "Verma"],
        sme_suffix=["Enterprises", "Traders", "Industries", "& Sons"],
        regions=["Karnataka", "Tamil Nadu", "Maharashtra", "Gujarat", "Delhi NCR", "Telangana",
                 "West Bengal", "Kerala", "Uttar Pradesh"],
        sme_industries=["Textiles", "Retail & Trading", "Manufacturing", "Food & Beverage", "IT Services",
                        "Logistics & Transport", "Construction", "Agri-processing"],
        ind_categories={
            "Salaried - Private": ["IT / Software", "Banking & Finance", "Healthcare", "Manufacturing", "Retail"],
            "Salaried - Government": ["Public Sector", "Education"],
            "Self-employed Professional": ["Healthcare", "Legal & Consulting", "Education"],
            "Gig / Platform Worker": ["Gig Economy"],
        },
        rms=["Anita Rao", "Vikram Shah", "Meera Pillai", "Rahul Verma", "Sana Qureshi", "Karthik Iyer"],
        income=dict(ind=(25_000, 220_000), gig=(22_000, 60_000), sme=(300_000, 4_000_000)),
        rate_col="interest_rate_pct",
        term_ind=[("Personal Loan", None, [24, 36, 48, 60], (12, 18)), ("Auto Loan", None, [36, 48, 60, 84], (9, 12)),
                  ("Home Loan", None, [120, 180, 240], (8.5, 9.5))],
        term_sme=[("Business Term Loan", None, [24, 36, 60, 84], (11, 15))],
        rev_ind=("Credit Card", None, (36, 42)),
        rev_sme=("Working Capital Limit", None, (10, 14)),
        clusters=[
            dict(scenario="S8_cluster_textiles_tamil_nadu", behaviour="sme_stress", ctype="SME",
                 industry="Textiles", region="Tamil Nadu", n=12, expected="Medium to High (cluster of SMEs)",
                 fact="buyers paying late across the Tirupur textile segment"),
            dict(scenario="S8_cluster_gig_workers_karnataka", behaviour="declining_cashflow", ctype="Individual",
                 category="Gig / Platform Worker", region="Karnataka", n=8,
                 expected="Medium to High (cluster of gig workers)", fact="platform payout cuts in Karnataka"),
            dict(scenario="S8_cluster_logistics_fuel_costs", behaviour="margin_squeeze", ctype="SME",
                 industry="Logistics & Transport", region=None, n=9, expected="Medium (cluster, early stage)",
                 fact="fuel cost rise squeezing logistics operators"),
        ],
        seasonal_peak_month=-5,  # harvest-season (May) peak for seasonal SMEs
    ),
    "gcc_islamic": dict(
        first=["Ahmed", "Fatima", "Mohammed", "Aisha", "Omar", "Mariam", "Khalid", "Noura", "Yousef", "Huda",
               "Rajesh", "Priya", "Jose", "Maria", "Imran", "Sana", "Ali", "Layla", "Hassan", "Reem"],
        last=["Al Mansoori", "Al Hashimi", "Al Qahtani", "Al Shamsi", "Haddad", "Khan", "Nair", "Santos",
              "Al Farsi", "Al Otaibi", "Rahman", "Siddiqui", "Fernandes", "Al Mazrouei", "Saleh"],
        sme_suffix=["Trading LLC", "Contracting LLC", "Services LLC", "Group"],
        regions=["Dubai", "Abu Dhabi", "Sharjah", "Riyadh", "Jeddah", "Dammam", "Doha", "Muscat", "Manama"],
        sme_industries=["Construction & Contracting", "Real Estate Services", "Retail & Trading", "Hospitality",
                        "Logistics & Transport", "Food & Beverage", "Oil & Gas Services", "IT Services"],
        ind_categories={
            "Salaried - Private": ["Banking & Finance", "Healthcare", "Retail", "Hospitality", "Construction"],
            "Salaried - Government": ["Public Sector", "Education"],
            "Self-employed Professional": ["Healthcare", "Legal & Consulting"],
            "Gig / Platform Worker": ["Delivery & Ride-hailing"],
        },
        rms=["Fatima Al Zaabi", "Omar Haddad", "Anil Menon", "Sara Al Harthy", "Bilal Qureshi", "Grace Thomas"],
        income=dict(ind=(8_000, 60_000), gig=(4_000, 9_000), sme=(100_000, 2_000_000)),
        rate_col="profit_rate_pct",
        term_ind=[("Tawarruq Personal Finance", "Tawarruq", [24, 36, 48], (5, 8)),
                  ("Murabaha Auto Finance", "Murabaha", [36, 48, 60], (3.5, 5.5)),
                  ("Ijarah Home Finance", "Ijarah", [180, 240, 300], (4, 5.5))],
        term_sme=[("Murabaha Business Finance", "Murabaha", [24, 36, 60], (5, 8))],
        rev_ind=("Islamic Credit Card", "Ujrah", (24, 30)),
        rev_sme=("Murabaha Working Capital Line", "Murabaha", (6, 9)),
        clusters=[
            dict(scenario="S8_cluster_contractors_dubai", behaviour="sme_stress", ctype="SME",
                 industry="Construction & Contracting", region="Dubai", n=10,
                 expected="Medium to High (cluster of SMEs)", fact="delayed payments on government projects"),
            dict(scenario="S8_cluster_delivery_riders_riyadh", behaviour="declining_cashflow", ctype="Individual",
                 category="Gig / Platform Worker", region="Riyadh", n=7,
                 expected="Medium to High (cluster of gig workers)", fact="platform incentive cuts in Riyadh"),
        ],
        seasonal_peak_month=-7,  # Ramadan / Eid peak (spring 2026)
    ),
}

# (scenario, behaviour, share, customer-type rule, expected band)
# Shares give a realistic book: roughly 60% healthy, 20-25% showing some warning.
PLAN = [
    ("S0_volatile_but_stable", "volatile", 0.03, None, "Low (volatility alone is not deterioration)"),
    ("S0_seasonal_sme", "seasonal", 0.02, "SME", "Low (seasonal dip matches last year)"),
    ("S1_repeated_repayment_delays", "repeated_delay", 0.04, None, "High"),
    ("S2_declining_income_cashflow", "declining_cashflow", 0.035, "mixed", "Medium to High"),
    ("S3_increasing_exposure", "increasing_exposure", 0.035, None, "Medium to High"),
    ("S4_temporary_miss_with_evidence", "temp_miss_evidence", 0.02, None, "Low"),
    ("S4_temporary_miss_no_evidence", "temp_miss_no_evidence", 0.02, None, "Low"),
    ("S5_early_delinquency_recovering", "early_delinq_recovering", 0.02, None, "Low-Medium to Medium"),
    ("S5_early_delinquency_worsening", "early_delinq_worsening", 0.025, None, "High to Critical"),
    ("S6_sme_financial_stress", "sme_stress", 0.025, "SME", "High"),
    ("S7_thin_history", "thin_file", 0.025, None, "Insufficient data (must NOT be High)"),
    ("S7_no_transaction_data", "no_transactions", 0.01, None, "Low (reduced confidence)"),
    ("S7_transaction_gap", "txn_gap", 0.02, None, "Low (reduced confidence)"),
]

EXCEPTIONS = {  # (reason, evidence, delay range, dips income that month)
    "evidence_ind": [("Bank holiday on due date", True, (1, 3), False),
                     ("NACH/UPI processing delay", True, (2, 5), False),
                     ("Salary credit delayed by employer", True, (8, 20), True),
                     ("Medical emergency (hospital bills provided)", True, (10, 20), False)],
    "evidence_sme": [("Bank holiday on due date", True, (1, 3), False),
                     ("NACH/UPI processing delay", True, (2, 5), False),
                     ("Large receivable delayed by buyer", True, (8, 20), True)],
    "no_evidence": [("Customer-reported, no supporting document", False, (6, 15), False),
                    (None, False, (8, 25), False)],
}
ALL_FACILITIES_BEHAVE = {"repeated_delay", "early_delinq_worsening", "early_delinq_recovering"}


# --------------------------------------------------------------------------- #
# Date helpers
# --------------------------------------------------------------------------- #
class Calendar:
    def __init__(self, as_of: date, profile: dict):
        self.as_of = as_of
        cal = profile.get("calendar", {})
        self.weekend = {WEEKDAYS.index(d) for d in cal.get("weekend", [])}
        self.holidays = {date.fromisoformat(d) for d in cal.get("holidays", [])}

    def month_start(self, i: int) -> date:
        y, m = self.as_of.year, self.as_of.month - (LAST - i)
        while m <= 0:
            y, m = y - 1, m + 12
        while m > 12:
            y, m = y + 1, m - 12
        return date(y, m, 1)

    def label(self, i: int) -> str:
        return self.month_start(i).strftime("%Y-%m")

    def due(self, i: int, day: int) -> date:
        return self.month_start(i).replace(day=min(day, 28))

    def non_business(self, d: date) -> bool:
        return d.weekday() in self.weekend or d in self.holidays


def add_months(d: date, k: int) -> date:
    m = d.month - 1 + k
    return date(d.year + m // 12, m % 12 + 1, min(d.day, 28))


def bucket(dpd: float) -> str:
    for label, hi in (("Current", 0), ("1-30", 30), ("31-60", 60), ("61-90", 90)):
        if dpd <= hi:
            return label
    return "90+"


# --------------------------------------------------------------------------- #
# Facilities
# --------------------------------------------------------------------------- #
@dataclass
class Facility:
    loan_id: str
    product: str
    contract: str | None
    revolving: bool
    disb_idx: int                 # month index of disbursement (negative = before history)
    rate: float
    tenure: int
    due_day: int
    principal: float = 0.0
    emi: float = 0.0
    limit: float = 0.0
    util: list = field(default_factory=list)
    primary: bool = False
    is_new: bool = False

    def balance(self, i: int) -> float:
        if self.revolving:
            return self.limit * self.util[i]
        k = max(0, min(i - self.disb_idx, self.tenure))
        r = self.rate / 1200
        return max(0.0, self.principal * (1 + r) ** k - self.emi * ((1 + r) ** k - 1) / r)

    def due_amount(self, i: int) -> int:
        if not self.revolving:
            return int(round(self.emi, -2))
        drawn = self.balance(i)
        if self.product_kind == "card":
            return int(round(max(0.05 * drawn, 500), -2))
        return int(round(drawn * self.rate / 1200, -2))

    @property
    def product_kind(self) -> str:
        return "card" if "Card" in self.product else "line"


def util_path(base, ramp_from, target, rng):
    out, cur = [], base
    for i in range(MONTHS):
        if ramp_from is not None and i >= ramp_from:
            cur += (target - cur) * rng.uniform(0.3, 0.5)
        out.append(min(0.99, max(0.02, cur + rng.gauss(0, 0.02))))
    return out


def make_term(rd, ctr, prod, emi_budget, disb_idx, rng, is_new=False):
    """disb_idx=None picks a disbursement before the history that still matures after the as-of date."""
    name, contract, tenures, (lo, hi) = prod
    tenure, rate = rng.choice(tenures), round(rng.uniform(lo, hi), 2)
    if disb_idx is None:
        disb_idx = rng.randint(max(-48, LAST - tenure + 2), -2)
    r = rate / 1200
    principal = round(emi_budget * (1 - (1 + r) ** -tenure) / r, -3)
    ctr["L"] += 1
    f = Facility(f"L{ctr['L']:05d}", name, contract, False, disb_idx, rate, tenure, rng.randint(1, 28),
                 principal=principal, is_new=is_new)
    f.emi = principal * r / (1 - (1 + r) ** -tenure)
    return f


def make_rev(rd, ctr, prod, limit, disb_idx, base, ramp_from, target, rng, is_new=False):
    name, contract, (lo, hi) = prod
    ctr["L"] += 1
    f = Facility(f"L{ctr['L']:05d}", name, contract, True, disb_idx, round(rng.uniform(lo, hi), 2), 12,
                 rng.randint(1, 28), limit=round(limit, -4), is_new=is_new)
    f.util = util_path(base, ramp_from, target, rng)
    for i in range(MONTHS):
        if i <= disb_idx:
            f.util[i] = 0.0
    return f


# --------------------------------------------------------------------------- #
# Behaviour
# --------------------------------------------------------------------------- #
def noise_delay(rng):
    r = rng.random()
    if r < 0.95:
        return 0
    return rng.randint(1, 3) if r < 0.99 else rng.randint(4, 6)


def payment_outcome(beh, p, i, rng):
    """(delay days or None if unpaid, paid fraction, (reason, evidence) or None)."""
    if beh == "repeated_delay" and i >= p["start"]:
        j = i - p["start"]
        if j == 0 or rng.random() < 0.8:
            frac = rng.uniform(0.4, 0.8) if rng.random() < 0.25 else 1.0
            return min(80, int(3 + j * rng.uniform(2, 5) + rng.randint(0, 4))), frac, None
        return rng.randint(0, 2), 1.0, None
    if beh in ("early_delinq_worsening", "early_delinq_recovering") and i in p["delays"]:
        delay, frac = p["delays"][i]
        return delay, frac, None
    if beh in ("temp_miss_evidence", "temp_miss_no_evidence"):
        if i == p["miss"]:
            return p["delay"], 1.0, p["exc"]
        if i > p["miss"]:
            return 0, 1.0, None
    if beh in ("sme_stress", "margin_squeeze") and i >= LAST - 3 and rng.random() < 0.4:
        return rng.randint(2, 7), 1.0, None
    return noise_delay(rng), 1.0, None


def worsening_delays(rng):
    """Three severities: latest unpaid (1-30), last two unpaid (31-60), last three unpaid (61-90)."""
    sev = rng.choice([1, 1, 2, 3])
    d = {LAST - 4: (rng.randint(4, 6), 1.0), LAST - 3: (rng.randint(9, 13), 1.0),
         LAST - 2: (rng.randint(16, 22), 0.6 if rng.random() < 0.5 else 1.0), LAST - 1: (rng.randint(22, 28), 1.0)}
    for k in range(sev):
        d[LAST - k] = (None, 0.0)
    return d, sev


def income_trend(beh, rng, is_sme):
    trend = [1.0] * MONTHS
    k, lo, hi = {"declining_cashflow": (rng.randint(3, 6), *((0.07, 0.13) if is_sme else (0.05, 0.10))),
                 "sme_stress": (rng.randint(4, 6), 0.08, 0.14),
                 "early_delinq_worsening": (4, 0.05, 0.09),
                 "repeated_delay": (rng.randint(4, 7), 0.02, 0.04)}.get(beh, (0, 0, 0))
    cur = 1.0
    for i in range(MONTHS - k, MONTHS):
        cur *= 1 - rng.uniform(lo, hi)
        trend[i] = cur
    if beh == "early_delinq_recovering":
        for i, v in ((LAST - 6, 0.8), (LAST - 5, 0.78), (LAST - 4, 0.88)):
            trend[i] = v
    return trend, k


# --------------------------------------------------------------------------- #
# Customer generation
# --------------------------------------------------------------------------- #
def gen_customer(cid, scen, beh, ctype_rule, over, expected, rd, cal, rng, ctr, out):
    if ctype_rule in ("SME", "Individual"):
        ctype = ctype_rule
    elif ctype_rule == "mixed":
        ctype = "SME" if rng.random() < 0.5 else "Individual"
    else:
        ctype = "Individual" if rng.random() < 0.62 else "SME"
    is_sme = ctype == "SME"
    facts: list[str] = []

    # ---- profile ------------------------------------------------------------
    if is_sme:
        inflow0 = float(round(rng.uniform(*rd["income"]["sme"]), -4))
        industry = over.get("industry") or rng.choice(rd["sme_industries"])
        category = rng.choice(["Proprietorship", "Partnership", "Private Limited"])
        name = f"{rng.choice(rd['last'])} {industry.split(' ')[0]} {rng.choice(rd['sme_suffix'])}"
        portfolio, segment = "SME Banking", rng.choice(["SME Core", "SME Emerging"])
    else:
        if beh == "volatile" and rng.random() < 0.6:
            category = "Gig / Platform Worker"
        else:
            category = over.get("category") or rng.choices(list(rd["ind_categories"]), [0.5, 0.2, 0.18, 0.12])[0]
        industry = rng.choice(rd["ind_categories"][category])
        key = "gig" if category.startswith("Gig") else "ind"
        inflow0 = float(round(rng.uniform(*rd["income"][key]), -3))
        name = f"{rng.choice(rd['first'])} {rng.choice(rd['last'])}"
        portfolio, segment = "Retail Banking", rng.choice(["Prime", "Near Prime"])
    region = over.get("region") or rng.choice(rd["regions"])

    thin = beh == "thin_file"
    hist_start = LAST - rng.randint(0, 2) if thin else 0

    # ---- behaviour parameters -----------------------------------------------
    p: dict = {}
    if beh == "repeated_delay":
        k = rng.randint(4, 7)
        p["start"] = MONTHS - k
        facts.append(f"regular payer for {MONTHS - k} months, then delays growing over the last {k}")
    elif beh == "early_delinq_worsening":
        p["delays"], sev = worsening_delays(rng)
        facts.append(f"delays rising then the last {sev} instalment(s) unpaid "
                     f"({ {1: '1-30', 2: '31-60', 3: '61-90'}[sev] } DPD bucket)")
    elif beh == "early_delinq_recovering":
        p["delays"] = {LAST - 5: (rng.randint(14, 18), 1.0), LAST - 4: (rng.randint(8, 11), 1.0),
                       LAST - 3: (rng.randint(3, 5), 1.0)}
        d = p["delays"]
        facts.append(f"delays {d[LAST - 5][0]}/{d[LAST - 4][0]}/{d[LAST - 3][0]} days after an income dip, "
                     "then 3 months on time")
    elif beh in ("temp_miss_evidence", "temp_miss_no_evidence"):
        pool = EXCEPTIONS["no_evidence"] if beh == "temp_miss_no_evidence" else \
            EXCEPTIONS["evidence_sme" if is_sme else "evidence_ind"]
        reason, evid, (lo, hi), dips = rng.choice(pool)
        p.update(reason=reason, evid=evid, delay=rng.randint(lo, hi), dips=dips, miss=rng.randint(LAST - 6, LAST - 2))
        p["exc"] = (reason, evid) if reason else None
    elif beh == "txn_gap":
        p["gap"] = rng.randint(4, LAST - 2)
        facts.append(f"transaction feed missing for {cal.label(p['gap'])} and {cal.label(p['gap'] + 1)}")
    elif beh == "thin_file":
        p["no_txn"] = rng.random() < 0.4
        facts.append(f"onboarded {MONTHS - hist_start} month(s) ago; transactions missing={p['no_txn']}")
    elif beh == "no_transactions":
        facts.append("established repayment history but no transaction feed")
    elif beh == "seasonal":
        facts.append("strong seasonal receipts; the recent dip matches the same months last year")
    elif beh == "margin_squeeze":
        facts.append("receipts flat but costs rising for 5 months; balances eroding")

    # ---- facilities ---------------------------------------------------------
    term_pool = rd["term_sme"] if is_sme else rd["term_ind"]
    term_w = None if is_sme else [0.45, 0.25, 0.30]
    pick_term = lambda: rng.choices(term_pool, term_w)[0] if term_w else rng.choice(term_pool)
    rev_prod = rd["rev_sme"] if is_sme else rd["rev_ind"]
    budget = inflow0 * (rng.uniform(0.08, 0.22) if is_sme else rng.uniform(0.15, 0.35))
    disb_term = (lambda: hist_start - 1) if thin else (lambda: None)
    disb = (lambda: hist_start - 1) if thin else (lambda: rng.randint(-48, -2))

    if beh in ("increasing_exposure", "sme_stress"):
        n_rev, n_term = 1, 1
    else:
        n_extra = rng.choices([0, 1], [0.5, 0.5])[0] if is_sme else rng.choices([0, 1, 2], [0.5, 0.35, 0.15])[0]
        n_rev = sum(rng.random() < 0.5 for _ in range(n_extra))
        n_term = 1 + n_extra - n_rev
    facs: list[Facility] = []
    for j in range(n_term):
        facs.append(make_term(rd, ctr, pick_term(), budget * (0.6 if j == 0 else 0.25), disb_term(), rng))
    for _ in range(n_rev):
        limit = inflow0 * (rng.uniform(0.5, 1.5) if is_sme else rng.uniform(1.5, 3.0))
        base = rng.uniform(0.25, 0.5) if is_sme else rng.uniform(0.15, 0.45)
        ramp_from, target = None, None
        if beh == "increasing_exposure":
            base, ramp_from, target = rng.uniform(0.25, 0.4), LAST - 4, rng.uniform(0.85, 0.97)
        elif beh in ("sme_stress", "margin_squeeze"):
            base, ramp_from, target = rng.uniform(0.35, 0.5), LAST - 5, rng.uniform(0.8, 0.95)
        facs.append(make_rev(rd, ctr, rev_prod, limit, disb(), base, ramp_from, target, rng))
    facs[0].primary = True
    if beh in ("increasing_exposure", "sme_stress"):
        extras = rng.randint(1, 2) if beh == "increasing_exposure" else int(rng.random() < 0.5)
        for _ in range(extras):
            d_idx = rng.randint(LAST - 5, LAST - 1)
            if rng.random() < 0.6:
                facs.append(make_term(rd, ctr, pick_term(), inflow0 * rng.uniform(0.06, 0.12), d_idx, rng, True))
            else:
                limit = inflow0 * (rng.uniform(0.4, 1.0) if is_sme else rng.uniform(1.0, 2.0))
                facs.append(make_rev(rd, ctr, rev_prod, limit, d_idx, rng.uniform(0.6, 0.75), d_idx + 1,
                                     rng.uniform(0.8, 0.95), rng, True))
        if extras:
            facts.append(f"{extras} new facility(ies) in the last 6 months")
        facts.append("revolving utilisation ramping up")

    # temporary-miss bank holiday: move the miss onto a non-business due date if one exists
    if beh == "temp_miss_evidence" and p["reason"] == "Bank holiday on due date":
        options = [i for i in range(LAST - 6, LAST - 1) if cal.non_business(cal.due(i, facs[0].due_day))]
        if options:
            p["miss"] = rng.choice(options)
        else:
            p.update(reason="NACH/UPI processing delay", delay=rng.randint(2, 5))
            p["exc"] = (p["reason"], True)
    if beh in ("temp_miss_evidence", "temp_miss_no_evidence"):
        facts.append(f"single late payment in {cal.label(p['miss'])} ({p['delay']}d), reason={p['reason']}, "
                     f"evidence={p['evid']}; clean before and after")

    # ---- transactions -------------------------------------------------------
    trend, k_decl = income_trend(beh, rng, is_sme)
    if beh in ("declining_cashflow", "sme_stress"):
        facts.append(f"income fell {100 * (1 - trend[LAST]):.0f}% over the last {k_decl} consecutive months")
    sigma = {"volatile": 0.18, "repeated_delay": 0.04}.get(beh, 0.05 if is_sme else 0.015)
    if category == "Gig / Platform Worker" and beh != "volatile":
        sigma = 0.06
    if k_decl and beh != "repeated_delay":
        sigma = 0.01
    amp = 0.28 if beh == "seasonal" else (0.05 if is_sme else 0.0)
    peak = rd["seasonal_peak_month"]
    mult = [(1 + amp * math.cos(2 * math.pi * (i - LAST - peak) / 12)) * max(0.3, rng.gauss(1, sigma))
            for i in range(MONTHS)]
    income = [inflow0 * mult[i] * trend[i] for i in range(MONTHS)]
    base_income = list(income)
    if beh in ("temp_miss_evidence", "temp_miss_no_evidence") and p["dips"]:
        income[p["miss"]] *= 0.3 if is_sme else 0.15
        income[p["miss"] + 1] *= 1.7 if is_sme else 1.85

    out_base = rng.uniform(0.88, 0.97)
    ramp_total = {"sme_stress": 0.16, "early_delinq_worsening": 0.10, "repeated_delay": 0.06,
                  "increasing_exposure": 0.06, "margin_squeeze": 0.14}.get(beh, 0.0)
    ramp_k = k_decl or (6 if beh in ("increasing_exposure", "margin_squeeze") else 0)
    stress_bounce = {"sme_stress": 0.5, "early_delinq_worsening": 0.5, "repeated_delay": 0.3,
                     "declining_cashflow": 0.15, "margin_squeeze": 0.3}.get(beh, 0.0)
    base_cnt = rng.randint(40, 110) if is_sme else rng.randint(2, 6)
    bal = inflow0 * rng.uniform(0.8, 1.8)
    emit_from = hist_start
    for i in range(MONTHS):
        in_ramp = ramp_k and i >= MONTHS - ramp_k
        ratio = out_base + (ramp_total * (i - (MONTHS - ramp_k) + 1) / ramp_k if in_ramp else 0)
        other = income[i] * rng.uniform(0, 0.08)
        outflow = base_income[i] * ratio * rng.gauss(1, 0.03)
        if beh == "margin_squeeze":
            outflow = inflow0 * mult[i] * ratio * rng.gauss(1, 0.02)
        closing = max(bal + income[i] + other - outflow, 0.03 * inflow0)
        bounced = rng.randint(1, 3) if (in_ramp and rng.random() < stress_bounce) else int(rng.random() < 0.03)
        emit = i >= emit_from and beh != "no_transactions" and not p.get("no_txn") \
            and not ("gap" in p and p["gap"] <= i <= p["gap"] + 1)
        if emit:
            out["transactions"].append({
                "customer_id": cid, "month": cal.label(i),
                "income_receipts": int(income[i]), "other_inflows": int(other),
                "total_inflows": int(income[i]) + int(other), "total_outflows": int(outflow),
                "avg_balance": int((bal + closing) / 2), "closing_balance": int(closing),
                "min_balance": int(min(bal, closing) * rng.uniform(0.6, 0.95)),
                "inflow_txn_count": max(1, round(base_cnt * mult[i] * trend[i])), "bounced_txns": bounced,
            })
        bal = closing

    # ---- SME indicators -----------------------------------------------------
    if is_sme:
        stressed = beh in ("sme_stress", "margin_squeeze")
        recv0, pay0 = rng.uniform(30, 60), rng.uniform(30, 50)
        for i in range(hist_start, MONTHS):
            ramp = max(0, i - (LAST - 5)) / 5 if stressed else 0.0
            late_p, miss_p = (0.45 * ramp, 0.25 * ramp) if stressed else (0.04, 0.0)
            r = rng.random()
            status = "Not Filed" if r < miss_p else ("Filed Late" if r < miss_p + late_p else "Filed On Time")
            out["sme_indicators"].append({
                "customer_id": cid, "month": cal.label(i),
                "tax_reported_turnover": None if status == "Not Filed" else int(income[i] * rng.uniform(0.88, 1.0)),
                "tax_filing_status": status,
                "receivable_days": round(recv0 + 35 * ramp + rng.gauss(0, 2), 1),
                "payable_days": round(pay0 + 25 * ramp + rng.gauss(0, 2), 1),
            })
        if stressed:
            facts.append("receivable days and tax filing delays rising")

    # ---- repayments + delinquency ---------------------------------------------
    as_of = cal.as_of
    for f in facs:
        behaves = (not f.is_new) and (f.primary or beh in ALL_FACILITIES_BEHAVE)
        rows = []
        for i in range(max(f.disb_idx + 1, hist_start, 0), MONTHS):
            due = cal.due(i, f.due_day)
            if due > as_of:
                continue
            amt = f.due_amount(i)
            if amt <= 0:
                continue
            delay, frac, exc = payment_outcome(beh, p, i, rng) if behaves else (noise_delay(rng), 1.0, None)
            pay = None if delay is None else due + timedelta(days=delay)
            if pay is None or pay > as_of:
                paid, pay_s, dpd = 0, None, (as_of - due).days
                status = "Missed" if dpd > 30 else "Overdue"
            else:
                paid, dpd, pay_s = int(round(amt * frac)), delay, pay.isoformat()
                status = "Partially Paid" if frac < 0.999 else ("Paid Late" if delay > 0 else "Paid On Time")
            ctr["R"] += 1
            rows.append({
                "repayment_id": f"R{ctr['R']:06d}", "loan_id": f.loan_id, "customer_id": cid,
                "installment_no": i - f.disb_idx, "due_date": due.isoformat(), "payment_date": pay_s,
                "amount_due": amt, "amount_paid": paid, "dpd": dpd, "repayment_status": status,
                "exception_reason": exc[0] if exc else None,
                "exception_evidence_available": ("Y" if exc[1] else "N") if exc else None,
            })
        out["repayments"] += rows
        if rows:
            out["delinquency"].append(delinquency_row(f, cid, rows, as_of))
        disb_date = add_months(cal.month_start(0), f.disb_idx).replace(day=f.due_day)
        maturity = add_months(disb_date, f.tenure)
        while f.revolving and maturity <= as_of:      # revolving limits renew every 12 months
            maturity = add_months(maturity, 12)
        row = {
            "loan_id": f.loan_id, "customer_id": cid, "product_type": f.product,
            "facility_type": "Revolving" if f.revolving else "Term Loan",
            "sanctioned_amount": int(f.limit if f.revolving else f.principal),
            "credit_limit": int(f.limit) if f.revolving else None,
            "outstanding_balance": int(f.balance(LAST)), rd["rate_col"]: f.rate, "tenure_months": f.tenure,
            "instalment_amount": f.due_amount(LAST), "repayment_frequency": "Monthly", "due_day": f.due_day,
            "disbursement_date": disb_date.isoformat(),
            "first_due_date": add_months(disb_date, 1).isoformat(),
            "maturity_date": maturity.isoformat(), "facility_status": "Active",
        }
        if f.contract:
            row["contract_type"] = f.contract
        out["facilities"].append(row)

    # ---- exposure ---------------------------------------------------------------
    ext_base = inflow0 * rng.uniform(0.03 if beh == "increasing_exposure" else 0.0, 0.1)
    inq_base = rng.choice([0, 0, 1])
    for i in range(hist_start, MONTHS):
        active = [f for f in facs if f.disb_idx < i or (f.disb_idx == i and f.is_new)]
        if not active:
            continue
        rev = [f for f in active if f.revolving]
        limit, drawn = sum(f.limit for f in rev), sum(f.balance(i) for f in rev)
        ext = ext_base * (1 + 1.5 * (i - (LAST - 6)) / 6) if (beh == "increasing_exposure" and i > LAST - 6) else ext_base
        inq = inq_base
        if beh == "increasing_exposure" and i >= LAST - 5:
            inq = rng.randint(2, 6)
        elif beh == "sme_stress" and i >= LAST - 4:
            inq = rng.randint(1, 3)
        out["exposure"].append({
            "customer_id": cid, "month": cal.label(i), "num_active_facilities": len(active),
            "total_outstanding": int(sum(f.balance(i) for f in active)),
            "total_credit_limit": int(limit) if limit else None, "revolving_drawn": int(drawn) if rev else None,
            "utilisation_pct": round(100 * drawn / limit, 1) if limit else None,
            "monthly_obligations": int(sum(f.due_amount(i) for f in active)),
            "external_bureau_obligations": int(round(ext * rng.uniform(0.97, 1.03), -2)),
            "new_credit_inquiries_90d": inq,
        })

    # ---- customer + ground truth ------------------------------------------------
    onboard = cal.month_start(hist_start) - timedelta(days=rng.randint(5, 40)) if thin else \
        as_of - timedelta(days=rng.randint(600, 3000))
    if thin and rng.random() < 0.4:
        category = None
    cust = {
        "customer_id": cid, "customer_name": name, "customer_type": ctype,
        "employment_or_business_category": category, "industry": industry, "region": region,
        "portfolio_classification": portfolio, "segment": segment,
        "origination_rating": rng.choices(["A", "B", "C"], [0.45, 0.40, 0.15])[0],
        "declared_monthly_income": int(round(inflow0 * rng.uniform(0.9, 1.1), -3)),
        "relationship_manager": rng.choice(rd["rms"]), "onboarding_date": onboard.isoformat(),
    }
    if rd["rate_col"] == "profit_rate_pct":
        cust["resident_type"] = "National" if name.split()[-2:-1] == ["Al"] or rng.random() < 0.2 else "Expatriate"
    out["customers"].append(cust)
    if "fact" in over:
        facts.insert(0, over["fact"])
    out["ground_truth"].append({
        "customer_id": cid, "scenario": scen, "behaviour": beh, "customer_type": ctype, "industry": industry,
        "region": region, "expected_band": expected,
        "planted_facts": "; ".join(facts) if facts else "no deterioration planted",
    })


def delinquency_row(f: Facility, cid: str, rows: list[dict], as_of: date) -> dict:
    unpaid = [r for r in rows if r["repayment_status"] in ("Overdue", "Missed")]
    cur = max((r["dpd"] for r in unpaid), default=0)
    overdue = sum(r["amount_due"] - r["amount_paid"] for r in unpaid)
    if rows[-1]["repayment_status"] == "Partially Paid":
        cur = max(cur, (as_of - date.fromisoformat(rows[-1]["due_date"])).days)
        overdue += rows[-1]["amount_due"] - rows[-1]["amount_paid"]
    cutoff = as_of - timedelta(days=92)
    dpd_3m_ago = max(((cutoff - date.fromisoformat(r["due_date"])).days for r in rows
                      if date.fromisoformat(r["due_date"]) <= cutoff
                      and (r["payment_date"] is None or date.fromisoformat(r["payment_date"]) > cutoff)), default=0)
    last12 = rows[-12:]
    dpds = [r["dpd"] for r in last12]
    return {
        "loan_id": f.loan_id, "customer_id": cid, "current_dpd": cur, "overdue_balance": overdue,
        "delinquency_bucket": bucket(cur), "dpd_bucket_3m_ago": bucket(dpd_3m_ago),
        "max_dpd_12m": max(dpds), "late_instalments_12m": sum(d > 0 for d in dpds),
        "instalments_30plus_dpd_12m": sum(d > 30 for d in dpds),
        "partial_payments_12m": sum(r["repayment_status"] == "Partially Paid" for r in last12),
        "ever_late_flag": "Y" if any(r["dpd"] > 0 for r in rows) else "N",
        "ever_30plus_flag": "Y" if any(r["dpd"] > 30 for r in rows) else "N",
    }


def build_plan(n, rd, rng):
    items = []
    for c in rd["clusters"]:
        over = {k: c[k] for k in ("industry", "region", "category", "fact") if c.get(k)}
        items += [(c["scenario"], c["behaviour"], c["ctype"], over, c["expected"])] * c["n"]
    for scen, beh, share, ctype, expected in PLAN:
        items += [(scen, beh, ctype, {}, expected)] * max(1, round(share * n))
    items += [("S0_healthy", "healthy", None, {}, "Low")] * max(0, n - len(items))
    rng.shuffle(items)
    return items[:n]


# --------------------------------------------------------------------------- #
# Dirty copy
# --------------------------------------------------------------------------- #
def inject_defects(tables, rng):
    t = {k: v.copy().reset_index(drop=True) for k, v in tables.items()}
    log = []
    L = lambda table, key, issue: log.append({"table": table, "record_key": key, "issue": issue})
    pick = lambda df, k, mask=None: rng.sample(list(df.index if mask is None else df.index[mask]), k)
    mk = lambda df, ix: f"{df.at[ix, 'customer_id']}|{df.at[ix, 'month']}"
    for col in ("declared_monthly_income",):
        t["customers"][col] = t["customers"][col].astype(object)
    t["repayments"]["amount_due"] = t["repayments"]["amount_due"].astype(object)
    c, f, r, x, e = t["customers"], t["facilities"], t["repayments"], t["transactions"], t["exposure"]

    for ix in pick(c, 2):
        L("customers", c.at[ix, "customer_id"], "missing customer_type"); c.at[ix, "customer_type"] = None
    for ix in pick(c, 1, c["customer_type"] == "Individual"):
        L("customers", c.at[ix, "customer_id"], "invalid customer_type value 'Individul'"); c.at[ix, "customer_type"] = "Individul"
    for ix in pick(c, 1, c["customer_type"] == "SME"):
        L("customers", c.at[ix, "customer_id"], "customer_type in lowercase 'sme'"); c.at[ix, "customer_type"] = "sme"
    for ix in pick(c, 1):
        L("customers", c.at[ix, "customer_id"], "invalid onboarding_date"); c.at[ix, "onboarding_date"] = "2026-13-45"
    for ix in pick(c, 2):
        L("customers", c.at[ix, "customer_id"], "declared_monthly_income with thousands separators")
        c.at[ix, "declared_monthly_income"] = f"{int(c.at[ix, 'declared_monthly_income']):,}"

    for ix in pick(f, 1):
        L("facilities", f.at[ix, "loan_id"], "negative sanctioned_amount"); f.at[ix, "sanctioned_amount"] *= -1
    for ix in pick(f, 2, f["facility_type"] == "Term Loan"):
        L("facilities", f.at[ix, "loan_id"], "outstanding_balance exceeds sanctioned_amount")
        f.at[ix, "outstanding_balance"] = int(f.at[ix, "sanctioned_amount"] * 1.4)
    for ix in pick(f, 1):
        L("facilities", f.at[ix, "loan_id"], "tenure_months = 0"); f.at[ix, "tenure_months"] = 0

    for ix in pick(r, 2, r["amount_paid"] > 0):
        L("repayments", r.at[ix, "repayment_id"], "negative amount_paid"); r.at[ix, "amount_paid"] *= -1
    for ix in pick(r, 2, r["payment_date"].notna()):
        L("repayments", r.at[ix, "repayment_id"], "unparseable payment_date"); r.at[ix, "payment_date"] = "31/02/2026"
    for ix in pick(r, 3, (r["dpd"] > 10) & (r["repayment_status"] == "Paid Late")):
        L("repayments", r.at[ix, "repayment_id"], "status 'Paid On Time' inconsistent with dpd")
        r.at[ix, "repayment_status"] = "Paid On Time"
    for ix in pick(r, 2):
        L("repayments", r.at[ix, "repayment_id"], "amount_due with thousands separators")
        r.at[ix, "amount_due"] = f"{int(r.at[ix, 'amount_due']):,}"

    f_add = f.loc[pick(f, 2)].copy()
    f_add["customer_id"] = "C9999"
    f_add["loan_id"] = [f"L99{n + 1:03d}" for n in range(len(f_add))]
    for k in f_add["loan_id"]:
        L("facilities", k, "orphan facility: customer_id C9999 does not exist")
    t["facilities"] = pd.concat([f, f_add], ignore_index=True)

    r_orph = r.loc[pick(r, 5)].copy()
    r_orph["loan_id"] = "L99999"
    r_orph["repayment_id"] = [f"R9{n:05d}" for n in range(len(r_orph))]
    for k in r_orph["repayment_id"]:
        L("repayments", k, "orphan repayment: loan_id L99999 does not exist")
    r_dup = r.loc[pick(r, 3)].copy()
    for k in r_dup["repayment_id"]:
        L("repayments", k, "duplicate repayment_id")
    t["repayments"] = pd.concat([r, r_orph, r_dup], ignore_index=True)

    for ix in pick(x, 2):
        L("transactions", mk(x, ix), "negative total_inflows"); x.at[ix, "total_inflows"] *= -1
    for ix in pick(x, 3):
        L("transactions", mk(x, ix), "missing total_inflows"); x.at[ix, "total_inflows"] = None
    for ix in pick(x, 1):
        L("transactions", mk(x, ix), "invalid month '2026-13'"); x.at[ix, "month"] = "2026-13"
    x_dup = x.loc[pick(x, 2, x["month"] != "2026-13")].copy()
    for ix in x_dup.index:
        L("transactions", mk(x_dup, ix), "duplicate customer-month record")
    x_orph = x.loc[pick(x, 2, x["month"] != "2026-13")].copy()
    x_orph["customer_id"] = "C9999"
    for ix in x_orph.index:
        L("transactions", mk(x_orph, ix), "orphan transaction: customer_id C9999 does not exist")
    t["transactions"] = pd.concat([x, x_dup, x_orph], ignore_index=True)

    for ix in pick(e, 2, e["utilisation_pct"].notna()):
        L("exposure", mk(e, ix), "utilisation_pct = 135 (above 100)"); e.at[ix, "utilisation_pct"] = 135.0
    for ix in pick(e, 3):
        L("exposure", mk(e, ix), "missing monthly_obligations"); e.at[ix, "monthly_obligations"] = None

    dup_c = c.loc[pick(c, 3)].copy()
    for k in dup_c["customer_id"]:
        L("customers", k, "duplicate customer row")
    t["customers"] = pd.concat([c, dup_c], ignore_index=True)
    return t, pd.DataFrame(log)


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
TABLES = ["customers", "facilities", "repayments", "delinquency", "exposure", "transactions", "sme_indicators"]


def write_outputs(out_dir: Path, tables: dict, gt: pd.DataFrame, defs: dict, profile: dict, seed: int, rng):
    clean, dirty = out_dir / "clean", out_dir / "dirty"
    clean.mkdir(parents=True, exist_ok=True)
    dirty.mkdir(parents=True, exist_ok=True)
    for name in TABLES:
        tables[name].to_csv(clean / f"{name}.csv", index=False)
    sig_df = pd.DataFrame(defs["signals"])
    sig_df.to_csv(clean / "risk_signal_definitions.csv", index=False)
    (clean / "risk_signal_definitions.json").write_text(json.dumps(defs, indent=2), encoding="utf-8")
    with pd.ExcelWriter(clean / "early_warning_data.xlsx") as xw:
        for name in TABLES:
            tables[name].to_excel(xw, sheet_name=name, index=False)
        sig_df.to_excel(xw, sheet_name="risk_signal_definitions", index=False)
    portfolio = {name: json.loads(tables[name].to_json(orient="records")) for name in TABLES}
    (clean / "portfolio.json").write_text(json.dumps(portfolio), encoding="utf-8")

    dirty_tables, manifest = inject_defects({k: tables[k] for k in TABLES}, rng)
    for name in TABLES:
        dirty_tables[name].to_csv(dirty / f"{name}.csv", index=False)
    manifest.to_csv(dirty / "data_issues_manifest.csv", index=False)
    gt.to_csv(out_dir / "ground_truth.csv", index=False)

    counts = gt["scenario"].value_counts().sort_index()
    expected = gt.drop_duplicates("scenario").set_index("scenario")["expected_band"]
    lines = [f"# Synthetic EWS data: {profile['profile']} (as-of {profile['as_of']}, seed {seed})", "",
             f"{len(gt)} customers, {MONTHS} months of history, currency {profile.get('currency', '')}. "
             "Generated by `scripts/generate_data.py`.", "",
             "- `clean/`: valid data as CSV per table, one Excel workbook and one JSON file. Ingest these.",
             "- `dirty/`: the same data with injected defects; `data_issues_manifest.csv` lists every defect.",
             "- `ground_truth.csv`: planted scenario per customer. Use only for testing, never as a feature.",
             "- `sme_indicators`: SME-only monthly tax filing and receivable/payable days.", "",
             "| Scenario | Customers | Expected band |", "|---|---|---|"]
    lines += [f"| {s} | {n} | {expected[s]} |" for s, n in counts.items()]
    (out_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--profile", default="india", choices=sorted(REGION_DATA))
    ap.add_argument("--customers", type=int, default=500)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=None, help="output folder (default data/<profile>)")
    args = ap.parse_args()

    profile = json.loads((ROOT / "config" / "profiles" / f"{args.profile}.json").read_text(encoding="utf-8"))
    defs = json.loads((ROOT / "config" / "risk_signal_definitions.json").read_text(encoding="utf-8"))
    rd = REGION_DATA[args.profile]
    rng = random.Random(args.seed)
    cal = Calendar(date.fromisoformat(profile["as_of"]), profile)
    out = {k: [] for k in [*TABLES, "ground_truth"]}
    ctr = {"L": 0, "R": 0}
    for n, (scen, beh, ctype, over, expected) in enumerate(build_plan(args.customers, rd, rng), start=1):
        gen_customer(f"C{n:04d}", scen, beh, ctype, over, expected, rd, cal, rng, ctr, out)

    tables = {k: pd.DataFrame(out[k]) for k in TABLES}
    out_dir = Path(args.out) if args.out else ROOT / "data" / args.profile
    write_outputs(out_dir, tables, pd.DataFrame(out["ground_truth"]), defs, profile, args.seed, rng)
    print(f"Wrote {out_dir}: " + ", ".join(f"{k}={len(v)}" for k, v in tables.items()))


if __name__ == "__main__":
    main()
