"""Loads risk signal definitions and region profiles from config/."""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def load_signal_definitions(override: dict | None = None) -> dict:
    if override:
        return override
    return json.loads((CONFIG_DIR / "risk_signal_definitions.json").read_text(encoding="utf-8"))


def load_profile(name: str = "india") -> dict:
    path = CONFIG_DIR / "profiles" / f"{name}.json"
    if not path.exists():
        raise ValueError(f"Unknown profile '{name}'. Available: {available_profiles()}")
    return json.loads(path.read_text(encoding="utf-8"))


def available_profiles() -> list[str]:
    return sorted(p.stem for p in (CONFIG_DIR / "profiles").glob("*.json"))


def pillar_of(signal: dict) -> str:
    return signal.get("pillar") or signal["signal_id"][:2]
