import copy
import datetime as dt
import json
import numpy as np
import pandas as pd
import pytest
from ml.sleep.config import Config,require_approval,require_freeze,fingerprint
from ml.sleep.data_validation import validate_frames
from ml.sleep.features import select_features,validate_masks
from conftest import write_synthetic_approval


def test_default_flags_protect_all_stages():
    c=Config()
    assert c.mode=='validate'
    assert not any((c.run_final_test,c.run_grouped_outer,c.run_sensitivity_test,c.run_midpoint,c.run_export,c.run_feature_experiments,c.run_tuning))


def test_approval_fail_closed(synthetic_bundle,synthetic_config,tmp_path):
    bundle,_,_=synthetic_bundle;c=synthetic_config
    with pytest.raises(PermissionError):require_approval(c,bundle,'develop')
    payload,path=write_synthetic_approval(c,bundle,tmp_path,['develop'])
    assert require_approval(c,bundle,'develop')['approved']
    for key,value in [('preprocessing_merged_to_main',False),('config_fingerprint','wrong'),('approved_at_utc','2026-01-01T00:00:00'),('reviewed_evidence',{}),('authorized_scopes',[])]:
        altered=payload|{key:value};path.write_text(json.dumps(altered))
        with pytest.raises(PermissionError):require_approval(c,bundle,'develop')
    path.write_text(json.dumps(payload))
    with pytest.raises(PermissionError):bundle.partition('test')


def test_freeze_checksum_is_pinned_by_human_approval(synthetic_bundle,synthetic_config,tmp_path):
    bundle,_,_=synthetic_bundle;c=synthetic_config
    approval,path=write_synthetic_approval(c,bundle,tmp_path,['final_test'])
    from ml.sleep.logging_utils import dependency_environment
    body={**bundle.fingerprints,'config_fingerprint':c.config_fingerprint,'environment_fingerprint':fingerprint(dependency_environment()),'frozen_at_utc':'2026-01-01T00:00:00Z','approved_by':'synthetic-test','authorized_protocols':['final_test'],'selection':{'model_name':'ridge','experiment_id':'E0'}}
    freeze={'frozen_payload':body,'freeze_fingerprint':fingerprint(body)}
    f=tmp_path/'SYNTHETIC_FREEZE.json';f.write_text(json.dumps(freeze));c.frozen_config=str(f)
    with pytest.raises(PermissionError):require_freeze(c,bundle,'final_test')
    approval['approved_freeze_fingerprint']=freeze['freeze_fingerprint'];path.write_text(json.dumps(approval))
    assert require_freeze(c,bundle,'final_test')['selection']['model_name']=='ridge'
    body['selection']['model_name']='random_forest';f.write_text(json.dumps({'frozen_payload':body,'freeze_fingerprint':fingerprint(body)}))
    with pytest.raises(PermissionError):require_freeze(c,bundle,'final_test')


def test_features_and_derivatives_respect_groups(synthetic_bundle):
    b,_,_=synthetic_bundle
    for e in ['E0','E1','E2','E3','E4','E5']:
        cols=select_features(b.schema,e)
        assert 'sleep_tst_prev' in cols
        assert not any(c.startswith('target_') or c in ('participant_id','cutoff_date','split','weekday_sin','exercise_load_prev') for c in cols)
    assert not any(n.startswith('fatigue') for n in select_features(b.schema,'E0'))
    assert 'fatigue_age_days_missing' in select_features(b.schema,'E1')
    assert 'rhr_baseline_past28d' in select_features(b.schema,'E2')
    assert 'sleep_tst_baseline_past28d' not in select_features(b.schema,'E4')


@pytest.mark.parametrize('violation',['duplicate','window','boundary','scenario','mask','shared','group','reproducibility'])
def test_contract_rejects_violations(synthetic_bundle,violation):
    b,m,g=synthetic_bundle;frame=b.frame.drop(columns=['split','outer_test_fold']).copy();shared=b.shared.copy();meta=copy.deepcopy(b.metadata);m=m.copy();g=g.copy()
    if violation=='duplicate':frame=pd.concat([frame,frame.iloc[[0]]])
    elif violation=='window':frame.loc[0,'target_sleep_start']=frame.loc[0,'cutoff_wallclock']
    elif violation=='boundary':frame.loc[0,'target_sleep_end']=pd.Timestamp('2020-02-01T08:00:00')
    elif violation=='scenario':frame.loc[0,'scenario']='offset_plus1'
    elif violation=='mask':frame.loc[0,'steps_prev_missing']=0
    elif violation=='shared':shared.loc[0,'sleep_tst_prev']=1
    elif violation=='group':g.loc[0,'outer_test_fold']=3
    else:meta['validation']=[v for v in meta['validation'] if v['test']!='deterministic_rebuild_frames_and_parquet_hashes']
    with pytest.raises(ValueError):validate_frames(frame,shared,b.schema,m,g,meta,'primary')


def test_optional_missingness_preserves_all_rows(synthetic_bundle):
    b,m,g=synthetic_bundle;frame=b.frame.drop(columns=['split','outer_test_fold']).copy()
    result,report=validate_frames(frame,b.shared,b.schema,m,g,b.metadata,'primary')
    assert len(result)==len(frame) and frame.steps_prev.isna().all()
    assert report['protected_outcomes_disclosed'] is False
    assert not any('distribution' in key or 'mae' in key for key in report)
