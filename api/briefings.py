"""AI write-ups for the portfolio: cluster briefings and the portfolio risk memo.

Both follow the case-note pattern: a compact, aggregated input (no customer
names), a fixed output schema, checks in code that cited signals and
customers exist and that numbers come from the input, and a rules-based
fallback with the same shape.
"""
from __future__ import annotations

from collections import Counter
import json

import pandas as pd
from pydantic import BaseModel

from api.ai import AIUnavailable, Provider, forbidden_terms, known_numbers, unverified_numbers

BANDS = ["Critical", "High", "Medium", "Low", "Insufficient data"]
ELEVATED = {"Medium", "High", "Critical"}


def money(value: float, currency: str) -> str:
    """Compact amount the model can quote verbatim, e.g. 'INR 37.9 Cr' or 'AED 50.9M'."""
    v = float(value or 0)
    if currency == "INR":
        return f"INR {v / 1e7:.1f} Cr" if v >= 1e7 else f"INR {v / 1e5:.1f} L"
    return f"{currency} {v / 1e6:.1f}M" if v >= 1e6 else f"{currency} {v / 1e3:.0f}K"


# --------------------------------------------------------------------------- cluster briefing
class Driver(BaseModel):
    text: str
    cites: list[str]


class ClusterBriefing(BaseModel):
    headline: str
    pattern: str
    shared_drivers: list[Driver]
    segment_wide: bool
    segment_wide_reason: str
    segment_actions: list[str]
    customers_to_prioritise: list[str]
    caveats: list[str]


CLUSTER_PROMPT = """You brief a credit committee on one portfolio risk cluster from an Early Warning System.

The user message is JSON describing the cluster: the measure that flagged it, band counts, exposure, the most common warning signals, recommended actions and its members (IDs, scores, bands, active signals). Rules:
- Use only facts in the JSON; no invented numbers, causes or names. Quote amounts as written in the input.
- Field meanings: band_counts = customers in each risk band (use it for any count by band; "Medium or above" is Medium + High + Critical). share_of_members_with_flag_pct = share of cluster members showing the measure in flagged_because; share_of_portfolio_with_flag_pct = the same share across the whole book; lift = the ratio of the two. None of these are default rates.
- Never mention default rates, probabilities of default or expected losses: the system measures deterioration, not default.
- headline: one sentence. pattern: 2-3 sentences on what the members have in common and how it differs from the rest of the book.
- shared_drivers: up to 4, each citing signal IDs from the input.
- segment_wide: true if the deterioration looks common across the group rather than a few individual cases; explain in segment_wide_reason using the counts.
- segment_actions: up to 4 actions for the segment as a whole (for example sector limits, enhanced monitoring, RM outreach), consistent with the recommended actions in the input.
- customers_to_prioritise: up to 5 member customer IDs to review first, highest risk first.
- Higher score = higher risk. Never predict defaults."""


def cluster_payload(cluster: dict, signal_names: dict[str, str], actions: dict[str, list], currency: str) -> dict:
    members = cluster["members"]
    bands = Counter(m["band"] for m in members)
    fired = Counter(s for m in members for s in m.get("active_signals", []))
    action_counts = Counter(a.title for m in members for a in actions.get(m["customer_id"], []))
    return {
        "cluster": {"grouping": cluster["dimension"], "value": cluster["value"].replace("|", " · "),
                    "flagged_because": cluster["basis"], "lift": cluster["lift"],
                    "members_with_flag": cluster.get("basis_hits"),
                    "share_of_members_with_flag_pct": round(100 * cluster.get("group_rate", 0), 1),
                    "share_of_portfolio_with_flag_pct": round(100 * cluster.get("portfolio_rate", 0), 1),
                    "customers": cluster["n_customers"], "customers_medium_or_above": cluster["n_elevated"],
                    "elevated_lift": cluster.get("elevated_lift"), "p_value": cluster["p_value"],
                    "exposure": money(cluster["exposure"], currency),
                    "elevated_exposure": money(cluster["elevated_exposure"], currency)},
        "band_counts": {b: bands.get(b, 0) for b in BANDS},
        "common_signals": [{"id": sid, "name": signal_names.get(sid, sid), "customers": n}
                           for sid, n in fired.most_common(6)],
        "recommended_actions": [{"title": t, "customers": n} for t, n in action_counts.most_common(5)],
        "members": [{"id": m["customer_id"], "score": m["score"], "band": m["band"],
                     "outstanding": money(m["total_outstanding"] or 0, currency),
                     "active_signals": m.get("active_signals", [])[:6], "review": m.get("review_decision")}
                    for m in sorted(members, key=lambda m: -(m["score"] or -1))[:25]],
    }


def verify_cluster(b: ClusterBriefing, payload: dict) -> tuple[ClusterBriefing, dict]:
    signal_ids = {s["id"] for s in payload["common_signals"]} | {s for m in payload["members"] for s in m["active_signals"]}
    member_ids = {m["id"] for m in payload["members"]}
    unknown = sorted({c for d in b.shared_drivers for c in d.cites if c not in signal_ids})
    dropped = [c for c in b.customers_to_prioritise if c not in member_ids]
    b = b.model_copy(update={"customers_to_prioritise": [c for c in b.customers_to_prioritise if c in member_ids]})
    text = " ".join([b.headline, b.pattern, b.segment_wide_reason, *b.segment_actions, *b.caveats,
                     *(d.text for d in b.shared_drivers)])
    numbers = unverified_numbers(text, known_numbers(payload))
    terms = forbidden_terms(text)
    checks = {"unknown_citations": unknown, "dropped_customers": dropped, "unverified_numbers": numbers,
              "forbidden_terms": terms}
    checks["status"] = "verified" if not (unknown or dropped or numbers or terms) else "check"
    return b, checks


def template_cluster(payload: dict) -> ClusterBriefing:
    c, bands = payload["cluster"], payload["band_counts"]
    elevated = c["customers_medium_or_above"]
    top = payload["common_signals"][:3]
    widespread = elevated >= max(3, 0.5 * c["customers"])
    return ClusterBriefing(
        headline=f"{c['value']}: {elevated} of {c['customers']} customers are Medium or above.",
        pattern=f"Flagged because of {c['flagged_because']}. Exposure {c['exposure']}, "
                f"of which {c['elevated_exposure']} sits with elevated customers.",
        shared_drivers=[Driver(text=f"{s['name']} active for {s['customers']} customers", cites=[s["id"]]) for s in top],
        segment_wide=widespread,
        segment_wide_reason=(f"{elevated} of {c['customers']} members are Medium or above "
                             f"({bands['Critical']} Critical, {bands['High']} High)."),
        segment_actions=[f"{a['title']} ({a['customers']} customers)" for a in payload["recommended_actions"][:4]],
        customers_to_prioritise=[m["id"] for m in payload["members"] if m["band"] in ELEVATED][:5],
        caveats=["Drafted from rules, not by the AI model."],
    )


def brief_cluster(provider: Provider | None, payload: dict):
    error = None
    if provider is not None:
        try:
            b = provider.parse(CLUSTER_PROMPT, json.dumps(payload, default=str), ClusterBriefing)
            b, checks = verify_cluster(b, payload)
            return b, checks, provider.name, provider.model, None
        except AIUnavailable as e:
            error = str(e)
    b, checks = verify_cluster(template_cluster(payload), payload)
    return b, checks, "template", None, error


# --------------------------------------------------------------------------- portfolio memo
class MemoPoint(BaseModel):
    text: str


class RiskMemo(BaseModel):
    title: str
    headline: str
    key_points: list[MemoPoint]
    changes_since_last: list[str]
    clusters: list[str]
    actions_due: list[str]
    data_quality: str
    recommendations: list[str]


MEMO_PROMPT = """You write a short portfolio risk memo for credit risk management from an Early Warning System assessment.

The user message is JSON: band counts and exposure, the most common warning signals, clusters, open actions by owner, review progress, data quality and, when available, changes since the previous assessment of the same portfolio. Rules:
- Use only facts in the JSON. Quote amounts exactly as written (for example "INR 37.9 Cr"). Do not invent numbers or causes.
- title: "Portfolio risk memo - <portfolio> - <as of date>". headline: one sentence on the overall position.
- key_points: 3-5 points on the main risks. changes_since_last: what moved since the previous assessment, or say there is no earlier assessment.
- clusters: one line per cluster in the input. actions_due: one line per owner with counts.
- data_quality: one sentence. recommendations: up to 4 management actions consistent with the input.
- Higher score = higher risk. Be concise and neutral. Never mention default rates, probabilities of default or expected losses: the system measures deterioration, not default."""


def memo_payload(summary: dict, previous: dict | None, transitions: dict | None, currency: str) -> dict:
    run = summary["run"]
    payload = {
        "portfolio": run["dataset_label"], "profile": run["profile"], "as_of": summary["as_of"],
        "customers": summary["customers"], "band_counts": summary["bands"],
        "exposure_by_band": {b: money(v, currency) for b, v in summary["exposure_by_band"].items()},
        "total_exposure": money(summary["total_exposure"], currency),
        "exposure_at_risk_high_critical": money(summary["exposure_at_risk"], currency),
        "average_confidence_pct": round(100 * summary["average_confidence"]),
        "top_signals": [{"name": s["name"], "customers": s["customers"]} for s in summary["top_signals"]],
        "clusters": [{"name": c["value"].replace("|", " · "), "grouping": c["dimension"],
                      "flagged_because": c["basis"], "lift": c["lift"], "customers": c["n_customers"],
                      "medium_or_above": c["n_elevated"]} for c in summary["clusters"]],
        "actions_by_owner": summary.get("actions", {}).get("by_owner", {}),
        "reviews": summary["reviews"],
        "data_quality": {"issues": summary["quality"]["issue_count"], **summary["quality"]["action"]},
        "previous_assessment": None,
    }
    if previous:
        payload["previous_assessment"] = {
            "created_at": previous["run"]["created_at"][:10], "band_counts": previous["bands"],
            "exposure_at_risk_high_critical": money(previous["exposure_at_risk"], currency),
            **(transitions or {}),
        }
    return payload


def band_transitions(current: pd.DataFrame, previous: pd.DataFrame) -> dict:
    order = {b: i for i, b in enumerate(["Low", "Medium", "High", "Critical"])}
    joined = current[["customer_id", "band"]].merge(previous[["customer_id", "band"]], on="customer_id",
                                                    suffixes=("", "_before"))
    joined = joined[joined["band"].isin(order) & joined["band_before"].isin(order)]
    worse = joined[joined["band"].map(order) > joined["band_before"].map(order)]
    better = joined[joined["band"].map(order) < joined["band_before"].map(order)]
    new_critical = worse[worse["band"] == "Critical"]["customer_id"].tolist()
    return {"customers_worsened": int(len(worse)), "customers_improved": int(len(better)),
            "new_critical_customers": new_critical[:10]}


def verify_memo(m: RiskMemo, payload: dict) -> tuple[RiskMemo, dict]:
    text = " ".join([m.title, m.headline, m.data_quality, *m.changes_since_last, *m.clusters, *m.actions_due,
                     *m.recommendations, *(p.text for p in m.key_points)])
    numbers = unverified_numbers(text, known_numbers(payload))
    terms = forbidden_terms(text)
    return m, {"unverified_numbers": numbers, "forbidden_terms": terms,
               "status": "verified" if not (numbers or terms) else "check"}


def template_memo(payload: dict) -> RiskMemo:
    b, prev = payload["band_counts"], payload["previous_assessment"]
    changes = ["No earlier assessment of this portfolio to compare with."]
    if prev:
        changes = [f"Since {prev['created_at']}: {prev.get('customers_worsened', 0)} customers moved to a worse band "
                   f"and {prev.get('customers_improved', 0)} improved; exposure at risk was "
                   f"{prev['exposure_at_risk_high_critical']}."]
    return RiskMemo(
        title=f"Portfolio risk memo - {payload['portfolio']} - {payload['as_of']}",
        headline=(f"{b['Critical'] + b['High']} of {payload['customers']} customers are High or Critical, holding "
                  f"{payload['exposure_at_risk_high_critical']} of {payload['total_exposure']}."),
        key_points=[MemoPoint(text=f"{s['name']}: active for {s['customers']} customers")
                    for s in payload["top_signals"][:4]],
        changes_since_last=changes,
        clusters=[f"{c['name']} ({c['grouping']}): {c['medium_or_above']} of {c['customers']} Medium or above"
                  for c in payload["clusters"]],
        actions_due=[f"{owner}: {n} open actions" for owner, n in payload["actions_by_owner"].items()],
        data_quality=(f"{payload['data_quality']['issues']} validation issues; "
                      f"{payload['data_quality']['quarantined']} rows quarantined, "
                      f"{payload['data_quality']['repaired']} values repaired."),
        recommendations=["Prioritise review of unreviewed High and Critical alerts.",
                         "Review the detected clusters at the next credit committee."],
    )


def write_memo(provider: Provider | None, payload: dict):
    error = None
    if provider is not None:
        try:
            m = provider.parse(MEMO_PROMPT, json.dumps(payload, default=str), RiskMemo)
            m, checks = verify_memo(m, payload)
            return m, checks, provider.name, provider.model, None
        except AIUnavailable as e:
            error = str(e)
    m, checks = verify_memo(template_memo(payload), payload)
    return m, checks, "template", None, error


def memo_markdown(m: RiskMemo) -> str:
    section = lambda title, items: [f"## {title}", *[f"- {i}" for i in items], ""] if items else []
    lines = [f"# {m.title}", "", m.headline, ""]
    lines += section("Key points", [p.text for p in m.key_points])
    lines += section("Changes since the last assessment", m.changes_since_last)
    lines += section("Risk clusters", m.clusters)
    lines += section("Actions due", m.actions_due)
    lines += ["## Data quality", m.data_quality, ""]
    lines += section("Recommendations", m.recommendations)
    return "\n".join(lines)
