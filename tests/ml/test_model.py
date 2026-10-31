import json
import shutil
import sqlite3
from copy import deepcopy
from dataclasses import asdict

import numpy as np
import pandas as pd
import pytest
from scipy.special import expit

from api.registry import Run
from ews.ml.features import FEATURE_IDS
from ews.ml.service import PredictionService
from ews.ml.train import split_rows, train
from ews.store.db import Store

@pytest.fixture(scope="module")
def saved_run(tmp_path_factory,clean_ds,clean_results):
    var=tmp_path_factory.mktemp("ml-evidence")
    store=Store(var/"ews.sqlite3")
    run_id=store.save_run(list(clean_results.values()),"india","ews.engine","fixture","Fixture")
    return store,Run(store.run(run_id),clean_ds,clean_results,[]),var


def test_split_has_no_customer_overlap(model_data):
    parts=split_rows(model_data)
    a,b,c=(set(part.group) for part in parts)
    assert not(a&b or a&c or b&c)
    assert sum(map(len,parts))==len(model_data)
    with pytest.raises(ValueError,match="Not enough mature origins"):
        split_rows(model_data,"temporal")


def test_temporal_split_purges_label_horizons():
    rows=[]
    for month in pd.period_range("2022-01","2025-12",freq="M"):
        for y in (0,1):
            origin=month.end_time.normalize()
            rows.append({"origin":str(origin.date()),"horizon_end":str((origin+pd.DateOffset(months=3)).date()),"target":y,"group":str(y)})
    train_rows,cal,test=split_rows(pd.DataFrame(rows),"temporal")
    assert train_rows.horizon_end.max()<cal.origin.min()
    assert cal.horizon_end.max()<test.origin.min()


def eligible(run):
    return next(r.customer_id for r in run.results.values() if r.status=="Scored" and
        all(s.value is None or s.value<30 for s in r.signals if s.signal_id=="RB04") and r.band=="Low")


def test_prediction_explains_exact_probability_and_preserves_rules(trained_model,saved_run):
    store,run,_=saved_run
    cid=eligible(run)
    alert=store.alert(run.meta["run_id"],cid)
    original=alert["result_json"]
    service=PredictionService(trained_model,store)
    prediction=service.predict(run,cid,alert)
    assert prediction["status"]=="predicted"
    assert 0<=prediction["probability"]<=1
    assert {f["signal_id"] for f in prediction["factors"]}==set(FEATURE_IDS)
    assert expit(prediction["base_log_odds"]+sum(f["contribution"] for f in prediction["factors"]))==pytest.approx(prediction["probability"],abs=1e-6)
    assert service.predict(run,cid,alert)["prediction_id"]==prediction["prediction_id"]
    assert store.alert(run.meta["run_id"],cid)["result_json"]==original
    assert len(service.history(alert["alert_id"]))==1
    assert "Synthetic-data" in prediction["disclaimer"]
    for sql in ("UPDATE ml_predictions SET payload_json='{}'","DELETE FROM ml_predictions"):
        with pytest.raises(sqlite3.IntegrityError,match="append-only"):
            with store.connect() as db:
                db.execute(sql)


def test_model_missing_thin_history_and_existing_delinquency(trained_model,saved_run,tmp_path):
    store,run,_=saved_run
    cid=eligible(run)
    unavailable=PredictionService(tmp_path/"absent",store).predict(run,cid,store.alert(run.meta["run_id"],cid))
    assert unavailable["status"]=="model_unavailable" and unavailable["probability"] is None
    service=PredictionService(trained_model,store)
    for required,status in (("Insufficient data","insufficient_data"),("Scored","already_delinquent")):
        if status=="insufficient_data":
            cid=next(r.customer_id for r in run.results.values() if r.status==required)
        else:
            cid=next(r.customer_id for r in run.results.values() if r.status=="Scored" and any(s.signal_id=="RB04" and s.value is not None and s.value>=30 for s in r.signals))
        result=service.predict(run,cid,store.alert(run.meta["run_id"],cid))
        assert result["status"]==status and result["probability"] is None


def test_custom_feature_definitions_and_corrupt_artifact(trained_model,saved_run,tmp_path):
    store,run,_=saved_run
    cid=eligible(run)
    altered=deepcopy(run)
    from ews.engine.scoring import _definitions
    altered.dataset.signal_config=_definitions(None)
    altered.dataset.signal_config["signals"][0]["window_months"]=12
    value=PredictionService(trained_model,store).predict(altered,cid,store.alert(run.meta["run_id"],cid))
    assert value["status"]=="model_unavailable"
    root=tmp_path/"corrupt"
    shutil.copytree(trained_model,root)
    model_id=json.loads((root/"current.json").read_text())["model_id"]
    (root/model_id/"model.ubj").write_bytes(b"corrupt")
    assert not PredictionService(root,store).info()["available"]


def test_new_model_creates_new_prediction_without_rewriting_old(trained_model,saved_run,model_data,tmp_path):
    store,run,_=saved_run
    root=tmp_path/"models"
    shutil.copytree(trained_model,root)
    cid=eligible(run); alert=store.alert(run.meta["run_id"],cid)
    service=PredictionService(root,store)
    before=service.predict(run,cid,alert)
    meta=service.info()["metadata"]
    train(model_data,meta["feature_signatures"],meta["source_hashes"],root,rounds=25)
    after=service.predict(run,cid,alert)
    assert before["model_id"]!=after["model_id"]
    assert before["prediction_id"]!=after["prediction_id"]
    assert any(row==before for row in service.history(alert["alert_id"]))
    assert json.loads(store.alert(run.meta["run_id"],cid)["result_json"])["score"]==run.results[cid].score


def test_ml_api_contract_and_wrong_customer(trained_model,saved_run,monkeypatch,tmp_path):
    from fastapi.testclient import TestClient
    from api.main import create_app
    from api.registry import Registry
    store,run,var=saved_run
    def get_run(self,run_id):
        if run_id!=run.meta["run_id"]:
            raise KeyError(run_id)
        return run
    monkeypatch.setattr(Registry,"run",get_run)
    client=TestClient(create_app(var_dir=var,web_dist=tmp_path/"missing",ml_model_dir=trained_model))
    cid=eligible(run)
    base=f"/api/runs/{run.meta['run_id']}/customers/{cid}"
    assert client.get("/api/ml/model").json()["available"]
    data=client.get(base+"/ml")
    assert data.status_code==200 and data.json()["status"]=="predicted"
    assert client.get(base+"/ml/history").json()
    assert client.get(f"/api/runs/{run.meta['run_id']}/customers/WRONG/ml").status_code==404
    assert client.get("/api/runs/WRONG/customers/C1/ml").status_code==404
    assert client.get("/api/health").json()=={"status":"ok"}
