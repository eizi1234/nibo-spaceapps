"""Synthetic fixtures only. These are never PMData scientific training inputs."""
from pathlib import Path
import sys
import datetime as dt
import numpy as np
import pandas as pd
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from ml.sleep.config import Config,TARGET
from ml.sleep.data_validation import DataBundle
from ml.sleep.features import read_schema


@pytest.fixture
def synthetic_bundle():
    # Schema definitions only; no participant rows or private Agent 2 inputs.
    schema=pd.read_json(Path(__file__).parent/'fixtures/feature_schema.json')
    dates=pd.to_datetime(['2019-12-04','2019-12-05','2019-12-06','2020-01-29','2020-01-30','2020-02-05','2020-02-06','2020-03-05','2020-03-06'])
    rows=[]
    features=schema[schema.role.eq('feature')]
    for person in range(8):
        for i,t in enumerate(dates):
            values={name:(np.nan if 'score' in name or name.startswith('steps_') else float((person+i)%5+1)) for name in features.name if not name.endswith('_missing')}
            values.update(sleep_tst_prev=380+person*3+i,sleep_tst_baseline_past28d=390.,sleep_observed_n_3d=3,sleep_observed_n_7d=7,rhr_observed_n_28d=20,sleep_tst_observed_n_28d=20,fatigue_observed_n_28d=20,sleep_reference_observed_n_28d=20)
            for name in features.name:
                if name.endswith('_missing'):values[name]=int(pd.isna(values[name[:-8]]))
            values.update(participant_id=f'synthetic-p{person}',cutoff_date=t.date(),feature_window_end=(t-pd.Timedelta(days=1)).date(),wellness_window_end=(t-pd.Timedelta(days=1)).date(),
                cutoff_wallclock=t+pd.Timedelta(hours=20),cutoff_datetime_utc=pd.NaT,core_eligible=True,scenario='primary',
                sleep_prev_end=t-pd.Timedelta(days=1)+pd.Timedelta(hours=7),target_sleep_start=t+pd.Timedelta(hours=23),target_sleep_end=t+pd.Timedelta(days=1,hours=7),
                target_sleep_tst_minutes=400+person*3+i,target_candidate_count=1,target_source_available_at=pd.NaT,
                target_midpoint_sin=.7,target_midpoint_cos=.7,preprocessing_version='pmdata-preprocessing-1.0.0')
            rows.append(values)
    frame=pd.DataFrame(rows)
    shared=frame.drop(columns=[n for n in frame if n.startswith('target_')]).copy()
    manifest=frame[['participant_id','cutoff_date']].copy();manifest['task']='sleep';manifest['scenario']='primary'
    manifest['split']=['train' if d<dt.date(2020,2,1) else 'validation' if d<dt.date(2020,3,1) else 'test' for d in frame.cutoff_date]
    manifest['reason']='eligible'
    grouped=manifest[['participant_id','cutoff_date','task','scenario']].copy()
    grouped['outer_test_fold']=[int(pid[-1])%4 for pid in grouped.participant_id]
    # Simulated upstream evidence strictly for software unit tests, never a real approval.
    checks = ('historical_lineage_end','unknown_availability_not_verified','known_late_arrival_rejected','core_exact_previous_sleep','fatigue_exact_next_day','sleep_strict_target_window','splits_actual_outcomes_contained','grouped_subject_isolation','deterministic_rebuild_frames_and_parquet_hashes','missing_masks_exact','optional_missingness_retains_rows','baseline_14_gate','rolling_minimums','circular_reference_abstains','no_future_counts')
    metadata={'version':'pmdata-preprocessing-1.0.0','validation':[{'test':key,'passed':True} for key in checks],'synthetic_fixture':True}
    fingerprints={k:'synthetic-'+k for k in ('preprocessing_fingerprint','schema_fingerprint','split_fingerprint','dataset_fingerprint')}
    from ml.sleep.data_validation import validate_frames
    merged,report=validate_frames(frame,shared,schema,manifest,grouped,metadata,'primary')
    return DataBundle(merged,shared,schema,metadata,fingerprints,report),manifest,grouped


@pytest.fixture
def synthetic_config(tmp_path):
    return Config(output_root=str(tmp_path/'private-software-tests'),mode='develop',device='cpu',trials=2,fast_trials=2,
        fast_mode=True,top_k=1,cpu_threads=1,bootstrap_replicates=10,model_names=['ridge'],experiment_ids=['E0'],run_baselines=True,run_feature_experiments=True)


def write_synthetic_approval(config,bundle,tmp_path,scopes):
    import json
    path=tmp_path/'SYNTHETIC_TEST_ONLY_APPROVAL.json'
    payload={'approved':True,'preprocessing_reviewed':True,'preprocessing_merged_to_main':True,'task':'sleep',
        'gate_status':'CONDITIONAL GO','reviewed_evidence':{k:True for k in ('mandatory_validation','audit_reconciliation','timestamp_assumptions','shared_contract')},
        'approved_by':'synthetic-software-test-fixture','approved_at_utc':'2026-01-01T00:00:00+00:00',
        'preprocessing_version':bundle.metadata['version'],'authorized_scopes':scopes,'config_fingerprint':config.config_fingerprint,
        'synthetic_software_test':True,**{k:v for k,v in bundle.fingerprints.items() if k!='dataset_fingerprint'}}
    path.write_text(json.dumps(payload));config.approval_record=str(path)
    return payload,path
