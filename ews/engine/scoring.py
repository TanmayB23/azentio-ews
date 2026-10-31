"""Turns signal results into an Early Warning Score.

1. Score each pillar (RB repayment, CF cash flow, EX exposure) 0-100 from the
   signals that could be evaluated in it.
2. Combine: highest pillar + 0.35 x second + 0.15 x third (profile-configurable),
   so one severe pillar can reach High and breadth pushes towards Critical.
3. Modifiers: temporary-miss dampener on repayment signals, roll-forward and
   recent-episode minimum scores.
4. Confidence = share of applicable signal weight evaluated; too little data
   gives status "Insufficient data" instead of a band.
"""
from __future__ import annotations

import pandas as pd

from ews.contracts import CustomerResult, Dataset, SignalResult
from ews.engine.config import load_profile, load_signal_definitions
from ews.engine.explain import summarise
from ews.engine.loader import DEFAULT_CLASSIFICATION
from ews.engine.signals import evaluate_signals
from ews.engine.views import CustomerViews, build_views, month_labels

PILLARS = ("RB", "CF", "EX")
PILLAR_NAMES = {"RB": "Repayment", "CF": "Cash flow", "EX": "Exposure"}
INSUFFICIENT_STATUS = "Collect data"


def score_portfolio(ds: Dataset, profile: str | dict = "india", as_of: str | None = None) -> list[CustomerResult]:
    prof = load_profile(profile) if isinstance(profile, str) else profile
    defs = _definitions(ds.signal_config)
    as_of_ts = pd.Timestamp(as_of or prof["as_of"])
    views = build_views(ds, as_of_ts, prof)
    version = f"signals:{defs.get('version', '?')}|profile:{prof['profile']}@{prof.get('version', '?')}"
    return [score_customer(v, defs, prof, as_of_ts, version) for v in views.values()]


def score_customer(v: CustomerViews, defs: dict, prof: dict, as_of: pd.Timestamp, version: str) -> CustomerResult:
    cfg = prof["scoring"]
    signals = evaluate_signals(v, defs, as_of)
    modifiers: list[str] = []

    damp = _temporary_miss(v, defs["modifiers"]["temporary_missed_payment_dampener"], as_of)
    if damp:
        mult, text = damp
        for s in signals:
            if s.pillar == "RB" and s.evaluated:
                s.strength *= mult
        modifiers.append(text)

    pillar_scores, pillar_weight = {}, {}
    for p in PILLARS:
        applicable = [s for s in signals if s.pillar == p and s.applicable]
        app_w = sum(s.weight for s in applicable)
        ev = [s for s in applicable if s.evaluated]
        ev_w = sum(s.weight for s in ev)
        if app_w == 0 or not ev:
            continue
        if ev_w / app_w < cfg["min_pillar_coverage"]:
            modifiers.append(f"{PILLAR_NAMES[p]} pillar not scored: only {ev_w:.0f} of {app_w:.0f} "
                             "signal weight has enough data")
            continue
        pillar_scores[p] = 100 * sum(s.weight * s.strength for s in ev) / ev_w
        pillar_weight[p] = ev_w

    factors = cfg["pillar_combination"]
    ranked = sorted(pillar_scores, key=pillar_scores.get, reverse=True)
    for rank, p in enumerate(ranked):
        f = factors[rank] if rank < len(factors) else 0.0
        for s in signals:
            if s.pillar == p and s.evaluated:
                s.points = round(f * 100 * s.weight * s.strength / pillar_weight[p], 2)
    score = min(100.0, sum(s.points for s in signals))

    rm = v.repay_months
    floor = _roll_forward(rm, cfg["roll_forward"])
    if floor:
        modifiers.append(floor[1])
        score = max(score, floor[0])
    elif not damp:
        floor = _recent_episode(rm, cfg["recent_episode"], as_of)
        if floor and score < floor[0]:
            modifiers.append(floor[1])
            score = floor[0]

    app_total = sum(s.weight for s in signals if s.applicable)
    confidence = sum(s.weight for s in signals if s.applicable and s.evaluated) / app_total if app_total else 0.0
    insufficient = len(rm) < cfg["min_repayment_months"] or confidence < cfg["min_confidence"]

    classification = defs.get("classification") or DEFAULT_CLASSIFICATION
    result = CustomerResult(
        customer_id=v.customer["customer_id"], as_of=as_of.date().isoformat(), rules_version=version,
        status="Insufficient data" if insufficient else "Scored",
        score=None if insufficient else round(score, 1),
        band=None, monitoring_status=INSUFFICIENT_STATUS,
        confidence=round(confidence, 2),
        pillar_scores={PILLAR_NAMES[p]: round(s, 1) for p, s in pillar_scores.items()},
        signals=signals, modifiers=modifiers, summary="",
    )
    if not insufficient:
        result.band, result.monitoring_status = _classify(result.score, classification)
    result.summary = summarise(result, v, defs)
    return result


def _definitions(uploaded: dict | None) -> dict:
    base = load_signal_definitions()
    if not uploaded:
        return base
    merged = dict(base)
    merged.update({k: v for k, v in uploaded.items() if v})
    merged["modifiers"] = uploaded.get("modifiers") or base["modifiers"]
    # uploaded thresholds/weights win; tuning keys only in config (e.g. CF01 series) are kept
    base_by_id = {s["signal_id"]: s for s in base["signals"]}
    merged["signals"] = [{**base_by_id.get(s["signal_id"], {}), **s} for s in uploaded["signals"]]
    return merged


def _classify(score: float, classification: list[dict]) -> tuple[str, str]:
    for c in classification:
        if score <= c["max"] + 0.999:
            return c["category"], c["monitoring_status"]
    return classification[-1]["category"], classification[-1]["monitoring_status"]


def _temporary_miss(v: CustomerViews, rule: dict, as_of) -> tuple[float, str] | None:
    """One late month in the window, clean before it, recovered after it."""
    rm = v.repay_months
    if rm.empty:
        return None
    window = set(month_labels(as_of, 6))
    late = rm[rm["late"] & rm["month"].isin(window)]
    if len(late) != 1 or len(late) > rule["applies_when"]["late_instalments_in_window_max"]:
        return None
    pos = late.index[0]
    need_before = rule["applies_when"]["clean_instalments_before_min"]
    before = rm.iloc[max(0, pos - need_before):pos]
    after = rm.iloc[pos + 1:pos + 1 + rule["applies_when"]["recovered_within_instalments"]]
    if len(before) < need_before or before["late"].any():
        return None
    if after.empty or after["unpaid"].any() or not (after["dpd"] == 0).any() or rm.iloc[-1]["unpaid"]:
        return None
    row = late.iloc[0]
    evid = bool(row["evidence"])
    mult = rule["multiplier_on_repayment_signals_with_evidence"] if evid else \
        rule["multiplier_on_repayment_signals_without_evidence"]
    reason = row["exception_reason"] or "no reason recorded"
    return mult, (f"Isolated late payment in {row['month']} ({row['dpd']:.0f} days; {reason}; "
                  f"evidence {'on file' if evid else 'not provided'}), clean before and recovered after: "
                  f"repayment signals x{mult}")


def _roll_forward(rm: pd.DataFrame, rule: dict) -> tuple[float, str] | None:
    """Currently unpaid after a run of late payments whose delays are not shrinking."""
    k = rule["lookback_instalments"]
    if len(rm) < k + 1 or not rm.iloc[-1]["unpaid"]:
        return None
    prev = rm.iloc[-1 - k:-1]
    late = prev[prev["late"]]
    if len(late) < rule["min_late"] or not late["dpd"].is_monotonic_increasing:
        return None
    delays = "/".join(f"{d:.0f}" for d in prev["dpd"])
    return rule["min_score"], (f"Roll-forward risk: delays {delays} days over the previous {k} instalments, "
                               f"latest instalment ({rm.iloc[-1]['month']}) unpaid: score raised to at least "
                               f"{rule['min_score']}")


def _recent_episode(rm: pd.DataFrame, rule: dict, as_of) -> tuple[float, str] | None:
    w = rm[rm["month"].isin(month_labels(as_of, 6))]
    late = w[w["late"]]
    if len(late) < rule["min_late"] or late["dpd"].max() < rule["min_dpd"]:
        return None
    return rule["min_score"], (f"Recent delinquency episode: {len(late)} late instalments in 6 months, worst "
                               f"{late['dpd'].max():.0f} days: score raised to at least {rule['min_score']}")
