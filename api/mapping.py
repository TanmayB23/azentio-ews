"""Column mapping for uploads that use a bank's own column names.

The proposal (from the model, or a fuzzy matcher without one) maps each file
to one of our tables and each column to one of our column names. The analyst
reviews it before anything is applied; applying only renames columns and
writes one CSV per table, so validation then runs exactly as for any upload.
Only file names, column headers and three sample values per column are sent.
"""
from __future__ import annotations

import difflib
import io
import json
from pathlib import Path
import re

import pandas as pd
from pydantic import BaseModel

from api.ai import AIUnavailable, Provider
from ews.contracts import TABLES
from ews.engine.validate import NUMERIC, REQUIRED

EXTRA = {
    "customers": ["customer_name", "origination_rating", "relationship_manager", "resident_type"],
    "facilities": ["due_day", "first_due_date", "maturity_date", "facility_status", "interest_rate_pct",
                   "profit_rate_pct", "contract_type"],
    "repayments": ["installment_no"],
    "delinquency": ["dpd_bucket_3m_ago", "instalments_30plus_dpd_12m", "partial_payments_12m"],
}
TARGETS = {t: list(dict.fromkeys(REQUIRED[t] + NUMERIC.get(t, []) + EXTRA.get(t, []))) for t in TABLES}
TABLE_HINTS = {
    "customers": ["customer", "client", "borrower", "cust", "obligor"],
    "facilities": ["facility", "facilities", "loan", "account", "contract", "limit"],
    "repayments": ["repayment", "payment", "instalment", "installment", "emi", "schedule"],
    "delinquency": ["delinquency", "dpd", "arrears", "overdue"],
    "exposure": ["exposure", "bureau", "utilisation", "utilization", "obligation"],
    "transactions": ["transaction", "txn", "cashflow", "cash_flow", "statement", "banking"],
    "sme_indicators": ["sme", "gst", "vat", "tax", "receivable"],
}
SYNONYMS = [(r"\bcust(omer)?\b|\bclient\b|\bborrower\b", "customer"), (r"\bno\b|\bnum(ber)?\b|\bref\b", "id"),
            (r"\bacc(oun)?t\b|\bloan\b|\bfacility\b", "loan"), (r"\bamt\b", "amount"), (r"\bbal\b", "balance"),
            (r"\bos\b|\bo/s\b", "outstanding"), (r"\bdt\b", "date"), (r"\bdisb(ursed|ursement)?\b", "disbursement"),
            (r"\btxns?\b", "transactions"), (r"\butil(isation|ization)?\b", "utilisation"),
            (r"\binst(al)?l?ment\b|\bemi\b", "instalment"), (r"\bsanc(tioned)?\b", "sanctioned"),
            (r"\bpaid\b", "paid"), (r"\bdays past due\b", "dpd"), (r"\b(paid|pay) date\b", "payment date")]


class ColumnMap(BaseModel):
    source: str
    target: str            # one of the table's target columns, or "" to leave unmapped


class FileMap(BaseModel):
    file: str
    table: str             # one of TABLES, or "ignore"
    columns: list[ColumnMap]


class MappingProposal(BaseModel):
    files: list[FileMap]
    notes: list[str]


SYSTEM_PROMPT = """You map a bank's data files onto an Early Warning System's tables.

The user message lists each uploaded file (or Excel sheet) with its column headers and up to three sample values, and the target tables with their column names. Rules:
- For each file choose the target table it holds, or "ignore" if none fits.
- For each source column choose the target column with the same meaning, copied exactly, or "" if none matches. Never map two source columns of one file to the same target.
- Use the headers and sample values (dates, IDs like C0001 or L00001, amounts, statuses) to decide. Do not guess when unsure; use "".
- notes: short remarks on anything ambiguous."""


def read_tables(files: dict[str, bytes]) -> dict[str, pd.DataFrame]:
    """name (file, or file:sheet for Excel) -> DataFrame read as text."""
    out = {}
    for name, data in files.items():
        suffix = Path(name).suffix.lower()
        if suffix == ".csv":
            out[name] = pd.read_csv(io.BytesIO(data), dtype=str)
        elif suffix in (".xlsx", ".xls"):
            for sheet, df in pd.read_excel(io.BytesIO(data), sheet_name=None, dtype=str).items():
                out[f"{name}:{sheet}"] = df
    return out


def describe(tables: dict[str, pd.DataFrame]) -> list[dict]:
    return [{"file": name, "columns": [{"name": str(c), "samples": [str(v)[:30] for v in df[c].dropna().head(3)]}
                                       for c in df.columns]} for name, df in tables.items()]


def _norm(text: str) -> str:
    text = re.sub(r"[_\-./]+", " ", str(text).lower()).strip()
    for pattern, repl in SYNONYMS:
        text = re.sub(pattern, repl, text)
    return re.sub(r"\s+", " ", text)


def heuristic(described: list[dict]) -> MappingProposal:
    files = []
    for f in described:
        stem = _norm(Path(f["file"].split(":")[-1]).stem)
        table = next((t for t in TABLES if _norm(t) == stem), None) or \
            next((t for t, hints in TABLE_HINTS.items() if any(h in stem for h in hints)), None)
        if table is None:
            heads = " ".join(_norm(c["name"]) for c in f["columns"])
            scores = {t: sum(_norm(col) in heads for col in TARGETS[t]) for t in TABLES}
            table = max(scores, key=scores.get) if max(scores.values()) >= 2 else "ignore"
        used, cols = set(), []
        for c in f["columns"]:
            target = ""
            if table != "ignore":
                options = {_norm(t): t for t in TARGETS[table] if t not in used}
                name = _norm(c["name"])
                match = difflib.get_close_matches(name, list(options), n=1, cutoff=0.72)
                if not match:   # a shorter form of one target, e.g. "portfolio" for "portfolio classification"
                    words = set(name.split())
                    contained = [o for o in options if words and words <= set(o.split())]
                    match = contained if len(contained) == 1 else []
                if match:
                    target = options[match[0]]
                    used.add(target)
            cols.append(ColumnMap(source=c["name"], target=target))
        files.append(FileMap(file=f["file"], table=table, columns=cols))
    return MappingProposal(files=files, notes=["Proposed by name matching (no AI model configured)."])


def clean(p: MappingProposal, described: list[dict]) -> tuple[MappingProposal, dict]:
    """Keep only valid tables/targets, no duplicate targets; report required columns still missing."""
    sources = {f["file"]: [c["name"] for c in f["columns"]] for f in described}
    files, dropped = [], []
    for f in p.files:
        if f.file not in sources:
            continue
        table = f.table if f.table in TABLES else "ignore"
        used, cols = set(), []
        given = {c.source: c.target for c in f.columns}
        for src in sources[f.file]:
            target = given.get(src, "")
            if table == "ignore" or target not in TARGETS.get(table, []) or target in used:
                if target:
                    dropped.append(f"{f.file}: {src} -> {target}")
                target = ""
            used.add(target) if target else None
            cols.append(ColumnMap(source=src, target=target))
        files.append(FileMap(file=f.file, table=table, columns=cols))
    for name in set(sources) - {f.file for f in files}:
        files.append(FileMap(file=name, table="ignore", columns=[ColumnMap(source=s, target="") for s in sources[name]]))
    covered: dict[str, set] = {}
    for f in files:
        if f.table != "ignore":
            covered.setdefault(f.table, set()).update(c.target for c in f.columns if c.target)
            covered[f.table].update(c.source for c in f.columns if c.source in TARGETS[f.table] and not c.target)
    missing = {t: [c for c in REQUIRED[t] if c not in covered.get(t, set())] for t in covered}
    missing = {t: cols for t, cols in missing.items() if cols}
    return MappingProposal(files=files, notes=p.notes), {"dropped": dropped, "missing_required": missing,
                                                         "tables_not_supplied": [t for t in TABLES if t not in covered and t != "sme_indicators"]}


def propose(provider: Provider | None, files: dict[str, bytes]):
    described = describe(read_tables(files))
    error = None
    if provider is not None:
        try:
            content = json.dumps({"files": described, "target_tables": TARGETS})
            proposal = provider.parse(SYSTEM_PROMPT, content, MappingProposal, max_tokens=6000)
            proposal, checks = clean(proposal, described)
            return proposal, checks, provider.name, provider.model, None
        except AIUnavailable as e:
            error = str(e)
    proposal, checks = clean(heuristic(described), described)
    return proposal, checks, "fuzzy", None, error


def apply(files: dict[str, bytes], proposal: MappingProposal) -> dict[str, bytes]:
    """Rename columns and write one CSV per target table; JSON files pass through unchanged."""
    tables = read_tables(files)
    out: dict[str, bytes] = {}
    for f in proposal.files:
        if f.table == "ignore" or f.file not in tables:
            continue
        rename = {c.source: c.target for c in f.columns if c.target}
        df = tables[f.file].rename(columns=rename)
        name = f"{f.table}.csv"
        if name in out:   # several files for one table: append rows
            df = pd.concat([pd.read_csv(io.BytesIO(out[name]), dtype=str), df], ignore_index=True)
        out[name] = df.to_csv(index=False).encode("utf-8")
    for name, data in files.items():
        if Path(name).suffix.lower() == ".json":
            out[name] = data
    return out
