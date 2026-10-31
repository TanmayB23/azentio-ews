"""Session-local scoring cache keyed by all source bytes and the region profile."""
from hashlib import sha256
from pathlib import Path
from ews import engine

DATA_ROOT = Path(__file__).resolve().parents[1] / "data"


def source_bytes(sources):
    # Hash the same bytes that are loaded, so changed files cannot reuse stale results.
    return {name: value if isinstance(value, bytes) else Path(value).read_bytes()
        for name, value in sources.items() if Path(name).stem.lower() != "ground_truth"}


def source_hash(sources):
    digest = sha256()
    for name, content in sorted(sources.items()):
        for part in (name.encode(), content):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
    return digest.hexdigest()


def sample_sources(profile, variant):
    if profile not in engine.available_profiles() or variant not in ("clean", "dirty"):
        raise ValueError("Choose an available profile and clean or dirty data")
    return source_bytes(engine.sources_from_dir(DATA_ROOT / profile / variant))


def assess(ds, fingerprint, profile, cache):
    key = (fingerprint, profile)
    if key not in cache:
        results = engine.score_portfolio(ds, profile=profile)
        clusters = engine.detect_clusters(ds, results)
        # Bound session memory when analysts try many uploads/profiles.
        if len(cache) >= 4:
            cache.pop(next(iter(cache)))
        cache[key] = results, clusters
    return cache[key]
