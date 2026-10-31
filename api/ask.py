"""Ask EWS: turn a plain-English question into watchlist filters.

The model only chooses filter values from the lists it is given (the
assessment's own facets and signal catalogue); anything else is dropped in
code. Results always come from the data via the normal watchlist filters,
never from the model. Without a provider, a keyword matcher does the same job.
"""
from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel

from api.ai import AIUnavailable, Provider

LIST_FILTERS = ("band", "main_product", "segment", "portfolio", "delinquency_bucket", "customer_type", "region",
                "industry", "signals")
SORTS = ("score", "total_outstanding", "current_dpd", "confidence", "customer_name")


class WatchQuery(BaseModel):
    search: str
    band: list[str]
    main_product: list[str]
    segment: list[str]
    portfolio: list[str]
    delinquency_bucket: list[str]
    customer_type: list[str]
    region: list[str]
    industry: list[str]
    signals: list[str]
    score_min: float | None
    score_max: float | None
    review: Literal["", "reviewed", "unreviewed"]
    sort: Literal["score", "total_outstanding", "current_dpd", "confidence", "customer_name"]
    order: Literal["asc", "desc"]
    explanation: str
    unsupported: list[str]


SYSTEM_PROMPT = """You turn a credit analyst's question into filters for an Early Warning System watchlist.

The user message has the question and the allowed values for every filter. Rules:
- Use only values from the allowed lists, copied exactly. Leave a filter empty when the question does not mention it.
- "signals" holds signal IDs (e.g. "SM02") whose warning should be active; choose them from the catalogue by meaning.
- Bands: Low, Medium, High, Critical, Insufficient data. "Elevated", "at risk" or "risky" means Medium, High and Critical unless the question says otherwise. Scores run 0-100, higher is riskier.
- review: "unreviewed" for not yet reviewed, "reviewed" for already reviewed, otherwise "".
- search: only a customer ID or name the question names; otherwise "".
- sort/order: what to rank by. Default score, desc. "Biggest" or "largest exposure" means total_outstanding desc.
- explanation: one plain sentence describing the filters you chose.
- unsupported: parts of the question these filters cannot express (for example dates or comparisons with other assessments)."""


def build_options(facets: dict, signal_names: dict[str, str]) -> dict:
    return {**{k: v for k, v in facets.items() if k in LIST_FILTERS},
            "signals": [{"id": sid, "name": name} for sid, name in sorted(signal_names.items())],
            "sort": list(SORTS)}


def clean(query: WatchQuery, options: dict) -> tuple[dict, list[str]]:
    """Keep only allowed values; returns (filters, dropped values)."""
    allowed = {k: set(v) for k, v in options.items() if k in LIST_FILTERS and k != "signals"}
    allowed["signals"] = {s["id"] for s in options["signals"]}
    filters, dropped = {}, []
    for key in LIST_FILTERS:
        values = getattr(query, key)
        filters[key] = [v for v in values if v in allowed.get(key, set())]
        dropped += [f"{key}={v}" for v in values if v not in allowed.get(key, set())]
    for key in ("score_min", "score_max"):
        value = getattr(query, key)
        filters[key] = value if value is not None and 0 <= value <= 100 else None
    filters.update(q=query.search.strip(), review=query.review, sort=query.sort, order=query.order)
    return filters, dropped


def keyword_query(question: str, options: dict) -> WatchQuery:
    """Deterministic fallback: match facet values and signal names that appear in the question."""
    text = question.lower()
    found = {k: [v for v in vals if isinstance(v, str) and len(v) > 2 and re.search(rf"\b{re.escape(v.lower())}\b", text)]
             for k, vals in options.items() if k in LIST_FILTERS and k != "signals"}
    if not found.get("band") and re.search(r"\b(elevated|at risk|risky)\b", text):
        found["band"] = [b for b in ("Medium", "High", "Critical") if b in options.get("band", [])]
    if re.search(r"\bsmes?\b", text) and "SME" in options.get("customer_type", []):
        found["customer_type"] = ["SME"]
    signals = [s["id"] for s in options["signals"]
               if s["id"].lower() in text or (len(s["name"]) > 6 and s["name"].lower().split(" (")[0] in text)]
    review = "unreviewed" if re.search(r"\b(not|un|never)[\s-]?reviewed\b|\bno review", text) else \
        "reviewed" if "reviewed" in text else ""
    ident = re.search(r"\bC\d{4}\b", question, re.IGNORECASE)
    biggest = re.search(r"\b(largest|biggest|exposure|outstanding)\b", text)
    parts = [f"{k.replace('_', ' ')}: {', '.join(v)}" for k, v in found.items() if v]
    parts += [f"active signal: {', '.join(signals)}"] if signals else []
    parts += [f"review: {review}"] if review else []
    parts += [f"customer: {ident.group(0).upper()}"] if ident else []
    return WatchQuery(
        search=ident.group(0).upper() if ident else "",
        band=found.get("band", []), main_product=found.get("main_product", []), segment=found.get("segment", []),
        portfolio=found.get("portfolio", []), delinquency_bucket=found.get("delinquency_bucket", []),
        customer_type=found.get("customer_type", []), region=found.get("region", []),
        industry=found.get("industry", []), signals=signals, score_min=None, score_max=None, review=review,
        sort="total_outstanding" if biggest else "score", order="desc",
        explanation=("Matched keywords: " + "; ".join(parts)) if parts else "No filter words recognised; showing everyone.",
        unsupported=[])


def interpret(provider: Provider | None, question: str, options: dict) -> tuple[dict, dict, str, str | None, str | None]:
    """Returns (filters, meta, source, model, error)."""
    error = None
    query = None
    if provider is not None:
        try:
            content = json.dumps({"question": question, "allowed": options})
            query = provider.parse(SYSTEM_PROMPT, content, WatchQuery, max_tokens=1500)
            source, model = provider.name, provider.model
        except AIUnavailable as e:
            error = str(e)
    if query is None:
        query, source, model = keyword_query(question, options), "keywords", None
    filters, dropped = clean(query, options)
    meta = {"explanation": query.explanation, "unsupported": query.unsupported, "dropped": dropped}
    return filters, meta, source, model, error
