from dataclasses import replace
import datetime as dt
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from ml.cognitive.config import EXPERIMENTS,fingerprint
from ml.cognitive.feature_sets import columns_for,validate_masks,read_schema,simulate_missing_modality
from ml.cognitive.approval import require_approval
from ml.cognitive.calibration import calibration_partitions


def test_all_six_experiments_and_derivatives(schema):
    for name,groups in EXPERIMENTS.items():
        cols=columns_for(schema,name)
        assert set(schema.set_index('name').loc[cols].group)<=set(groups)
        assert 'sleep_tst_prev' in cols
        assert not any(c.startswith('target_') or c in ('participant_id','cutoff_date','split') for c in cols)
        assert 'weekday_sin' not in cols and 'exercise_load_prev' not in cols
    assert not any(c.startswith('fatigue_') for c in columns_for(schema,'SUP_NO_FATIGUE'))
    assert not any(c in columns_for(schema,'E1') and schema.set_index('name').loc[c,'group']=='B' for c in columns_for(schema,'SUP_WEARABLE_ONLY'))


def test_metadata_cannot_be_approved(schema,tmp_path):
    schema.loc[schema.name.eq('target_fatigue_score'),'feature_allowlist']=True
    path=tmp_path/'schema.csv';schema.to_csv(path,index=False)
    with pytest.raises(ValueError):read_schema(path)


def test_masks_optional_rows_preserved(schema,frame):
    validate_masks(frame,schema)
    masked=simulate_missing_modality(frame,schema,['B','C'])
    validate_masks(masked,schema)
    assert len(masked)==len(frame) and masked.sleep_tst_prev.equals(frame.sleep_tst_prev)
    assert masked.fatigue_prev.isna().all() and masked.fatigue_prev_missing.eq(1).all()
    with pytest.raises(ValueError):simulate_missing_modality(frame,schema,['A'])


def test_bad_mask_fails(frame,schema):
    frame.loc[0,'rhr_prev_missing']=0
    with pytest.raises(ValueError):validate_masks(frame,schema)


def test_no_automatic_training_authorization(config,data):
    with pytest.raises(PermissionError):require_approval(config,data)
    with pytest.raises(PermissionError):data.partition('test')
    with pytest.raises(PermissionError):data.grouped_frame()


@pytest.mark.parametrize('field,value',[('task','sleep'),('approved',False),('preprocessing_reviewed',False),('preprocessing_merged_to_main',False),('config_fingerprint','wrong'),('dataset_fingerprint','wrong'),('authorized_scopes',[])])
def test_gate_rejects_missing_or_wrong_human_record(approved,data,field,value):
    config,record=approved
    record[field]=value;Path(config.approval_record).write_text(json.dumps(record))
    with pytest.raises(PermissionError):require_approval(config,data)


def test_freeze_integrity_and_protected_scope(approved,data):
    config,record=approved
    freeze=dict(config_fingerprint=config.config_fingerprint,preprocessing_fingerprint=data.fingerprints['preprocessing_fingerprint'],chronological_selection_frozen=True,refit_policy='train_only')
    from ml.cognitive.experiment_logger import code_fingerprint,environment_snapshot
    freeze.update(code_fingerprint=code_fingerprint(),environment_fingerprint=fingerprint(environment_snapshot()))
    freeze['freeze_fingerprint']=fingerprint(freeze)
    record['authorized_scopes']+=['final_chronological'];record['approved_freeze_fingerprint']=freeze['freeze_fingerprint']
    Path(config.approval_record).write_text(json.dumps(record))
    require_approval(config,data,'final_chronological',freeze)
    freeze['refit_policy']='train_plus_validation'
    with pytest.raises(PermissionError):require_approval(config,data,'final_chronological',freeze)


def test_calibration_threshold_partitions_disjoint(data):
    a,b=calibration_partitions(data.partition('validation'))
    assert set(a.index).isdisjoint(set(b.index))
    assert a.cutoff_date.max()<b.cutoff_date.min()


def test_group_subject_isolation(data):
    for fold in range(4):
        a=data._frame[data._frame.outer_test_fold.ne(fold)];b=data._frame[data._frame.outer_test_fold.eq(fold)]
        assert set(a.participant_id).isdisjoint(set(b.participant_id))
