"""Synthetic fixtures only. No PMData model fitting is performed by this suite."""
from dataclasses import replace
import datetime as dt
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from ml.cognitive.config import Config,file_hash,fingerprint
from ml.cognitive.feature_sets import read_schema
from ml.cognitive.data_loader import DataBundle


@pytest.fixture
def schema():
    # Approved column names/types are a contract, not participant data.
    return read_schema(ROOT.parent/'pmdata_preprocessing/research/feature_schema.csv')


@pytest.fixture
def frame(schema):
    dates=[dt.date(2020,1,d) for d in (2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30)]+[dt.date(2020,2,d) for d in range(1,29)]+[dt.date(2020,3,d) for d in range(1,4)]
    rows=[]
    for person in range(8):
        for i,day in enumerate(dates):
            r={c:np.nan for c in schema.name}
            for c in schema[schema.feature_allowlist].name:
                if '_observed_n_' in c or c.startswith('sleep_observed_n_'):r[c]=0
            score=2 if (i+person)%2 else 3
            r.update(participant_id=f's{person:02}',cutoff_date=day,feature_window_end=day-dt.timedelta(days=1),wellness_window_end=day-dt.timedelta(days=1),cutoff_wallclock=dt.datetime.combine(day,dt.time(20)),cutoff_datetime_utc=pd.NaT,timezone_status='unresolved_device_wallclock',scenario='primary',preprocessing_version='pmdata-preprocessing-1.0.0',core_eligible=True,sleep_prev_log_id=f'sleep-{person}-{i}',sleep_prev_end=dt.datetime.combine(day-dt.timedelta(days=1),dt.time(7)),sleep_prev_main_count=1,sleep_tst_prev=380+person+20*((i+person)%2),sleep_midpoint_sin_prev=.5,sleep_midpoint_cos_prev=np.sqrt(.75),sleep_age_days=1.,fatigue_prev=float(score),fatigue_age_days=1.,target_fatigue_score=score,target_elevated_fatigue=score<=2,target_fatigue_date=day+dt.timedelta(days=1),target_fatigue_effective_time=dt.datetime.combine(day+dt.timedelta(days=1),dt.time(8)),target_source_available_at=pd.NaT,target_availability_status='assumed',target_fatigue_effective_utc=pd.Timestamp(dt.datetime.combine(day+dt.timedelta(days=1),dt.time(8)),tz='UTC'),split='train' if day.month==1 else 'validation' if day.month==2 else 'test',outer_test_fold=person%4)
            for c in schema.name:
                if c.endswith('_missing') and c[:-8] in r:r[c]=int(pd.isna(r[c[:-8]]))
            rows.append(r)
    return pd.DataFrame(rows)


@pytest.fixture
def config(tmp_path):
    return Config(mode='develop',output_root=str(tmp_path/'runs'),requested_device='cpu',fast_mode=True,trials=1,top_k=1,models=('logistic',),feature_experiments=('E0',),run_tuning=False,run_explainability=False,bootstrap_replicates=10,calibration_min_samples=5,calibration_min_class=1)


@pytest.fixture
def data(frame,schema):
    fps=dict(preprocessing_fingerprint='preprocessing',dataset_fingerprint='dataset',schema_fingerprint='schema',split_fingerprint='splits',history_fingerprint=None)
    return DataBundle(frame,schema,frame[['participant_id','cutoff_date','split']].assign(task='fatigue',scenario='primary'),frame[['participant_id','cutoff_date','outer_test_fold']],{'version':'pmdata-preprocessing-1.0.0','config':{'wellness_lag':1,'scenario':'primary'}},fps,None,{'software_fixture':True})


@pytest.fixture
def approved(config,data,tmp_path):
    record=dict(approved=True,task='fatigue',approved_by='SYNTHETIC SOFTWARE TEST ONLY',approved_at_utc='2020-01-01T00:00:00+00:00',preprocessing_reviewed=True,preprocessing_version=data.metadata['version'],preprocessing_merged_to_main=True,gate_status='CONDITIONAL GO',authorized_scopes=['development'],config_fingerprint=config.config_fingerprint,reviewed_evidence={k:True for k in ('mandatory_validation','audit_reconciliation','timestamp_assumptions','shared_contract')},**data.fingerprints)
    path=tmp_path/'synthetic_approval.json';path.write_text(json.dumps(record))
    return replace(config,approval_record=str(path)),record
