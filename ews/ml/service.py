"""Versioned inference and append-only forecasts; never edits rule alerts."""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import threading
from uuid import uuid4

import numpy as np
import pandas as pd

from ews.contracts import Dataset
from ews.ml.features import FEATURE_IDS, FEATURE_VERSION, feature_rows, feature_signature, horizon_end

DISCLAIMER = "Synthetic-data prototype: the method is ready for real data, not evidence of predictive accuracy. The model can learn generator patterns."


class PredictionService:
    def __init__(self, model_dir, store):
        self.root = Path(model_dir)
        self.store = store
        self._lock = threading.RLock()
        self._loaded = None
        with store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS ml_predictions (
                prediction_id TEXT PRIMARY KEY, alert_id INTEGER NOT NULL REFERENCES alerts(alert_id),
                model_id TEXT NOT NULL, feature_hash TEXT NOT NULL, created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL, UNIQUE(alert_id, model_id, feature_hash))""")
            for action in ("UPDATE", "DELETE"):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS ml_predictions_no_{action.lower()} BEFORE {action} ON ml_predictions BEGIN SELECT RAISE(ABORT, 'ML predictions are append-only'); END")

    def _model(self):
        import xgboost as xgb
        with self._lock:
            pointer = json.loads((self.root/"current.json").read_text())
            model_id = pointer["model_id"]
            if not re.fullmatch(r"gbdt-[a-f0-9]{16}", model_id):
                raise ValueError("Invalid model identifier")
            if self._loaded and self._loaded[0]["model_id"] == model_id:
                return self._loaded
            folder = self.root/model_id
            meta = json.loads((folder/"metadata.json").read_text())
            raw = (folder/"model.ubj").read_bytes()
            if meta["model_id"] != model_id or sha256(raw).hexdigest() != meta["model_sha256"]:
                raise ValueError("Model checksum mismatch")
            if meta["format_version"] != 1 or meta["feature_version"] != FEATURE_VERSION or meta["feature_ids"] != list(FEATURE_IDS):
                raise ValueError("Incompatible feature schema")
            booster = xgb.Booster()
            booster.load_model(bytearray(raw))
            if booster.feature_names != list(FEATURE_IDS):
                raise ValueError("Incompatible model feature order")
            if not all(np.isfinite(meta["calibration"][key]) for key in ("slope","intercept")):
                raise ValueError("Invalid calibration")
            self._loaded = (meta, booster)
            return self._loaded

    def info(self):
        try:
            meta, _ = self._model()
            return {"available":True, "metadata":meta, "disclaimer":DISCLAIMER}
        except (OSError, ValueError, KeyError, ImportError):
            return {"available":False, "reason":"Trained ML model unavailable. Run python -m ews.ml.train after installing requirements.", "disclaimer":DISCLAIMER}

    def history(self, alert_id):
        with self.store.connect() as db:
            return [json.loads(row["payload_json"]) for row in db.execute(
                "SELECT payload_json FROM ml_predictions WHERE alert_id=? ORDER BY created_at DESC", (alert_id,))]

    def predict(self, run, customer_id, alert):
        result = run.results[customer_id]
        base = {"status":"model_unavailable", "probability":None, "threshold_dpd":30,"horizon_months":3,
            "as_of":result.as_of,"horizon_end":str(horizon_end(result.as_of).date()),
            "factors":[],"disclaimer":DISCLAIMER,"model":None}
        info = self.info()
        if not info["available"]:
            return {**base,"reason":info["reason"]}
        meta, booster = self._model()
        base["model"] = meta
        if not pd.Timestamp(result.as_of).is_month_end:
            return {**base,"reason":"This monthly model requires a month-end assessment date."}
        if feature_signature(run.dataset,run.meta["profile"]) != meta["feature_signatures"].get(run.meta["profile"]):
            return {**base,"reason":"This signal feature definition or regional profile differs from the trained model. Retrain for these definitions."}
        # One customer only: other customers and their IDs never enter the model.
        subset = Dataset({name:frame.loc[frame.customer_id == customer_id].copy() for name,frame in run.dataset.tables.items()}, [], {}, run.dataset.signal_config)
        rows = feature_rows(subset,run.meta["profile"],result.as_of)
        row = rows.get(customer_id)
        if row is None:
            return {**base,"reason":"No customer observations available at the assessment date."}
        vector = [row["features"][sid] for sid in FEATURE_IDS]
        safe_vector = [None if not np.isfinite(v) else float(v) for v in vector]
        feature_hash = sha256(json.dumps({"features":safe_vector,"alert":sha256(alert["result_json"].encode()).hexdigest(),"feature_version":FEATURE_VERSION},sort_keys=True).encode()).hexdigest()
        with self.store.connect() as db:
            previous = db.execute("SELECT payload_json FROM ml_predictions WHERE alert_id=? AND model_id=? AND feature_hash=?", (alert["alert_id"],meta["model_id"],feature_hash)).fetchone()
        if previous:
            return json.loads(previous["payload_json"])
        if result.status == "Insufficient data" or row["observed_months"] < 4 or row["coverage"] < .5:
            prediction = {**base,"status":"insufficient_data","reason":"Not enough observed repayment history or signal coverage for a forecast. Collect more data."}
        elif row["current_dpd"] >= 30 or any(s.signal_id == "RB04" and s.value is not None and s.value >= 30 for s in result.signals):
            prediction = {**base,"status":"already_delinquent","reason":"Already at 30+ DPD in the current observation. This incident-risk model applies below 30 DPD; no future-entry probability is shown."}
        else:
            import xgboost as xgb
            from scipy.special import expit
            matrix = xgb.DMatrix(pd.DataFrame([vector],columns=FEATURE_IDS),feature_names=list(FEATURE_IDS))
            margin = float(booster.predict(matrix,output_margin=True)[0])
            contributions = booster.predict(matrix,pred_contribs=True)[0]
            slope, intercept = meta["calibration"]["slope"], meta["calibration"]["intercept"]
            log_odds = slope*margin+intercept
            baseline = slope*float(contributions[-1])+intercept
            factors = []
            for sid, value, contribution in zip(FEATURE_IDS,safe_vector,contributions[:-1]):
                signal = row["signals"].get(sid)
                effect = slope*float(contribution)
                factors.append({"signal_id":sid,"name":meta["feature_names"][sid],"value":value,
                    "evaluated":bool(signal and signal.evaluated),"applicable":bool(signal and signal.applicable),
                    "reason":signal.reason_not_evaluated if signal else "Not evaluated", "contribution":effect,
                    "direction":"increases" if effect>1e-8 else "decreases" if effect < -1e-8 else "neutral"})
            if abs(baseline+sum(f["contribution"] for f in factors)-log_odds) > .001:
                raise RuntimeError("ML explanation does not reconcile with the prediction")
            prediction = {**base,"status":"predicted","probability":float(expit(log_odds)),"reason":None,
                "base_probability":float(expit(baseline)),"base_log_odds":baseline,"log_odds":log_odds,
                "factors":sorted(factors,key=lambda f:abs(f["contribution"]),reverse=True),
                "explanation_method":"Exact TreeSHAP, scaled through sigmoid calibration; additive in log-odds, not probability percentage points."}
        prediction.update(prediction_id=str(uuid4()),model_id=meta["model_id"],feature_hash=feature_hash,
            created_at=datetime.now(timezone.utc).isoformat(),original_alert_sha256=sha256(alert["result_json"].encode()).hexdigest())
        with self.store.connect() as db:
            db.execute("INSERT OR IGNORE INTO ml_predictions VALUES (?,?,?,?,?,?)",(prediction["prediction_id"],alert["alert_id"],meta["model_id"],feature_hash,prediction["created_at"],json.dumps(prediction,allow_nan=False)))
            saved = db.execute("SELECT payload_json FROM ml_predictions WHERE alert_id=? AND model_id=? AND feature_hash=?",(alert["alert_id"],meta["model_id"],feature_hash)).fetchone()
        return json.loads(saved["payload_json"])
