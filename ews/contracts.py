"""Shared interface from EWS_TEAM_PLAN.md. Coordinate changes with Person A."""
from dataclasses import dataclass
from typing import Literal
import pandas as pd

@dataclass
class ValidationIssue:
    table: str
    record_key: str
    field: str | None
    issue: str
    severity: Literal["error", "warning"]
    action: Literal["quarantined", "kept"]

@dataclass
class Dataset:
    tables: dict[str, pd.DataFrame]
    issues: list[ValidationIssue]
    quarantined: dict[str, pd.DataFrame]

@dataclass
class SignalResult:
    signal_id: str
    name: str
    pillar: Literal["RB", "CF", "EX"]
    evaluated: bool
    reason_not_evaluated: str | None
    value: float | None
    trigger: float
    saturation: float
    strength: float
    weight: float
    points: float
    evidence: list[str]

@dataclass
class CustomerResult:
    customer_id: str
    as_of: str
    rules_version: str
    status: Literal["Scored", "Insufficient data"]
    score: float | None
    band: Literal["Low", "Medium", "High", "Critical"] | None
    monitoring_status: str
    confidence: float
    pillar_scores: dict[str, float]
    signals: list[SignalResult]
    modifiers: list[str]
    summary: str

@dataclass
class Cluster:
    dimension: str
    value: str
    n_customers: int
    n_elevated: int
    lift: float
    top_signals: list[str]
    customer_ids: list[str]
