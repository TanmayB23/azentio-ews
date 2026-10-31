"""Evidence checker: does an uploaded document support the reason given for a late payment?

The analyst uploads a salary letter, bank notice, hospital bill or similar
(PDF or image). The model reads it alongside the customer's late instalments
(IDs, dates, amounts, recorded reason; no customer name) and returns a
structured assessment. It never changes a score: the analyst records the
decision (accept or reject the evidence), which is kept append-only.
"""
from __future__ import annotations

import base64
from hashlib import sha256
import json
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel

from api.ai import AIUnavailable, Provider

MEDIA = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp"}
MAX_BYTES = 10 * 1024 * 1024
Verdict = Literal["supports", "partially supports", "does not support", "unreadable", "not assessed"]


class EvidenceAssessment(BaseModel):
    document_type: str
    issuer: str
    document_date: str
    verdict: Verdict
    repayment_ids: list[str]
    matched_details: list[str]
    concerns: list[str]
    summary: str


SYSTEM_PROMPT = """You check whether a document supports the reason a bank customer gave for paying an instalment late.

The user message has the customer's late instalments as JSON (IDs, due dates, payment dates, days late, amounts, any reason already recorded), the analyst's description of the claim, and the document itself. Rules:
- Describe only what the document shows. Do not assume facts that are not visible.
- document_type (e.g. salary delay letter, hospital bill, bank holiday notice), issuer and document_date as printed ("unknown" if not shown).
- verdict: "supports" when the document plausibly explains the delay of the cited instalments (matching period and cause); "partially supports" when it is relevant but dates or details do not fully match; "does not support" when it is unrelated or contradicts the claim; "unreadable" when you cannot read it.
- repayment_ids: the instalment IDs from the input that the document relates to.
- matched_details: specific dates, amounts or names in the document that line up with the instalments or claim.
- concerns: anything suspicious or missing (wrong dates, no letterhead, altered text, a different person's details).
- summary: 2 sentences for the analyst, who makes the decision. Never decide the outcome yourself."""


def late_instalments(repayments: pd.DataFrame, repayment_id: str | None) -> list[dict]:
    df = repayments
    if repayment_id:
        df = df[df["repayment_id"] == repayment_id]
    else:
        df = df[df["dpd"].fillna(0) > 0].sort_values("due_date", ascending=False).head(12)
    cols = ["repayment_id", "loan_id", "due_date", "payment_date", "dpd", "amount_due", "amount_paid",
            "repayment_status", "exception_reason", "exception_evidence_available"]
    out = df[[c for c in cols if c in df.columns]].copy()
    for c in ("due_date", "payment_date"):
        if c in out:
            out[c] = pd.to_datetime(out[c], errors="coerce").dt.strftime("%Y-%m-%d")
    return json.loads(out.to_json(orient="records"))


def save_file(var_dir: Path, filename: str, data: bytes) -> tuple[str, str]:
    """Store the document by content hash; returns (sha, media type)."""
    suffix = Path(filename).suffix.lower()
    if suffix not in MEDIA:
        raise ValueError("Upload a PDF, PNG, JPG or WebP file")
    if len(data) > MAX_BYTES:
        raise ValueError("The document is larger than 10 MB")
    digest = sha256(data).hexdigest()[:24]
    folder = var_dir / "evidence"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{digest}{suffix}"
    if not path.exists():
        path.write_bytes(data)
    return digest, MEDIA[suffix]


def content_parts(context: dict, filename: str, media: str, data: bytes) -> list[dict]:
    encoded = base64.b64encode(data).decode()
    doc = {"type": "file", "file": {"filename": filename, "file_data": f"data:{media};base64,{encoded}"}} \
        if media == "application/pdf" else {"type": "image_url", "image_url": {"url": f"data:{media};base64,{encoded}"}}
    return [{"type": "text", "text": json.dumps(context, default=str)}, doc]


def verify(a: EvidenceAssessment, context: dict) -> tuple[EvidenceAssessment, dict]:
    known = {r["repayment_id"] for r in context["late_instalments"]}
    unknown = [r for r in a.repayment_ids if r not in known]
    a = a.model_copy(update={"repayment_ids": [r for r in a.repayment_ids if r in known]})
    return a, {"unknown_repayments": unknown, "status": "verified" if not unknown else "check"}


def not_assessed(reason: str) -> EvidenceAssessment:
    return EvidenceAssessment(document_type="unknown", issuer="unknown", document_date="unknown",
                              verdict="not assessed", repayment_ids=[], matched_details=[], concerns=[reason],
                              summary="The document was stored but not read automatically. Open it and record "
                                      "your decision below.")


def assess(provider: Provider | None, context: dict, filename: str, media: str, data: bytes):
    if provider is None:
        a = not_assessed("No AI model is configured, so the document was not read.")
        return a, {"unknown_repayments": [], "status": "verified"}, "template", None, None
    try:
        a = provider.parse(SYSTEM_PROMPT, content_parts(context, filename, media, data), EvidenceAssessment,
                           max_tokens=2000)
        a, checks = verify(a, context)
        return a, checks, provider.name, provider.model, None
    except AIUnavailable as e:
        a = not_assessed(f"The AI check failed: {e}")
        return a, {"unknown_repayments": [], "status": "verified"}, "template", None, str(e)
