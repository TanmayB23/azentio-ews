"""AI case notes: a grounded draft of findings and next steps for one alert.

The model only sees the saved alert, the recommended actions that already
fired from the playbook, and a few profile facts (no customer name unless
EWS_AI_SEND_NAMES=1). Its output is a fixed schema. Afterwards the code checks
that every cited ID exists in the input, that recommended actions come from the
playbook, and that numbers in the text appear in the input. Without an API key
(or if the call fails) a deterministic note is built from the same input, so
the feature always works.
"""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
import os
import re
from typing import Literal

from pydantic import BaseModel

from ews.contracts import CustomerResult
from ews.interventions import Recommendation
from ews.store.db import DECISIONS

PROMPT_VERSION = "case-note-2026-10-31.2"
Decision = Literal["Continue Monitoring", "Requires Investigation", "False Positive", "Escalate for Review"]
assert set(Decision.__args__) == set(DECISIONS)


# --------------------------------------------------------------------------- schema
class Finding(BaseModel):
    text: str
    cites: list[str]


class ActionPick(BaseModel):
    action_id: str
    reason: str
    cites: list[str]


class CaseNote(BaseModel):
    summary: str
    key_findings: list[Finding]
    recommended_actions: list[ActionPick]
    questions_for_customer: list[str]
    data_gaps: list[str]
    suggested_decision: Decision
    suggested_decision_reason: str
    caveats: list[str]


SYSTEM_PROMPT = """You draft case notes for credit risk analysts inside a bank's Early Warning System.

The user message is a JSON record for one customer alert. Write a case note for the analyst who will review it.

Rules:
- Use only facts in the JSON. Do not invent numbers, dates, causes, names or customer details. If something is unknown, say so in data_gaps or caveats.
- The score runs 0-100 and a higher score means higher risk. Never change or re-derive the score or band, and never predict default.
- Each key finding cites the IDs it relies on, copied exactly from the input: signal IDs (e.g. "CF01"), evidence IDs (e.g. "R001168" or "2026-07"), adjustment IDs (e.g. "ADJ1") or action IDs. Cite IDs only, never field names.
- recommended_actions: choose only from input.recommended_actions by action_id, most urgent first, each with a reason linked to the findings. Never add an action that is not in the input; return an empty list if the input has none.
- suggested_decision is a suggestion for the analyst, who decides. Escalate for Review fits Critical alerts or roll-forward risk; Requires Investigation fits High alerts or unexplained deterioration; Continue Monitoring fits Medium/Low or recovering customers and insufficient data; False Positive fits alerts where the evidence shows the signals do not reflect real deterioration (for example a documented one-off delay or a seasonal pattern).
- data_gaps: evidence that is missing or not evaluated, from signals whose status is "Missing data".
- Write plainly for a credit analyst. Summary: at most 3 sentences. At most 5 findings and 4 questions."""


# --------------------------------------------------------------------------- input
def build_payload(result: CustomerResult, actions: list[Recommendation], profile: dict, row: dict | None,
                  clusters: list[str]) -> dict:
    row = row or {}
    customer = {k: row.get(k) for k in ("customer_type", "segment", "portfolio", "industry", "region",
                                        "main_product", "total_outstanding", "current_dpd", "delinquency_bucket")}
    if os.environ.get("EWS_AI_SEND_NAMES") == "1":
        customer["customer_name"] = row.get("customer_name")
    signals = []
    for s in result.signals:
        if not s.applicable:
            continue
        status = "Missing data" if not s.evaluated else "Active" if s.points > 0 else "No warning"
        signals.append({"id": s.signal_id, "name": s.name, "status": status,
                        "value": None if s.value is None else round(s.value, 2), "trigger": s.trigger,
                        "full_strength_at": s.saturation, "points": round(s.points, 1),
                        "evidence": s.evidence[:8], "reason_not_evaluated": s.reason_not_evaluated})
    return {
        "alert": {"customer_id": result.customer_id, "as_of": result.as_of, "profile": profile.get("profile"),
                  "currency": profile.get("currency"), "status": result.status, "score": result.score,
                  "band": result.band, "monitoring_status": result.monitoring_status,
                  "confidence": result.confidence, "area_scores": result.pillar_scores,
                  "summary": result.summary,
                  "adjustments": [{"id": f"ADJ{i}", "text": m} for i, m in enumerate(result.modifiers, 1)]},
        "customer": customer,
        "signals": signals,
        "clusters": clusters,
        "recommended_actions": [{"action_id": a.action_id, "title": a.title, "owner": a.owner,
                                 "due_date": a.due_date, "reasons": a.reasons} for a in actions],
    }


def input_hash(payload: dict, source: str) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str) + PROMPT_VERSION + source
    return sha256(blob.encode()).hexdigest()[:24]


# --------------------------------------------------------------------------- checks
_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[float]:
    out = set()
    for tok in _NUM.findall(text):
        try:
            out.add(float(tok.replace(",", "")))
        except ValueError:
            pass
    return out


def verify(note: CaseNote, payload: dict) -> tuple[CaseNote, dict]:
    """Drop actions not in the playbook and flag citations or numbers not found in the input."""
    allowed_ids = {s["id"] for s in payload["signals"]} | {a["action_id"] for a in payload["recommended_actions"]}
    allowed_ids |= {a["id"] for a in payload["alert"]["adjustments"]}
    for s in payload["signals"]:
        allowed_ids |= set(map(str, s["evidence"]))
    action_ids = {a["action_id"] for a in payload["recommended_actions"]}

    dropped = [a.action_id for a in note.recommended_actions if a.action_id not in action_ids]
    note = note.model_copy(update={"recommended_actions": [a for a in note.recommended_actions
                                                           if a.action_id in action_ids]})
    cited = [c for f in note.key_findings for c in f.cites] + [c for a in note.recommended_actions for c in a.cites]
    unknown = sorted({c for c in cited if c not in allowed_ids})

    known = set()
    for n in _numbers(json.dumps(payload, default=str)):
        known |= {n, abs(n), round(n), round(abs(n)), round(n, 1), round(abs(n), 1)}
    text = " ".join([note.summary, note.suggested_decision_reason, *note.caveats, *note.questions_for_customer,
                     *note.data_gaps, *(f.text for f in note.key_findings), *(a.reason for a in note.recommended_actions)])
    unverified = sorted({n for n in _numbers(text)
                         if n > 12 and not 1990 <= n <= 2100 and n not in known and round(n) not in known})

    checks = {"unknown_citations": unknown, "dropped_actions": dropped,
              "unverified_numbers": [int(n) if n == int(n) else n for n in unverified]}
    checks["status"] = "verified" if not (unknown or dropped or unverified) else "check"
    return note, checks


# --------------------------------------------------------------------------- fallback
_QUESTIONS = {
    "COLLECTIONS_CONTACT": "What has stopped the recent instalments being paid, and what amount can be paid by when?",
    "RM_REPAYMENT_CALL": "Why have recent payments been late or partial, and is the cause temporary?",
    "RM_CASHFLOW_REVIEW": "What explains the fall in account inflows, and how long is it expected to last?",
    "FREEZE_LIMITS": "What were the new facilities or the higher utilisation used for?",
    "SME_DOCUMENTS": "Can you share the latest tax returns and an aged list of amounts owed by your customers?",
    "REQUEST_EVIDENCE": "Can you provide a document explaining the late payment?",
    "COLLECT_DATA": "Can you provide statements or records covering the missing months?",
}


def template_note(payload: dict) -> CaseNote:
    alert = payload["alert"]
    active = sorted((s for s in payload["signals"] if s["status"] == "Active"), key=lambda s: -s["points"])
    findings = [Finding(text=f"{s['name']}: measured {s['value']} against a trigger of {s['trigger']} "
                             f"({s['points']} points).", cites=[s["id"], *map(str, s["evidence"][:3])])
                for s in active[:5]]
    for adj in alert["adjustments"][:2]:
        findings.append(Finding(text=adj["text"], cites=[adj["id"]]))
    actions = [ActionPick(action_id=a["action_id"], reason="; ".join(a["reasons"]) or a["title"], cites=[])
               for a in payload["recommended_actions"]]
    band, adjustments = alert["band"], " ".join(a["text"] for a in alert["adjustments"])
    if alert["status"] == "Insufficient data":
        decision, why = "Continue Monitoring", "Not enough history to assess risk; collect the missing data first."
    elif band == "Critical" or "Roll-forward" in adjustments:
        decision, why = "Escalate for Review", "Critical band or worsening delinquency."
    elif band == "High":
        decision, why = "Requires Investigation", "High band; the cause of the deterioration needs confirming."
    else:
        decision, why = "Continue Monitoring", f"{band} band; keep under routine or watch monitoring."
    return CaseNote(
        summary=alert["summary"],
        key_findings=findings[:5],
        recommended_actions=actions,
        questions_for_customer=[_QUESTIONS[a["action_id"]] for a in payload["recommended_actions"]
                                if a["action_id"] in _QUESTIONS][:4],
        data_gaps=[f"{s['name']}: {s['reason_not_evaluated'] or 'not evaluated'}"
                   for s in payload["signals"] if s["status"] == "Missing data"],
        suggested_decision=decision,
        suggested_decision_reason=why,
        caveats=["Drafted from rules, not by the AI model: this note restates the alert and playbook."],
    )


# --------------------------------------------------------------------------- providers
# shared with the other AI features (api/ai.py); re-exported for existing imports
from api.ai import AIUnavailable, OpenAIProvider, Provider, provider_from_env  # noqa: E402,F401


def draft(provider: Provider | None, payload: dict) -> tuple[CaseNote, dict, str, str | None, str | None]:
    """Returns (note, checks, source, model, error)."""
    error = None
    if provider is not None:
        try:
            note, checks = verify(provider.draft(SYSTEM_PROMPT, payload), payload)
            return note, checks, provider.name, provider.model, None
        except AIUnavailable as e:
            error = str(e)
    note, checks = verify(template_note(payload), payload)
    return note, checks, "template", None, error


def recommendation_dicts(actions: list[Recommendation]) -> list[dict]:
    return [asdict(a) for a in actions]
