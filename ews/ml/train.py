"""Offline training: python -m ews.ml.train --output models/delinquency_3m."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import train_test_split
import xgboost as xgb

from ews.engine import load_dir, sources_from_dir
from ews.engine.config import load_profile
from ews.ml.features import FEATURE_IDS, FEATURE_VERSION, feature_rows, feature_signature, horizon_end, target


def build_training(data_root, profiles, origins=6):
    rows, signatures, sources = [], {}, {}
    for profile in profiles:
        folder = Path(data_root) / profile / "clean"
        ds = load_dir(folder)
        if any(i.severity == "error" for i in ds.issues):
            raise ValueError(f"Training requires clean validated input: {profile}")
        observed = pd.Timestamp(load_profile(profile)["as_of"])
        signatures[profile] = feature_signature(ds, profile)
        digest = sha256()
        for name, file in sorted(sources_from_dir(folder).items()):
            digest.update(name.encode()); digest.update(Path(file).read_bytes())
        sources[profile] = digest.hexdigest()
        last = observed.to_period("M") - 3
        for month in pd.period_range(end=last, periods=origins, freq="M"):
            origin = month.end_time.normalize()
            count, positives = 0, 0
            for cid, row in feature_rows(ds, profile, origin).items():
                if row["observed_months"] < 4 or row["coverage"] < .5 or row["current_dpd"] >= 30:
                    continue
                y = target(ds, cid, origin, observed)
                if y is None:
                    continue
                rows.append({**row["features"], "group": f"{profile}:{cid}", "profile": profile,
                    "origin": str(origin.date()), "horizon_end": str(horizon_end(origin).date()), "target": y})
                count += 1; positives += y
            print(f"{profile} {month}: {count} eligible origins, {positives} recorded outcomes", flush=True)
    if not rows:
        raise ValueError("No fully observed eligible customer-month outcomes")
    return pd.DataFrame(rows), signatures, sources


def split_rows(table, mode="customer-demo", seed=42):
    if mode == "customer-demo":
        groups = table.groupby("group").target.max()
        if groups.value_counts().min() < 6 or len(groups.value_counts()) != 2:
            raise ValueError("Need at least six customer groups in each outcome class for disjoint splits")
        train, test = train_test_split(groups.index, test_size=.2, random_state=seed, stratify=groups)
        train, calibration = train_test_split(train, test_size=.2, random_state=seed, stratify=groups.loc[train])
        parts = [table.loc[table.group.isin(ids)].copy() for ids in (train, calibration, test)]
        assert not (set(parts[0].group) & set(parts[1].group) or set(parts[0].group) & set(parts[2].group) or set(parts[1].group) & set(parts[2].group))
    else:
        dates = sorted(table.origin.unique())
        test_start = dates[max(1, int(len(dates)*.8))]
        before_test = table.loc[table.horizon_end < test_start]
        eligible_dates = sorted(before_test.origin.unique())
        if len(eligible_dates) < 3:
            raise ValueError("Not enough mature origins for purged chronological train/calibration/test; supply longer history. Synthetic demo uses --split customer-demo.")
        cal_start = eligible_dates[max(1, int(len(eligible_dates)*.8))]
        parts = [table.loc[table.horizon_end < cal_start].copy(),
            before_test.loc[before_test.origin >= cal_start].copy(), table.loc[table.origin >= test_start].copy()]
    for name, part in zip(("train", "calibration", "test"), parts):
        if len(part) == 0 or part.target.nunique() != 2:
            raise ValueError(f"{name} requires both outcome classes. Short synthetic histories cannot support a meaningful purged time split.")
    return parts


def calibrate(margin, target_values):
    """Positive-slope sigmoid calibration on separate customer groups."""
    def loss(values):
        slope, intercept = values
        z = slope*margin + intercept
        objective = np.mean(np.logaddexp(0, z)-target_values*z) + .001*(slope-1)**2
        residual = expit(z)-target_values
        return objective, np.array([np.mean(residual*margin)+.002*(slope-1), np.mean(residual)])
    result = minimize(loss, [1., 0.], jac=True, bounds=[(0,10),(-20,20)], method="L-BFGS-B")
    if not result.success:
        raise ValueError("Sigmoid calibration did not converge")
    return {"method": "held-out bounded sigmoid", "slope": float(result.x[0]), "intercept": float(result.x[1])}


def metrics(y, probability, baseline):
    bins = []
    for lower, upper in zip(np.linspace(0,1,6)[:-1], np.linspace(0,1,6)[1:]):
        mask = (probability >= lower) & (probability <= upper if upper == 1 else probability < upper)
        if mask.any():
            bins.append({"count": int(mask.sum()), "mean_prediction": float(probability[mask].mean()), "observed_rate": float(y[mask].mean())})
    return {"roc_auc": float(roc_auc_score(y,probability)), "average_precision": float(average_precision_score(y,probability)),
        "brier_score": float(brier_score_loss(y,probability)), "log_loss": float(log_loss(y,probability,labels=[0,1])),
        "event_rate": float(y.mean()), "constant_baseline_brier": float(brier_score_loss(y,np.full(len(y),baseline))), "calibration_bins": bins}


def train(table, signatures, sources, output, mode="customer-demo", seed=42, rounds=100):
    parts = split_rows(table, mode, seed)
    train_rows, cal_rows, test_rows = parts
    matrix = lambda frame: xgb.DMatrix(frame[list(FEATURE_IDS)].astype(float), feature_names=list(FEATURE_IDS))
    booster = xgb.train({"objective":"binary:logistic", "eval_metric":"logloss", "max_depth":3,
        "eta":.05,"min_child_weight":5,"lambda":5,"alpha":.1,"seed":seed,"nthread":2},
        xgb.DMatrix(train_rows[list(FEATURE_IDS)].astype(float),label=train_rows.target,feature_names=list(FEATURE_IDS)), num_boost_round=rounds)
    cal_margin = booster.predict(matrix(cal_rows), output_margin=True).astype(float)
    calibration = calibrate(cal_margin, cal_rows.target.to_numpy())
    raw_test = booster.predict(matrix(test_rows),output_margin=True).astype(float)
    probability = expit(calibration["slope"]*raw_test+calibration["intercept"])
    split_report = {}
    for name, rows in zip(("train","calibration","test"),parts):
        split_report[name] = {"rows":len(rows),"customers":rows.group.nunique(),"positive_rows":int(rows.target.sum()),
            "origin_start":rows.origin.min(),"origin_end":rows.origin.max(),"last_label_date":rows.horizon_end.max()}
    metadata = {"format_version":1,"feature_version":FEATURE_VERSION,"feature_ids":list(FEATURE_IDS),
        "feature_signatures":signatures,"source_hashes":sources,"training_data_kind":"synthetic",
        "algorithm":"XGBoost gradient-boosted decision trees","xgboost_version":xgb.__version__,
        "horizon_months":3,"threshold_dpd":30,"seed":seed,"rounds":rounds,"calibration":calibration,
        "feature_names":{},"split":mode,"splits":split_report,
        "evaluation":metrics(test_rows.target.to_numpy(),probability,float(train_rows.target.mean())),
        "limitations":["Synthetic-data method demonstration, not evidence of real-world predictive accuracy.",
            "Few positive outcomes; overlapping customer-month labels are correlated.",
            "Customer-disjoint holdout uses the same calendar period; it is not an out-of-time backtest." if mode == "customer-demo" else "Purged chronological holdout; real-world representativeness still requires validation.",
            "Monthly inputs are assumed available at month-end; real data needs reliable availability timestamps.",
            "Ambiguous partial-payment label windows and incomplete future follow-up are censored."]}
    from ews.engine.config import load_signal_definitions
    metadata["feature_names"] = {s["signal_id"]:s["signal_name"] for s in load_signal_definitions()["signals"]}
    raw = bytes(booster.save_raw(raw_format="ubj"))
    metadata["model_sha256"] = sha256(raw).hexdigest()
    model_id = "gbdt-"+sha256(raw+json.dumps(metadata,sort_keys=True).encode()).hexdigest()[:16]
    metadata.update(model_id=model_id,trained_at=datetime.now(timezone.utc).isoformat())
    root = Path(output); folder = root/model_id
    folder.mkdir(parents=True,exist_ok=True)
    if (folder/"metadata.json").exists():
        existing = json.loads((folder/"metadata.json").read_text())
        if existing["model_sha256"] != sha256((folder/"model.ubj").read_bytes()).hexdigest():
            raise ValueError("Existing versioned model failed checksum verification")
        metadata = existing
    else:
        (folder/"model.ubj").write_bytes(raw)
        (folder/"metadata.json").write_text(json.dumps(metadata,indent=2,allow_nan=False),encoding="utf-8")
    temporary = root/"current.json.tmp"
    temporary.write_text(json.dumps({"model_id":model_id})+"\n",encoding="utf-8")
    temporary.replace(root/"current.json")
    print(json.dumps({"model_id":model_id,"splits":split_report,"evaluation":metadata["evaluation"]},indent=2),flush=True)
    return folder


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root",default="data")
    parser.add_argument("--profiles",nargs="+",default=["india","gcc_islamic"])
    parser.add_argument("--output",default="models/delinquency_3m")
    parser.add_argument("--origins",type=int,default=6)
    parser.add_argument("--split",choices=["customer-demo","temporal"],default="customer-demo")
    parser.add_argument("--seed",type=int,default=42)
    parser.add_argument("--rounds",type=int,default=100)
    args=parser.parse_args()
    table, signatures, sources=build_training(args.data_root,args.profiles,args.origins)
    Path("var/ml").mkdir(parents=True,exist_ok=True)
    table.to_csv("var/ml/training_rows.csv",index=False)
    train(table,signatures,sources,args.output,args.split,args.seed,args.rounds)

if __name__ == "__main__":
    main()
