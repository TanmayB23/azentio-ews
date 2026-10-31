"""Shared data contract between the engine (Person A) and the app (Person B).

Change this file only when both sides agree. New fields must be optional
(have a default) so the other side keeps working.

Score convention: 0-100, higher = riskier.
Bands: Low 0-24, Medium 25-49, High 50-74, Critical 75-100.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

TABLES = ("customers", "facilities", "repayments", "delinquency", "exposure", "transactions", "sme_indicators")
OPTIONAL_TABLES = ("sme_indicators",)       # absent table = signals not applicable, not an error
Pillar = Literal["RB", "CF", "EX", "SM"]
Band = Literal["Low", "Medium", "High", "Critical"]


@dataclass
class ValidationIssue:
    table: str
    record_key: str                          # customer_id / loan_id / repayment_id / "C0001|2026-07"
    field: str | None
    issue: str
    severity: Literal["error", "warning"]
    action: Literal["quarantined", "kept", "repaired"]


@dataclass
class Dataset:
    tables: dict[str, pd.DataFrame]          # validated, typed tables keyed by TABLES
    issues: list[ValidationIssue]
    quarantined: dict[str, pd.DataFrame]     # rows removed from tables, with an "issue" column
    signal_config: dict | None = None        # uploaded risk_signal_definitions, if any


@dataclass
class SignalResult:
    signal_id: str
    name: str
    pillar: Pillar
    evaluated: bool
    reason_not_evaluated: str | None
    value: float | None
    trigger: float
    saturation: float
    strength: float                          # 0-1 after modifiers
    weight: float
    points: float                            # contribution to the final score (before rule floors)
    evidence: list[str]                      # repayment_ids / months used
    applicable: bool = True                  # False = signal does not apply (e.g. no revolving facility)


@dataclass
class CustomerResult:
    customer_id: str
    as_of: str
    rules_version: str
    status: Literal["Scored", "Insufficient data"]
    score: float | None                      # 0-100, higher = riskier; None when insufficient
    band: Band | None
    monitoring_status: str                   # Routine / Watch / Investigate / Escalate / Collect data
    confidence: float                        # 0-1 share of applicable signal weight evaluated
    pillar_scores: dict[str, float]
    signals: list[SignalResult]
    modifiers: list[str]                     # dampeners and rule floors applied, in plain English
    summary: str


@dataclass
class Cluster:
    dimension: str                           # e.g. "industry x region"
    value: str                               # e.g. "Textiles|Tamil Nadu"
    n_customers: int
    n_elevated: int                          # customers scoring Medium or above
    lift: float                              # elevated rate in group / elevated rate in portfolio
    top_signals: list[str]
    customer_ids: list[str]
    p_value: float = 1.0                     # one-sided binomial test vs portfolio rate
    basis: str = "elevated risk"             # or "shared signal CF04 (...)" for early-stage clusters
