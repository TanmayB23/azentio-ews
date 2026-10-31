"""python -m ews.engine <data folder> [--profile india] [--top 20]"""
from __future__ import annotations

import argparse
from collections import Counter

from ews.engine import detect_clusters, load_dir, score_portfolio


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the EWS engine on a data folder")
    ap.add_argument("folder")
    ap.add_argument("--profile", default="india")
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    ds = load_dir(args.folder)
    print(f"Loaded: {', '.join(f'{k}={len(v)}' for k, v in ds.tables.items())}")
    counts = Counter((i.severity, i.action) for i in ds.issues)
    print("Validation:", ", ".join(f"{n} {sev}/{act}" for (sev, act), n in counts.items()) or "no issues")

    results = score_portfolio(ds, args.profile)
    bands = Counter(r.band or r.status for r in results)
    print("Bands:", ", ".join(f"{b}={bands[b]}" for b in ("Critical", "High", "Medium", "Low", "Insufficient data")))

    print(f"\nTop {args.top} (score, band, confidence, summary)")
    ranked = sorted((r for r in results if r.score is not None), key=lambda r: r.score, reverse=True)
    for r in ranked[:args.top]:
        print(f"  {r.customer_id}  {r.score:5.1f}  {r.band:<8}  {r.confidence:.2f}  {r.summary}")

    print("\nClusters")
    for c in detect_clusters(ds, results):
        print(f"  {c.dimension}={c.value}: {c.n_elevated}/{c.n_customers} elevated, lift {c.lift}, "
              f"p={c.p_value}, basis: {c.basis}, signals {c.top_signals}")


if __name__ == "__main__":
    main()
