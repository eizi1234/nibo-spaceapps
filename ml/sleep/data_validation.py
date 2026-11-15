"""Read-only Agent 2 contracts. Protected targets are never summarized by validation."""
from dataclasses import dataclass
import datetime as dt
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .config import KEYS,TARGET,file_hash,fingerprint
from .features import read_schema,select_features,validate_masks


@dataclass
class DataBundle:
    frame: pd.DataFrame
    shared: pd.DataFrame
    schema: pd.DataFrame
    metadata: dict
    fingerprints: dict
    report: dict

    def partition(self,name,authorized=False):
        if name in ('test','grouped_all') and not authorized:raise PermissionError('Protected outcomes require stage approval and freeze')
        if name=='grouped_all':return self.frame.copy()
        if name not in ('train','validation','test'):raise ValueError('Unknown partition')
        return self.frame[self.frame.split.eq(name)].copy()


def _date(series):return pd.to_datetime(series).dt.normalize()


def validate_frames(frame,shared,schema,manifest,grouped,metadata,scenario):
    checks={}
    def need(name,condition):
        checks[name]=bool(condition)
        if not checks[name]:raise ValueError(f'Contract failure: {name}')
    required=set(KEYS+[TARGET,'core_eligible','sleep_tst_prev','cutoff_wallclock','cutoff_datetime_utc',
        'feature_window_end','target_sleep_start','target_sleep_end','target_candidate_count','scenario'])
    need('required_columns',required<=set(frame))
    need('unique_keys',not frame.duplicated(KEYS).any() and not shared.duplicated(KEYS).any())
    need('scenario_isolation',frame.scenario.eq(scenario).all() and shared.scenario.eq(scenario).all())
    need('shared_has_no_targets',not any(c.startswith('target_') for c in shared))
    need('core_valid',frame.core_eligible.fillna(False).all() and frame.sleep_tst_prev.between(1,1440).all())
    need('labels_finite_valid',np.isfinite(frame[TARGET].astype(float)).all() and frame[TARGET].between(1,1440).all())
    day=_date(frame.cutoff_date);wall=pd.to_datetime(frame.cutoff_wallclock)
    need('naive_wallclock',wall.dt.tz is None and wall.eq(day+pd.Timedelta(hours=20)).all())
    need('utc_cutoff_unresolved',frame.cutoff_datetime_utc.isna().all())
    need('history_exact_t_minus1',_date(frame.feature_window_end).eq(day-pd.Timedelta(days=1)).all())
    if 'sleep_prev_end' in frame:need('previous_sleep_end_date',_date(frame.sleep_prev_end).eq(day-pd.Timedelta(days=1)).all())
    start=pd.to_datetime(frame.target_sleep_start);end=pd.to_datetime(frame.target_sleep_end)
    need('target_strict_window',start.gt(wall).all() and start.lt(day+pd.Timedelta(days=1,hours=12)).all())
    need('unique_main_candidate',frame.target_candidate_count.eq(1).all())
    need('tst_elapsed_consistency',end.gt(start).all() and frame[TARGET].le((end-start).dt.total_seconds()/60+1).all())
    validate_masks(frame,schema);checks['mask_consistency']=True
    for experiment in ('E0','E1','E2','E3','E4','E5'):
        need('allowlist_'+experiment,set(select_features(schema,experiment))<=set(frame))
    features=schema.loc[(schema.role=='feature')&schema.feature_allowlist,'name'].tolist()
    left=frame.set_index(KEYS)[features]
    right=shared.set_index(KEYS).loc[left.index,features]
    try:pd.testing.assert_frame_equal(left,right,check_exact=True)
    except AssertionError as exc:raise ValueError('Task/shared feature values differ') from exc
    checks['shared_task_feature_equality']=True
    m=manifest[(manifest.task=='sleep')&(manifest.scenario==scenario)].copy()
    need('manifest_unique',not m.duplicated(KEYS).any())
    m=m[m.split!='purged']
    need('manifest_exact_membership',set(map(tuple,m[KEYS].astype(str).to_numpy()))==set(map(tuple,frame[KEYS].astype(str).to_numpy())))
    result=frame.merge(m[KEYS+['split']],on=KEYS,validate='one_to_one')
    need('no_unknown_splits',result.split.isin(['train','validation','test']).all())
    dates=_date(result.cutoff_date);ends=_date(result.target_sleep_end)
    ranges={'train':('2019-11-01','2020-01-31'),'validation':('2020-02-01','2020-02-29'),'test':('2020-03-01','2020-03-31')}
    need('horizon_purges',~dates.isin(pd.to_datetime(['2020-01-31','2020-02-29'])).any())
    for name,(first,last) in ranges.items():
        idx=result.split.eq(name)
        need('split_boundaries_'+name,dates[idx].between(first,last).all() and ends[idx].between(first,last).all())
        if 'target_source_available_at' in result:
            arrival=pd.to_datetime(result.loc[idx,'target_source_available_at'],utc=True)
            # A known zoned arrival with unresolved UTC cutoff should have been purged.
            need('arrival_unresolved_rejected_'+name,arrival.isna().all())
    g=grouped[(grouped.task=='sleep')&(grouped.scenario==scenario)]
    need('grouped_keys_unique',not g.duplicated(KEYS).any())
    need('grouped_exact_membership',set(map(tuple,g[KEYS].astype(str).to_numpy()))==set(map(tuple,frame[KEYS].astype(str).to_numpy())))
    need('subject_single_outer_fold',g.groupby('participant_id').outer_test_fold.nunique().eq(1).all())
    need('four_outer_folds',set(g.outer_test_fold)=={0,1,2,3})
    result=result.merge(g[KEYS+['outer_test_fold']],on=KEYS,validate='one_to_one')
    need('upstream_checks_passed',bool(metadata.get('validation')) and all(r.get('passed') is True for r in metadata['validation']))
    required_upstream={'historical_lineage_end','unknown_availability_not_verified','known_late_arrival_rejected','core_exact_previous_sleep',
        'fatigue_exact_next_day','sleep_strict_target_window','splits_actual_outcomes_contained','grouped_subject_isolation',
        'deterministic_rebuild_frames_and_parquet_hashes','missing_masks_exact','optional_missingness_retains_rows',
        'baseline_14_gate','rolling_minimums','circular_reference_abstains','no_future_counts'}
    need('mandatory_upstream_evidence',required_upstream<={r['test'] for r in metadata['validation']})
    # No means, histograms, quantiles, class support or performance of test outcomes.
    report=dict(status='software_contract_valid',scenario_id=scenario,checks=checks,
        rows=len(result),participants=int(result.participant_id.nunique()),
        split_row_counts=result.groupby('split').size().to_dict(),
        protected_outcomes_disclosed=False,approval_inferred=False,
        limitations=['Naive device wallclock; UTC cutoff unresolved','Unknown ingestion remains assumed'])
    return result,report


def load_bundle(config):
    root=Path(config.data_dir)
    required=('sleep_dataset.parquet','shared_features.parquet','split_manifest.csv','grouped_split_manifest.csv','preprocessing_run.json')
    for name in required:
        if not (root/name).is_file():raise FileNotFoundError(f'Required Agent 2 artifact missing: {root/name}')
    metadata=json.loads((root/'preprocessing_run.json').read_text())
    if metadata.get('version')!='pmdata-preprocessing-1.0.0':raise ValueError('Unapproved preprocessing version')
    if metadata.get('config',{}).get('scenario')!=config.scenario_id:raise ValueError('Scenario config mismatch')
    for name in required[:-1]:
        if metadata.get('artifacts_sha256',{}).get(name)!=file_hash(root/name):raise ValueError(f'Artifact hash mismatch: {name}')
    schema=read_schema(config.schema_path)
    frame=pd.read_parquet(root/'sleep_dataset.parquet')
    shared=pd.read_parquet(root/'shared_features.parquet')
    manifest=pd.read_csv(root/'split_manifest.csv')
    grouped=pd.read_csv(root/'grouped_split_manifest.csv')
    for table in (frame,shared,manifest,grouped):table['cutoff_date']=pd.to_datetime(table.cutoff_date).dt.date
    frame,report=validate_frames(frame,shared,schema,manifest,grouped,metadata,config.scenario_id)
    reports=Path(config.reports_root)
    for name in ('preprocessing_report.md','leakage_test_report.md','delivery_integrity.json'):
        if not (reports/name).is_file():raise FileNotFoundError(f'Upstream gate evidence missing: {reports/name}')
    fp=dict(preprocessing_fingerprint=file_hash(root/'preprocessing_run.json'),schema_fingerprint=file_hash(config.schema_path),
        split_fingerprint=fingerprint({name:file_hash(root/name) for name in ('split_manifest.csv','grouped_split_manifest.csv')}),
        dataset_fingerprint=file_hash(root/'sleep_dataset.parquet'))
    report.update(fp,preprocessing_version=metadata['version'])
    return DataBundle(frame,shared,schema,metadata,fp,report)
