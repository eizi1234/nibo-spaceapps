import json
import numpy as np
import pandas as pd
import pytest
from ml.sleep.preprocessing import StableMedianImputer,transformer
from ml.sleep.evaluation import regression_metrics,clustered_bootstrap
from ml.sleep.midpoint import decode_midpoint,circular_error,midpoint_metrics
from ml.sleep.models import fit_attempt,fit_model,ModelUnavailable
from ml.sleep.logging_utils import RunLogger
from ml.sleep.export import export_bundle
from ml.sleep.inference import SleepPredictor,predict_sleep


def test_train_only_empty_column_policy():
    train=np.array([[1,np.nan],[3,np.nan]])
    tr=transformer(True).fit(train)
    assert tr.named_steps['imputer'].statistics_.tolist()==[2,0]
    transformed=tr.transform([[1000,5]])
    assert transformed[0,0]==998 and transformed.shape[1]==2
    np.testing.assert_array_equal(tr.named_steps['imputer'].empty_training_columns_,[False,True])


def test_metrics_and_zero_persistence():
    m,_=regression_metrics([1,3,10],[2,3,8],['a','a','b'],[1,3,10])
    assert m['mae_minutes']==1 and m['participant_macro_mae_minutes']==1.25
    assert m['mean_signed_error_minutes']==pytest.approx(-1/3)
    assert m['rmse_minutes']==pytest.approx(np.sqrt(5/3))
    assert m['improvement_vs_persistence_pct'] is None
    boot=clustered_bootstrap([1,3,10],[2,3,8],['a','a','b'],[2,4,12],replicates=20)
    assert boot['replicates']==20 and boot['intervals']['mae_minutes']['valid_replicates']==20


def test_circular_midnight_and_abstention():
    assert circular_error([1435],[5])[0]==10
    minutes,valid=decode_midpoint([0,0,np.nan],[1,0,1])
    assert minutes[0]==0 and valid.tolist()==[True,False,False]


@pytest.mark.parametrize('name',['ridge','random_forest','lightgbm','xgboost','catboost'])
def test_all_factories_synthetic_fit_predict_cpu_reload(name,tmp_path):
    rng=np.random.default_rng(42)
    X=pd.DataFrame({'sleep_tst_prev':rng.normal(400,20,48),'rhr_prev':rng.normal(60,3,48),'rhr_prev_missing':0.})
    X.loc[0:10,'rhr_prev']=np.nan;X['rhr_prev_missing']=X.rhr_prev.isna().astype(int)
    y=X.sleep_tst_prev*.8+80
    params={'n_estimators':8} if name in ('random_forest','lightgbm','xgboost') else {'iterations':8} if name=='catboost' else {'alpha':1.}
    fit,times=fit_attempt(name,X.iloc[:32],y.iloc[:32],X.iloc[32:],y.iloc[32:],params,device='cpu',threads=1,early_stopping=3,verbose=False)
    assert np.isfinite(fit.predict(X)).all() and times['training_seconds']>=0
    schema=pd.DataFrame({'name':list(X),'role':'feature','feature_allowlist':True,'unit':['minutes','bpm','binary']})
    destination=tmp_path/name
    export_bundle(fit,{'model_version':'SYNTHETIC-SOFTWARE-TEST'},schema,destination,X.iloc[32:],synthetic_software_test=True)
    exported=json.loads((destination/'model_metadata.json').read_text())
    assert exported['environment']['python'] and exported['environment']['packages']['scikit-learn']
    from ml.sleep.config import fingerprint
    assert exported['environment_fingerprint']==fingerprint(exported['environment'])
    prediction=SleepPredictor(destination).predict(X.iloc[0].to_dict())
    assert prediction['sleep_tst_status']=='ok' and prediction['uncertainty'] is None
    assert SleepPredictor(destination).predict({'sleep_tst_prev':None})['sleep_tst_status']=='insufficient_data'
    assert SleepPredictor(destination).predict({'sleep_tst_prev':400,'core_eligible':False})['sleep_tst_status']=='insufficient_data'


def test_unavailable_artifact_returns_null(tmp_path):
    result=predict_sleep(tmp_path/'absent',{'sleep_tst_prev':400})
    assert result['sleep_tst_status']=='unavailable' and result['predicted_sleep_tst_minutes'] is None
