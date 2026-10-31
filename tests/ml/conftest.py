from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from ews.ml.features import FEATURE_IDS, feature_signature
from ews.ml.train import train

@pytest.fixture(scope="module")
def model_data():
    rng=np.random.default_rng(42)
    rows=[]
    for i in range(100):
        y=i%2
        for month in ("2026-03-31","2026-04-30"):
            values={sid:float(rng.normal()) for sid in FEATURE_IDS}
            values["RB01"]=float(y*4+rng.normal(0,.1))
            rows.append({**values,"group":f"fixture:{i}","profile":"india","origin":month,
                "horizon_end":"2026-07-31","target":y})
    return pd.DataFrame(rows)

@pytest.fixture(scope="module")
def trained_model(tmp_path_factory,clean_ds,model_data):
    root=tmp_path_factory.mktemp("trained-ml")
    signature=feature_signature(clean_ds,"india")
    train(model_data,{"india":signature},{"fixture":"not-a-source-dataset"},root,rounds=20)
    return root
