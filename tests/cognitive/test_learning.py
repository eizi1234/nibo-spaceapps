from dataclasses import replace
import datetime as dt
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import average_precision_score
from ml.cognitive.preprocessing import MedianImputer
from ml.cognitive.models import fit_model,initial_params,DeviceError,gpu_failure
from ml.cognitive.feature_sets import columns_for
from ml.cognitive.calibration import CalibrationState,calibrate_and_threshold
from ml.cognitive.evaluation import metrics,choose_threshold,cluster_bootstrap
from ml.cognitive.baselines import baseline_scores
from ml.cognitive.export import save_bundle
from ml.cognitive.inference import predict_fatigue


def test_imputer_train_only_and_all_null():
    train=np.array([[1,np.nan],[3,np.nan]])
    imputer=MedianImputer().fit(train)
    assert imputer.statistics_.tolist()==[2.,0.]
    np.testing.assert_array_equal(imputer.transform([[np.nan,7]]),[[2,7]])
    imputer.transform([[100000,np.nan]])
    assert imputer.statistics_.tolist()==[2.,0.]


@pytest.mark.parametrize('name',['logistic','random_forest','lightgbm','xgboost','catboost'])
def test_five_cpu_factories_synthetic_fit_reload(name,config,data,tmp_path):
    features=columns_for(data.schema,'E0')
    model=fit_model(name,features,data.partition('train').head(100),data.partition('validation').head(40),config,params=initial_params(name,True))
    val=data.partition('validation').head(20)
    scores=model.scores(val)
    assert np.isfinite(scores).all() and ((scores>=0)&(scores<=1)).all()
    assert model.actual_device=='cpu'
    state=CalibrationState()
    path=tmp_path/name
    save_bundle(path,model,state,{'model_version':'SYNTHETIC-SOFTWARE-ONLY','ordered_feature_schema':features},val,software_fixture=True)
    result=predict_fatigue(val.iloc[0].to_dict(),path)
    assert result['status']=='ok' and result['fatigue_risk_probability'] is None
    assert result['fatigue_risk_score']==pytest.approx(scores[0],abs=1e-6)


def test_actual_ap_and_one_class_handling():
    y=[0,1,0,1];scores=[.1,.8,.3,.6]
    result=metrics(y,scores,participants=['a','a','b','b'])
    assert result['average_precision']==average_precision_score(y,scores)
    assert result['participant_defined_counts']['roc_auc']==2
    one=metrics([0,0],[.1,.2])
    assert one['roc_auc'] is None and one['average_precision'] is None and one['recall'] is None
    assert one['specificity']==1


def test_threshold_and_cluster_bootstrap():
    threshold,details=choose_threshold([0,1,0,1],[.1,.8,.3,.6])
    assert 0<=threshold<=1 and details['status']=='selected'
    result=cluster_bootstrap([0,1,0,1],[.1,.8,.3,.6],['a','a','b','b'],replicates=10)
    assert result['clusters']==2 and result['invalid_replicates']==0 and result['interval_95']==[1.,1.]


def test_baselines_no_history_fallback(data):
    scores,coverage=baseline_scores(data.partition('train'),data.partition('validation'))
    assert 'B2_PERSONAL_PREVALENCE' not in scores
    assert any(c.get('status')=='blocked' for c in coverage)
    assert len(scores['B1_PERSISTENCE'])==len(data.partition('validation'))


def test_personal_baseline_calendar_and_future_perturbation(data):
    evaluation=data.partition('validation').iloc[:1].copy();r=evaluation.iloc[0]
    history=[]
    for i in range(1,29):
        date=r.cutoff_date-dt.timedelta(days=i)
        history.append(dict(participant_id=r.participant_id,date=date,value=2,effective_time=dt.datetime.combine(date,dt.time(8)),source_available_at=pd.NaT))
    history=pd.DataFrame(history)
    a,c=baseline_scores(data.partition('train'),evaluation,history)
    assert a['B2_PERSONAL_PREVALENCE'][0]==1
    future=pd.DataFrame([dict(participant_id=r.participant_id,date=r.cutoff_date+dt.timedelta(days=1),value=5,effective_time=dt.datetime.combine(r.cutoff_date+dt.timedelta(days=1),dt.time(8)),source_available_at=pd.NaT)])
    b,_=baseline_scores(data.partition('train'),evaluation,pd.concat([history,future],ignore_index=True))
    assert a['B2_PERSONAL_PREVALENCE'].tolist()==b['B2_PERSONAL_PREVALENCE'].tolist()
    # 13 calendar observations cannot satisfy min14; never use sparse targets.
    short,_=baseline_scores(data.partition('train'),evaluation,history.iloc[:13])
    assert short['B2_PERSONAL_PREVALENCE'][0]==data.partition('train').target_elevated_fatigue.mean()


def test_inference_missing_unusable_and_stale_core(tmp_path):
    assert predict_fatigue({'sleep_tst_prev':None})['status']=='insufficient_data'
    assert predict_fatigue({'sleep_tst_prev':400,'core_eligible':False})['status']=='insufficient_data'
    assert predict_fatigue({'sleep_tst_prev':400,'cutoff_date':'2020-01-05','sleep_prev_end':'2020-01-01T07:00'})['status']=='insufficient_data'
    assert predict_fatigue({'sleep_tst_prev':400},tmp_path/'absent')['status']=='unavailable'
    path=tmp_path/'bad';path.mkdir();(path/'model.joblib').write_bytes(b'not a model')
    assert predict_fatigue({'sleep_tst_prev':400},path)['status']=='unavailable'


def test_device_errors_classified_and_data_errors_not():
    assert gpu_failure(DeviceError('Library silently fell back from requested GPU'))
    assert gpu_failure(RuntimeError('CUDA driver unavailable'))
    assert not gpu_failure(ValueError('Missing feature schema'))


def test_calibration_train_oof_and_disjoint_threshold(config,data):
    features=columns_for(data.schema,'E0')
    model=fit_model('logistic',features,data.partition('train'),data.partition('validation'),config)
    state=calibrate_and_threshold(model,data.partition('train'),data.partition('validation'),config,adequacy_approved=False)
    assert state.evidence['oof_n']>0 and state.evidence['partition_overlap']==0
    assert state.probability_verified is False
