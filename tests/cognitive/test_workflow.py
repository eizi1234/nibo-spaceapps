from dataclasses import replace
import json
from pathlib import Path
import time
import numpy as np
import pytest
from ml.cognitive.experiment_logger import Run
from ml.cognitive.experiments import development,final_evaluation,grouped_evaluation,export_selected,scenario_context
from ml.cognitive.models import fit_model,initial_params
from ml.cognitive.feature_sets import columns_for
from ml.cognitive.tuning import tune


def authorize_protected(config,record,freeze,scope):
    record['authorized_scopes'].append(scope)
    record['approved_freeze_fingerprint']=freeze['freeze_fingerprint']
    Path(config.approval_record).write_text(json.dumps(record))


def test_logger_failure_and_incremental_timing(config,data,tmp_path):
    run=Run(config,data,software_only=True)
    with pytest.raises(RuntimeError):
        with run.event('intentional-software-failure','software_test') as event:
            time.sleep(.001)
            raise RuntimeError('synthetic failure')
    records=[json.loads(x) for x in (run.path/'logs/experiment_log.jsonl').read_text().splitlines()]
    assert records[-1]['status']=='failed' and records[-1]['elapsed_seconds']>0
    assert records[-1]['started_at_utc'].endswith('+00:00')
    assert records[-1]['finished_at_utc'].endswith('+00:00')
    assert all(k in records[-1] for k in ('config_fingerprint','preprocessing_fingerprint','schema_fingerprint','split_fingerprint','model_version','evaluation_protocol','requested_device','actual_device'))


def test_fit_checkpoint_resume_does_not_fit_twice(config,data,monkeypatch):
    import ml.cognitive.models as models
    run=Run(config,data,software_only=True);train=data.partition('train');val=data.partition('validation');cols=columns_for(data.schema,'E0')
    first=fit_model('logistic',cols,train,val,config,run,'cached-fit')
    before=len(run.records)
    monkeypatch.setattr(models,'make_estimator',lambda *a,**k:(_ for _ in ()).throw(AssertionError('Must not refit')))
    again=fit_model('logistic',cols,train,val,config,run,'cached-fit')
    np.testing.assert_allclose(first.scores(val),again.scores(val))
    assert len(run.records)==before


def test_resume_signature_changed_config_rejected(config,data):
    run=Run(config,data,software_only=True)
    with pytest.raises(ValueError):Run(replace(config,resume_run=str(run.path),seed=3),data)


def test_resume_environment_change_rejected(config,data,monkeypatch):
    import ml.cognitive.experiment_logger as logging
    run=Run(config,data,software_only=True)
    original=logging.environment_snapshot
    monkeypatch.setattr(logging,'environment_snapshot',lambda:original()|{'python':'SYNTHETIC-DIFFERENT-ENVIRONMENT'})
    with pytest.raises(ValueError):Run(replace(config,resume_run=str(run.path)),data)


def test_tiny_optuna_file_storage_and_resume(config,data):
    run=Run(config,data,software_only=True)
    train=data.partition('train');val=data.partition('validation');features=columns_for(data.schema,'E0')
    result=tune('logistic','E0',features,train,val,config,run,budget=1)
    assert result is not None and (run.path/'studies/optuna.sqlite3').is_file()
    count=len(run.records)
    again=tune('logistic','E0',features,train,val,config,run,budget=1)
    assert result['trial_id']==again['trial_id'] and len(run.records)==count


def test_synthetic_development_freeze_exact_final_export_and_resume(approved,data,monkeypatch):
    import ml.cognitive.experiments as engine
    config,record=approved
    run=Run(config,data,software_only=True)
    result=development(data,config,run)
    assert result['protected_test']=='not opened'
    freeze=json.loads((run.path/'configs/frozen_config.json').read_text())
    assert freeze['checkpoint_sha256'] and freeze['calibration']['probability_verified'] is False
    count=len(run.records)
    again=development(data,config,run)
    assert again==result and len(run.records)==count
    # Protected phases must load the exact trained checkpoint, never refit.
    monkeypatch.setattr(engine,'fit_model',lambda *a,**k:(_ for _ in ()).throw(AssertionError('Protected stage attempted refit')))
    final_config=replace(config,mode='final',run_final_test=True,final_config=str(run.path/'configs/frozen_config.json'))
    authorize_protected(config,record,freeze,'final_chronological')
    final_run=Run(final_config,data,software_only=True)
    final=final_evaluation(data,final_config,final_run,freeze)
    assert final['status']=='protected_final_completed'
    export_config=replace(config,mode='export',run_export=True,final_config=str(run.path/'configs/frozen_config.json'))
    authorize_protected(config,record,freeze,'export')
    exported=export_selected(data,export_config,Run(export_config,data,software_only=True),freeze)
    assert exported['cpu_reload_verified']


def test_nested_grouped_synthetic_only_never_reuses_chronological_winner(approved,data):
    config,record=approved
    run=Run(config,data,software_only=True);development(data,config,run)
    freeze=json.loads((run.path/'configs/frozen_config.json').read_text())
    config=replace(config,mode='grouped',run_grouped_outer=True,final_config=str(run.path/'configs/frozen_config.json'))
    authorize_protected(config,record,freeze,'grouped_outer')
    grouped=Run(config,data,software_only=True)
    result=grouped_evaluation(data,config,grouped,freeze)
    assert result['folds']==4 and result['chronological_selection_changed'] is False
    saved=json.loads((grouped.path/'metrics/protected_grouped_pooled_metrics.json').read_text())
    assert 'macro_f1' not in saved and 'macro_f1' not in saved['participant_macro']
    assert all('macro_f1' not in p for p in saved['participant_metrics'].values())
    inner=[r for r in grouped.records if r['stage']=='inner_fold']
    assert inner and all(r['parent_event_id'] for r in inner)


def test_scenario_context_records_correct_fingerprints(config,data):
    run=Run(config,data,software_only=True)
    original=run.context.copy()
    data.metadata['config']['scenario']='offset_plus1';data.fingerprints['preprocessing_fingerprint']='different'
    with scenario_context(run,data):
        with run.event('scenario-child','software_test'):pass
    assert run.records[-1]['scenario_id']=='offset_plus1' and run.records[-1]['preprocessing_fingerprint']=='different'
    assert run.context==original


def test_group_calibration_abstains_insufficient_minority_support(config,data):
    import pandas as pd
    from ml.cognitive.experiments import _group_calibration
    frame=data._frame.copy();frame['target_elevated_fatigue']=False
    frame.loc[frame.groupby('participant_id').head(1).index,'target_elevated_fatigue']=True
    scores=pd.Series(.01,index=frame.index)
    state=_group_calibration(frame,scores,replace(config,calibration_min_class=5,calibration_min_samples=50),adequacy_approved=True)
    assert state.probability_verified is False
