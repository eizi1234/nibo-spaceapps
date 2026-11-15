"""Synthetic on-disk processed fixtures exercise fail-closed serialized validation."""
from dataclasses import replace
import datetime as dt
import json
from pathlib import Path
import pandas as pd
import pytest
from ml.cognitive.config import file_hash
from ml.cognitive.data_loader import load_and_validate


@pytest.fixture
def serialized(config,frame,schema,tmp_path):
    directory=tmp_path/'processed';directory.mkdir()
    schema_path=tmp_path/'schema.csv';schema.to_csv(schema_path,index=False)
    reports=tmp_path/'reports';reports.mkdir()
    for name in ('preprocessing_report.md','leakage_test_report.md'):(reports/name).write_text('SYNTHETIC SOFTWARE FIXTURE ONLY')
    (reports/'delivery_integrity.json').write_text(json.dumps({'primary':{'all_validation_passed':True}}))
    frame.drop(columns=['split','outer_test_fold']).to_parquet(directory/'fatigue_dataset.parquet',index=False)
    shared=frame[[c for c in frame if not c.startswith('target_') and c not in ('split','outer_test_fold')]]
    shared.to_parquet(directory/'shared_features.parquet',index=False)
    frame[['participant_id','cutoff_date','split']].assign(task='fatigue',scenario='primary').to_csv(directory/'split_manifest.csv',index=False)
    frame[['participant_id','cutoff_date','outer_test_fold']].assign(task='fatigue',scenario='primary').to_csv(directory/'grouped_split_manifest.csv',index=False)
    metadata={'version':'pmdata-preprocessing-1.0.0','config':{'scenario':'primary','wellness_lag':1},'validation':[{'test':name,'passed':True} for name in ('historical_lineage_end','unique_keys','fatigue_exact_next_day','feature_allowlist_isolation','grouped_subject_isolation','deterministic_rebuild_frames_and_parquet_hashes')],'artifacts_sha256':{name:file_hash(directory/name) for name in ('fatigue_dataset.parquet','shared_features.parquet','split_manifest.csv','grouped_split_manifest.csv')}}
    (directory/'preprocessing_run.json').write_text(json.dumps(metadata))
    return replace(config,mode='validate',data_dir=str(directory),schema_path=str(schema_path),reports_root=str(reports)),directory,metadata


def update_hash(directory,metadata,name):
    metadata['artifacts_sha256'][name]=file_hash(directory/name)
    (directory/'preprocessing_run.json').write_text(json.dumps(metadata))


def test_valid_serialized_fixture_and_test_redaction(serialized):
    config,_,_=serialized
    bundle=load_and_validate(config)
    assert bundle.summary['protected_test_outcomes']=='redacted'
    assert 'test' not in bundle.summary['development_support']


@pytest.mark.parametrize('mutation',['invalid_label','wrong_target_date','duplicate_keys','wrong_fold','bad_hash','targets_in_shared','cross_split'])
def test_serialized_contract_violations_fail(serialized,mutation):
    config,directory,metadata=serialized
    if mutation in ('wrong_fold',):
        name='grouped_split_manifest.csv';table=pd.read_csv(directory/name);table.loc[0,'outer_test_fold']=3-table.loc[0,'outer_test_fold'];table.to_csv(directory/name,index=False)
    elif mutation=='targets_in_shared':
        name='shared_features.parquet';table=pd.read_parquet(directory/name);table['target_accidental']=1;table.to_parquet(directory/name,index=False)
    elif mutation=='cross_split':
        name='split_manifest.csv';table=pd.read_csv(directory/name);table.loc[0,'split']='test';table.to_csv(directory/name,index=False)
    else:
        name='fatigue_dataset.parquet';table=pd.read_parquet(directory/name)
        if mutation=='invalid_label':table.loc[0,'target_fatigue_score']=0
        elif mutation=='wrong_target_date':table.loc[0,'target_fatigue_date']=dt.date(2020,1,30)
        elif mutation=='duplicate_keys':table=pd.concat([table,table.iloc[[0]]],ignore_index=True)
        else:table.loc[0,'sleep_tst_prev']=123
        table.to_parquet(directory/name,index=False)
    if mutation!='bad_hash':update_hash(directory,metadata,name)
    with pytest.raises((ValueError,AssertionError)):load_and_validate(config)


@pytest.mark.parametrize('kind',['future_input','unknown_verified'])
def test_serialized_lineage_rejected(serialized,kind):
    config,directory,_=serialized
    diagnostics=directory/'diagnostics';diagnostics.mkdir()
    pd.DataFrame([dict(feature='sleep_tst_prev',cutoff_date=dt.date(2020,1,2),history_end=dt.date(2020,1,1),latest_event=dt.datetime(2020,1,3,7) if kind=='future_input' else dt.datetime(2020,1,1,7),source_available_at=pd.NaT,availability_status='verified' if kind=='unknown_verified' else 'assumed')]).to_parquet(diagnostics/'feature_lineage.parquet',index=False)
    with pytest.raises(ValueError):load_and_validate(config)
