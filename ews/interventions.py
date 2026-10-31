"""Recommended interventions from config/interventions.json.

Rules are evaluated in file order against a saved alert. Each condition that
holds contributes a plain-English reason, and the signal IDs behind it, so a
recommendation can always be traced back to evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
import json
from pathlib import Path
import re

from ews.contracts import Cluster, CustomerResult, Dataset

CONFIG = Path(__file__).resolve().parents[1] / "config" / "interventions.json"


@dataclass
class Facts:
    """Context outside the alert itself."""
    profile: str
    current_dpd: float = 0.0
    clusters: list[str] = field(default_factory=list)


@dataclass
class Recommendation:
    action_id: str
    title: str
    owner: str
    priority: int
    due_days: int
    due_date: str
    detail: str
    reasons: list[str]
    cites: list[str]


def load_playbook(path: Path = CONFIG) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# Segment and portfolio clusters are too broad to justify a sector review per customer.
SECTOR_DIMENSIONS = ("industry x region", "industry", "region", "product")


def customer_facts(ds: Dataset, clusters: list[Cluster], profile: str) -> dict[str, Facts]:
    dq = ds.tables["delinquency"]
    worst = dq.groupby("customer_id")["current_dpd"].max() if not dq.empty else {}
    member: dict[str, list[str]] = {}
    for c in clusters:
        if c.dimension in SECTOR_DIMENSIONS:
            for cid in c.customer_ids:
                member.setdefault(cid, []).append(c.value.replace("|", " · "))
    out = {}
    for cid in ds.tables["customers"]["customer_id"]:
        dpd = worst.get(cid, 0) if len(worst) else 0
        out[cid] = Facts(profile, float(dpd) if dpd == dpd else 0.0, member.get(cid, []))
    return out


def recommend(result: CustomerResult, facts: Facts, playbook: dict | None = None) -> list[Recommendation]:
    playbook = playbook or load_playbook()
    active = {s.signal_id: s for s in result.signals if s.evaluated and s.points > 0}
    fired: dict[str, Recommendation] = {}
    for rule in playbook["rules"]:
        action_id = rule["action"]
        if action_id in fired:
            continue
        outcomes = [_check(key, value, result, facts, active, fired) for key, value in rule["when"].items()]
        hit = all(o is not None for o in outcomes) if rule.get("match", "all") == "all" \
            else any(o is not None for o in outcomes)
        if not hit:
            continue
        reasons, cites = [], []
        for o in outcomes:
            if o and o[0]:
                reasons.append(o[0])
                cites += [c for c in o[1] if c not in cites]
        spec = playbook["actions"][action_id]
        due = date.fromisoformat(result.as_of) + timedelta(days=spec["due_days"])
        fired[action_id] = Recommendation(action_id, spec["title"], spec["owner"], spec["priority"],
                                          spec["due_days"], due.isoformat(), spec["detail"], reasons, cites)
    return sorted(fired.values(), key=lambda r: (r.priority, r.due_days))


def _check(key, value, result: CustomerResult, facts: Facts, active: dict, fired: dict):
    """Return (reason, cites) when the condition holds, ("", []) when it holds silently, else None."""
    pillars = result.pillar_scores
    if key == "modifier_starts":
        hits = [m for m in result.modifiers if any(m.startswith(v) for v in value)]
        return (hits[0].split(":")[0] + ": " + hits[0].split(":", 1)[-1].strip(), _rb(active)) if hits else None
    if key == "modifier_contains":
        hits = [m for m in result.modifiers if any(v in m for v in value)]
        return (hits[0].split(":")[0], []) if hits else None
    if key == "dampened_delay_min_days":
        for m in result.modifiers:
            found = re.search(r"Isolated late payment in (\S+) \((\d+) days", m)
            if found and int(found.group(2)) >= value:
                return (f"Late payment in {found.group(1)} was {found.group(2)} days", _rb(active))
        return None
    if key == "no_modifier_contains":
        return None if any(v in m for m in result.modifiers for v in value) else ("", [])
    if key == "current_dpd_gt":
        return (f"Currently {facts.current_dpd:.0f} days past due", ["RB04"]) if facts.current_dpd > value else None
    if key == "pillar_min":
        for name, threshold in value.items():
            score = pillars.get(name)
            if score is None or score < threshold:
                return None
        names = list(value)
        cites = [sid for sid, s in active.items() if _pillar_name(s.pillar) in names]
        return ("; ".join(f"{n} risk {pillars[n]:.0f}/100" for n in names), cites)
    if key == "signals_active":
        hits = [sid for sid in value if sid in active]
        return ("Active: " + ", ".join(active[s].name for s in hits), hits) if hits else None
    if key == "status":
        if result.status != value:
            return None
        missing = sorted({s.name for s in result.signals if s.applicable and not s.evaluated})
        return (f"{result.status}; missing evidence for: {', '.join(missing[:4])}", [])
    if key == "bands":
        return ("", []) if result.band in value else None
    if key == "in_cluster":
        if bool(facts.clusters) != value:
            return None
        return ("Member of risk cluster " + ", ".join(facts.clusters), []) if value else ("", [])
    if key == "profiles":
        return ("", []) if facts.profile in value else None
    if key == "actions_fired":
        hits = [a for a in value if a in fired]
        return ("Region profile requires Shariah-compliant restructuring", []) if hits else None
    if key == "actions_not_fired":
        return None if any(a in fired for a in value) else ("", [])
    if key == "no_other_actions":
        return ("No more specific action applies", []) if (not fired) == value else None
    raise ValueError(f"Unknown intervention condition '{key}'")


_PILLARS = {"RB": "Repayment", "CF": "Cash flow", "EX": "Exposure", "SM": "Business", "UB": "Unusual behaviour"}


def _pillar_name(code: str) -> str:
    return _PILLARS.get(code, code)


def _rb(active: dict) -> list[str]:
    return [sid for sid, s in active.items() if s.pillar == "RB"]
