"""Reads CSV, Excel and JSON sources into raw tables, then validates them.

Everything is read as text first so that malformed values reach the validator
instead of crashing the reader.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pandas as pd

from ews.contracts import TABLES, Dataset
from ews.engine.validate import validate

SIGNAL_DEFS = "risk_signal_definitions"
DEFAULT_CLASSIFICATION = [
    {"category": "Low", "min": 0, "max": 24, "monitoring_status": "Routine"},
    {"category": "Medium", "min": 25, "max": 49, "monitoring_status": "Watch"},
    {"category": "High", "min": 50, "max": 74, "monitoring_status": "Investigate"},
    {"category": "Critical", "min": 75, "max": 100, "monitoring_status": "Escalate"},
]
_NUMERIC_SIGNAL_FIELDS = ("window_months", "trigger", "saturation", "weight", "min_observations")


def load_dataset(sources: dict[str, str | bytes | Path], fmt_hint: str | None = None) -> Dataset:
    """sources maps a file name (used for the format and table name) to a path or raw bytes."""
    raw: dict[str, pd.DataFrame] = {}
    signal_config = None
    for name, src in sources.items():
        data = src if isinstance(src, bytes) else Path(src).read_bytes()
        fmt = (fmt_hint or Path(name).suffix.lstrip(".")).lower()
        stem = _table_name(name)
        if fmt == "csv":
            df = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=True)
            if stem == SIGNAL_DEFS:
                signal_config = _signals_from_frame(df)
            else:
                raw[stem] = df
        elif fmt in ("xlsx", "xls", "xlsm"):
            for sheet, df in pd.read_excel(io.BytesIO(data), sheet_name=None, dtype=str).items():
                sheet = _table_name(sheet)
                if sheet == SIGNAL_DEFS:
                    signal_config = _signals_from_frame(df)
                else:
                    raw[sheet] = df
        elif fmt == "json":
            obj = json.loads(data.decode("utf-8-sig"))
            if isinstance(obj, dict) and "signals" in obj:
                signal_config = obj
            elif isinstance(obj, dict):
                for key, records in obj.items():
                    raw[_table_name(key)] = _as_text_frame(pd.DataFrame(records))
            elif isinstance(obj, list):
                raw[stem] = _as_text_frame(pd.DataFrame(obj))
        else:
            raise ValueError(f"Unsupported format '{fmt}' for {name}")

    unknown = sorted(set(raw) - set(TABLES))
    for key in unknown:
        raw.pop(key)
    ds = validate(raw)
    ds.signal_config = signal_config
    return ds


def sources_from_dir(folder: str | Path) -> dict[str, Path]:
    """Picks the CSV tables (and signal definitions) from a data folder."""
    folder = Path(folder)
    names = [*TABLES, SIGNAL_DEFS]
    found = {p.name: p for p in folder.glob("*.csv") if p.stem in names}
    if not any(Path(n).stem in TABLES for n in found):
        found.update({p.name: p for p in folder.glob("*.xlsx")})
        found.update({p.name: p for p in folder.glob("*.json")})
    return found


def load_dir(folder: str | Path) -> Dataset:
    return load_dataset(sources_from_dir(folder))


def _table_name(name: str) -> str:
    return Path(str(name)).stem.strip().lower().replace(" ", "_")


def _as_text_frame(df: pd.DataFrame) -> pd.DataFrame:
    return df.apply(lambda col: col.map(lambda v: None if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)))


def _signals_from_frame(df: pd.DataFrame) -> dict:
    signals = []
    for row in df.to_dict("records"):
        sig = {k: v for k, v in row.items() if isinstance(v, str) or not pd.isna(v)}
        for k in _NUMERIC_SIGNAL_FIELDS:
            if k in sig:
                sig[k] = float(sig[k])
        signals.append(sig)
    return {
        "version": "uploaded",
        "score_scale": {"min": 0, "max": 100, "higher_score_means": "higher credit risk"},
        "classification": DEFAULT_CLASSIFICATION,
        "signals": signals,
    }
