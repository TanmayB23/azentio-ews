"""Datasets and scoring runs.

Uploaded or sample sources are stored on disk under a content hash, so a
saved run can always be traced to the exact files it was scored from and
reloaded after a restart. Parsed datasets and scored runs are kept in a small
in-memory LRU cache.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import threading

import pandas as pd

from ews import engine
from ews.contracts import Cluster, CustomerResult, Dataset, SignalResult
from ews.store.db import Store

ALLOWED_SUFFIXES = {".csv", ".xlsx", ".xls", ".json"}
EXCLUDED_STEMS = {"ground_truth"}            # answer key: never ingested
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ENGINE_NAME = "ews.engine"
SAMPLE_NAMES = {"india": "India", "gcc_islamic": "GCC Islamic"}


def source_hash(sources: dict[str, bytes]) -> str:
    digest = sha256()
    for name, content in sorted(sources.items()):
        for part in (name.encode(), content):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
    return digest.hexdigest()[:16]


def result_from_dict(d: dict) -> CustomerResult:
    return CustomerResult(**{**d, "signals": [SignalResult(**s) for s in d["signals"]]})


class _LRU(OrderedDict):
    def __init__(self, size: int):
        super().__init__()
        self.size = size

    def put(self, key, value):
        self[key] = value
        self.move_to_end(key)
        while len(self) > self.size:
            self.popitem(last=False)
        return value

    def fetch(self, key):
        if key in self:
            self.move_to_end(key)
            return self[key]
        return None


@dataclass
class Run:
    meta: dict
    dataset: Dataset
    results: dict[str, CustomerResult]
    clusters: list[Cluster]


class Registry:
    def __init__(self, var_dir: Path, data_root: Path, store: Store):
        self.root = var_dir / "datasets"
        self.root.mkdir(parents=True, exist_ok=True)
        self.data_root = data_root
        self.store = store
        self._datasets = _LRU(6)
        self._runs = _LRU(6)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ datasets
    def samples(self) -> list[dict]:
        out = []
        for profile in engine.available_profiles():
            for variant in ("clean", "dirty"):
                if (self.data_root / profile / variant).is_dir():
                    out.append({"profile": profile, "variant": variant})
        return out

    def register_sample(self, profile: str, variant: str) -> dict:
        folder = self.data_root / profile / variant
        if profile not in engine.available_profiles() or variant not in ("clean", "dirty") or not folder.is_dir():
            raise ValueError("Unknown sample portfolio")
        sources = {name: Path(path).read_bytes() for name, path in engine.sources_from_dir(folder).items()}
        label = f"{SAMPLE_NAMES.get(profile, profile)} sample ({variant})"
        return self.register(sources, label, origin="sample", profile_hint=profile)

    def register(self, sources: dict[str, bytes], label: str, origin: str = "upload",
                 profile_hint: str | None = None) -> dict:
        clean: dict[str, bytes] = {}
        for name, content in sources.items():
            path = Path(Path(name).name)
            if path.stem.lower() in EXCLUDED_STEMS:
                continue
            if path.suffix.lower() not in ALLOWED_SUFFIXES:
                raise ValueError(f"{path.name}: only CSV, Excel and JSON files are accepted")
            if len(content) > MAX_UPLOAD_BYTES:
                raise ValueError(f"{path.name}: file is larger than 50 MB")
            clean[path.name] = content
        if not clean:
            raise ValueError("No data files supplied")
        dataset_id = source_hash(clean)
        folder = self.root / dataset_id
        if not (folder / "meta.json").exists():
            folder.mkdir(parents=True, exist_ok=True)
            for name, content in clean.items():
                (folder / name).write_bytes(content)
            meta = {"dataset_id": dataset_id, "label": label, "origin": origin, "profile_hint": profile_hint,
                    "files": sorted(clean), "created_at": datetime.now(timezone.utc).isoformat()}
            (folder / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return self.dataset_meta(dataset_id)

    def dataset_meta(self, dataset_id: str) -> dict:
        path = self.root / dataset_id / "meta.json"
        if not path.exists():
            raise KeyError(dataset_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def datasets(self) -> list[dict]:
        metas = [json.loads(p.read_text(encoding="utf-8")) for p in self.root.glob("*/meta.json")]
        return sorted(metas, key=lambda m: m["created_at"], reverse=True)

    def dataset(self, dataset_id: str) -> Dataset:
        with self._lock:
            cached = self._datasets.fetch(dataset_id)
            if cached is not None:
                return cached
        meta = self.dataset_meta(dataset_id)
        folder = self.root / dataset_id
        ds = engine.load_dataset({name: (folder / name).read_bytes() for name in meta["files"]})
        with self._lock:
            return self._datasets.put(dataset_id, ds)

    # ------------------------------------------------------------------ runs
    def create_run(self, dataset_id: str, profile: str) -> dict:
        if profile not in engine.available_profiles():
            raise ValueError(f"Unknown profile '{profile}'")
        ds = self.dataset(dataset_id)
        blocking = [i for i in ds.issues if i.severity == "error" and i.action == "kept"]
        if blocking:
            raise ValueError("Fix structural errors before scoring: " + "; ".join(i.issue for i in blocking[:3]))
        results = engine.score_portfolio(ds, profile=profile)
        clusters = engine.detect_clusters(ds, results)
        meta = self.dataset_meta(dataset_id)
        run_id = self.store.save_run(results, profile, ENGINE_NAME, dataset_id, meta["label"])
        run = Run(self.store.run(run_id), ds, {r.customer_id: r for r in results}, clusters)
        with self._lock:
            self._runs.put(run_id, run)
        return run.meta

    def run(self, run_id: str) -> Run:
        with self._lock:
            cached = self._runs.fetch(run_id)
            if cached is not None:
                return cached
        meta = self.store.run(run_id)
        ds = self.dataset(meta["dataset_id"])
        results = {a["customer_id"]: result_from_dict(json.loads(a["result_json"])) for a in self.store.alerts(run_id)}
        clusters = engine.detect_clusters(ds, list(results.values()))
        run = Run(meta, ds, results, clusters)
        with self._lock:
            return self._runs.put(run_id, run)


def frame_records(df: pd.DataFrame, limit: int | None = None) -> list[dict]:
    """DataFrame -> JSON-safe records (NaN -> None, timestamps -> ISO strings)."""
    if df is None or df.empty:
        return []
    df = df.head(limit) if limit else df
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d")
    return json.loads(out.to_json(orient="records", date_format="iso"))
