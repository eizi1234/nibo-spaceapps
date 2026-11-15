import copy
import json
import numpy as np
import pandas as pd
import pytest
from ml.sleep.baselines import baseline_predictions
from ml.sleep.config import TARGET,fingerprint
from ml.sleep.features import select_features,matrix
from ml.sleep.logging_utils import RunLogger
from ml.sleep.experiments import development,grouped_evaluation
from ml.sleep.models import fit_model
from ml.sleep.tuning import optimize
from conftest import write_synthetic_approval


def test_rolling_median_calendar_and_fallback():
    shared=pd.DataFrame({'participant_id':['s']*5,'cutoff_date':pd.to_datetime(['2020-01-02','2020-01-03','2020-01-05','2020-01-08','2020-01-10']).date,
        'sleep_tst_prev':[100,300,500,700,900],'core_eligible':True})
    evaluation=pd.DataFrame({'participant_id':['s','s'],'cutoff_date':pd.to_datetime(['2020-01-08','2020-01-09']).date,'sleep_tst_prev':[700,800],'sleep_tst_baseline_past28d':[np.nan,600]})
    tr=pd.DataFrame({TARGET:[300,400]})
    out=baseline_predictions(tr,evaluation,shared)
    assert out['B0']['predictions'].tolist()==[350,350]
    assert out['B2']['predictions'].tolist()==[400,800]
    assert out['B2']['available_n']==1 and out['B2']['fallback_n']==1
    assert out['B3']['predictions'].tolist()==[700,600]
    # Adding future source observations cannot alter earlier baselines.
    future=pd.concat([shared,pd.DataFrame({'participant_id':['s'],'cutoff_date':[pd.Timestamp('2020-02-01').date()],'sleep_tst_prev':[9999],'core_eligible':[True]})])
    np.testing.assert_array_equal(out['B2']['predictions'],baseline_predictions(tr,evaluation,future)['B2']['predictions'])


def test_logger_unique_incremental_failure_and_resume(tmp_path):
    log=RunLogger(tmp_path,{'config_fingerprint':'synthetic'},label='synthetic_software_test')
    log.emit(dict(experiment_id='identity-override',status='blocked',config_fingerprint='scenario-specific'))
    with log.event('one','software_test') as event:event['answer']=1
    with pytest.raises(ValueError):
        with log.event('failure','software_test'):raise ValueError('synthetic expected failure')
    records=[json.loads(line) for line in (log.root/'logs/experiment_log.jsonl').read_text().splitlines()]
    assert [r['status'] for r in records]==['blocked','success','failed']
    assert records[0]['config_fingerprint']=='scenario-specific' and records[0]['elapsed_seconds'] is None
    assert all(r['elapsed_seconds']>=0 and r['finished_at_utc'].endswith('+00:00') for r in records[1:])
    resumed=RunLogger(tmp_path,{'config_fingerprint':'synthetic'},resume_dir=log.root)
    assert resumed.completed('one')
    with pytest.raises(ValueError):RunLogger(tmp_path,{'config_fingerprint':'changed'},resume_dir=log.root)
    assert RunLogger(tmp_path,{'config_fingerprint':'synthetic'}).run_id!=log.run_id


def test_tiny_optuna_sqlite_resume_synthetic(synthetic_config,tmp_path):
    c=synthetic_config;log=RunLogger(tmp_path/'studies',{'config_fingerprint':'synthetic-optuna'},label='synthetic_software_test')
    calls=[]
    def objective(params,trial):calls.append(trial.number);return abs(np.log10(params['alpha'])),dict(best_iteration=None)
    a=optimize('ridge','E0',objective,c,log)
    b=optimize('ridge','E0',objective,c,log)
    assert len(calls)==2 and a['params']==b['params']
    assert (log.root/'studies/optuna.sqlite3').is_file()


def test_gpu_fallback_separate_attempts_and_data_errors(monkeypatch,synthetic_config,tmp_path):
    import ml.sleep.models as models
    c=synthetic_config;c.device='auto'
    monkeypatch.setattr(models,'gpu_inventory',lambda:dict(available=True))
    calls=[]
    def attempt(*args,**kw):
        device=args[6] if len(args)>6 else kw['device'];calls.append(device)
        if device=='gpu':raise RuntimeError('CUDA synthetic failure')
        class Fit:resolved_params={};best_iteration=None
        return Fit(),dict(training_seconds=.01)
    monkeypatch.setattr(models,'fit_attempt',attempt)
    log=RunLogger(tmp_path,{'config_fingerprint':'synthetic-device'},label='synthetic_software_test')
    X=pd.DataFrame({'a':[1.,2.]})
    models.fit_model('xgboost',X,[1,2],None,None,c,log,'gpu-fallback')
    assert calls==['gpu','cpu'] and [r['status'] for r in log.events]==['failed','success']
    c.device='gpu'
    with pytest.raises(models.ModelUnavailable):models.fit_model('xgboost',X,[1,2],None,None,c,log,'explicit-gpu')
    def bad(*a,**k):raise ValueError('invalid target shape')
    monkeypatch.setattr(models,'fit_attempt',bad);c.device='auto'
    with pytest.raises(ValueError):models.fit_model('xgboost',X,[1,2],None,None,c,log,'bad-data')


def test_synthetic_development_no_test_scoring(synthetic_bundle,synthetic_config,tmp_path):
    b,_,_=synthetic_bundle;c=synthetic_config
    write_synthetic_approval(c,b,tmp_path,['develop'])
    log=RunLogger(tmp_path/'workflow',{'config_fingerprint':c.config_fingerprint},label='synthetic_software_test')
    result=development(b,c,log)
    assert result['selection']['experiment_id']=='E0'
    assert all(e.get('evaluation_partition')!='test' for e in log.events)
    assert (log.root/'metadata/selection_proposal.json').is_file()


def test_synthetic_nested_outer_selection_disjoint(synthetic_bundle,synthetic_config,tmp_path):
    b,_,_=synthetic_bundle;c=synthetic_config
    approval,path=write_synthetic_approval(c,b,tmp_path,['grouped_outer'])
    from ml.sleep.logging_utils import dependency_environment
    body=b.fingerprints|dict(config_fingerprint=c.config_fingerprint,environment_fingerprint=fingerprint(dependency_environment()),frozen_at_utc='2026-01-01T00:00:00Z',approved_by='synthetic-test',authorized_protocols=['grouped_outer'],chronological_selection_frozen=True,nested_selection_protocol='groupkfold_inner_full_matrix_v1',selection={'model_name':'ridge','experiment_id':'E0','params':{}})
    freeze={'frozen_payload':body,'freeze_fingerprint':fingerprint(body)}
    f=tmp_path/'SYNTHETIC_FREEZE.json';f.write_text(json.dumps(freeze));c.frozen_config=str(f)
    approval['approved_freeze_fingerprint']=freeze['freeze_fingerprint'];path.write_text(json.dumps(approval))
    log=RunLogger(tmp_path/'outer',{'config_fingerprint':c.config_fingerprint},label='synthetic_software_test')
    results=grouped_evaluation(b,c,log)
    assert len(results)==4
    assert all(r['n']==18 for r in results)
