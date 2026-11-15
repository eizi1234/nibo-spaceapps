"""Read-only processed-data contract. Protected outcomes have an explicit accessor."""
from dataclasses import dataclass
import datetime as dt
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .config import file_hash,fingerprint
from .feature_sets import read_schema,validate_masks

KEY=['participant_id','cutoff_date']
LABEL='target_elevated_fatigue'


def keyed(frame):
    out=frame.copy()
    out['participant_id']=out.participant_id.astype(str)
    out['cutoff_date']=pd.to_datetime(out.cutoff_date).dt.date
    return out


def scenario_directory(config,scenario=None):
    scenario=scenario or config.scenario_id
    if scenario in config.scenario_paths:return Path(config.scenario_paths[scenario])
    root=Path(config.data_dir)
    return root if scenario=='primary' else root/'sensitivity'/scenario


@dataclass
class DataBundle:
    _frame: pd.DataFrame
    schema: pd.DataFrame
    manifest: pd.DataFrame
    groups: pd.DataFrame
    metadata: dict
    fingerprints: dict
    history: pd.DataFrame | None
    summary: dict

    def partition(self,name,protected_authorized=False):
        if name not in ('train','validation','test'):raise ValueError('Unknown partition')
        if name=='test' and not protected_authorized:
            raise PermissionError('Protected test outcomes require approved freeze and explicit stage')
        return self._frame[self._frame.split.eq(name)].copy()

    def grouped_frame(self,protected_authorized=False):
        if not protected_authorized:raise PermissionError('Outer evaluation is protected')
        return self._frame.copy()


def _same_keys(a,b):
    return set(map(tuple,a[KEY].to_numpy()))==set(map(tuple,b[KEY].to_numpy()))


def load_and_validate(config,scenario=None):
    scenario=scenario or config.scenario_id
    directory=scenario_directory(config,scenario)
    paths={name:directory/name for name in ('fatigue_dataset.parquet','shared_features.parquet','split_manifest.csv','grouped_split_manifest.csv','preprocessing_run.json')}
    for path in list(paths.values())+[Path(config.schema_path)]:
        if not path.is_file():raise FileNotFoundError(f'Required processed artifact absent: {path}')
    metadata=json.loads(paths['preprocessing_run.json'].read_text())
    evidence_paths=[Path(config.reports_root)/n for n in ('preprocessing_report.md','leakage_test_report.md','delivery_integrity.json')]
    for evidence in evidence_paths:
        if not evidence.is_file():raise FileNotFoundError(f'Required upstream evidence absent: {evidence}')
    integrity=json.loads(evidence_paths[-1].read_text())
    if integrity.get(scenario,{}).get('all_validation_passed') is not True:raise ValueError('Serialized upstream validation evidence failed/absent')
    if metadata.get('version')!='pmdata-preprocessing-1.0.0':raise ValueError('Unreviewed preprocessing version')
    if metadata.get('config',{}).get('scenario')!=scenario:raise ValueError('Scenario metadata mismatch')
    checks=metadata.get('validation',[])
    if not checks or not all(c.get('passed') is True for c in checks):raise ValueError('Upstream validation failed/absent')
    required_checks={'historical_lineage_end','unique_keys','fatigue_exact_next_day','feature_allowlist_isolation','grouped_subject_isolation','deterministic_rebuild_frames_and_parquet_hashes'}
    if not required_checks.issubset({c['test'] for c in checks}):raise ValueError('Mandatory upstream evidence absent')
    hashes=metadata.get('artifacts_sha256',{})
    for name,path in paths.items():
        if name=='preprocessing_run.json':continue
        if hashes.get(name)!=file_hash(path):raise ValueError(f'Fingerprint mismatch: {name}')
    schema=read_schema(config.schema_path)
    frame=keyed(pd.read_parquet(paths['fatigue_dataset.parquet']))
    shared=keyed(pd.read_parquet(paths['shared_features.parquet']))
    manifest=keyed(pd.read_csv(paths['split_manifest.csv']))
    groups=keyed(pd.read_csv(paths['grouped_split_manifest.csv']))
    for name,table in [('dataset',frame),('shared',shared)]:
        if table.duplicated(KEY).any():raise ValueError(f'Duplicate {name} keys')
    manifest=manifest[manifest.task.eq('fatigue') & manifest.scenario.eq(scenario)].copy()
    groups=groups[groups.task.eq('fatigue') & groups.scenario.eq(scenario)].copy()
    if manifest.duplicated(KEY).any() or groups.duplicated(KEY).any():raise ValueError('Manifest cardinality violation')
    retained=manifest[manifest.split.isin(['train','validation','test'])]
    if not _same_keys(frame,retained) or not _same_keys(frame,groups):raise ValueError('Manifest key membership mismatch')
    if not frame.scenario.eq(scenario).all() or not shared.scenario.eq(scenario).all():raise ValueError('Mixed scenario inputs')
    if any(c.startswith('target_') for c in shared):raise ValueError('Shared table contains labels')
    frame=frame.merge(retained[KEY+['split']],on=KEY,validate='one_to_one')
    frame=frame.merge(groups[KEY+['outer_test_fold']],on=KEY,validate='one_to_one')
    if not groups.groupby('participant_id').outer_test_fold.nunique().eq(1).all() or set(groups.outer_test_fold)!={0,1,2,3}:
        raise ValueError('Invalid grouped subject assignment')
    if not frame.core_eligible.fillna(False).all() or not pd.to_numeric(frame.sleep_tst_prev).between(1,1440).all():
        raise ValueError('Invalid core sleep')
    validate_masks(frame,schema)
    # Necessary integrity checks below produce pass/fail only, never test outcome
    # summaries. Test distributions and scoring remain behind protected accessors.
    score=pd.to_numeric(frame.target_fatigue_score,errors='coerce')
    if not score.isin([1,2,3,4,5]).all() or not frame[LABEL].isin([True,False,0,1]).all() or not frame[LABEL].astype(int).eq(score.le(2).astype(int)).all():
        raise ValueError('Invalid fatigue target mapping')
    lag=int(metadata['config']['wellness_lag'])
    for r in frame.itertuples():
        prev=r.cutoff_date-dt.timedelta(days=1)
        if pd.Timestamp(r.feature_window_end).date()!=prev or pd.Timestamp(r.wellness_window_end).date()!=r.cutoff_date-dt.timedelta(days=lag):raise ValueError('Calendar lag violation')
        cutoff=pd.Timestamp(r.cutoff_wallclock)
        if cutoff.tzinfo is not None or cutoff.date()!=r.cutoff_date or cutoff.time()!=dt.time(20) or pd.notna(r.cutoff_datetime_utc):raise ValueError('Cutoff time contract violation')
        if pd.Timestamp(r.sleep_prev_end).date()!=prev:raise ValueError('Core sleep not exact t-1')
        if pd.Timestamp(r.target_fatigue_date).date()!=r.cutoff_date+dt.timedelta(days=1):raise ValueError('Fatigue target gap substitution')
        if pd.Timestamp(r.target_fatigue_effective_time).date()!=pd.Timestamp(r.target_fatigue_date).date():raise ValueError('Target timestamp/date mismatch')
        first,last={'train':(dt.date(2019,11,1),dt.date(2020,1,31)), 'validation':(dt.date(2020,2,1),dt.date(2020,2,29)), 'test':(dt.date(2020,3,1),dt.date(2020,3,31))}[r.split]
        if not first<=r.cutoff_date<=last or not first<=pd.Timestamp(r.target_fatigue_date).date()<=last or r.cutoff_date in (dt.date(2020,1,31),dt.date(2020,2,29)):raise ValueError('Split horizon/purge violation')
        available=r.target_source_available_at
        if pd.notna(available):
            available=pd.Timestamp(available)
            if available.tzinfo is not None or available.date()>last:raise ValueError('Known late/unresolved label availability')
    for count,value,minimum in [('sleep_observed_n_3d','sleep_tst_mean_3d',2),('sleep_observed_n_7d','sleep_tst_mean_7d',4),('sleep_observed_n_7d','sleep_tst_sd_7d',4),('rhr_observed_n_28d','rhr_baseline_past28d',14),('sleep_tst_observed_n_28d','sleep_tst_baseline_past28d',14),('fatigue_observed_n_28d','fatigue_baseline_past28d',14)]:
        if frame.loc[frame[count].lt(minimum),value].notna().any():raise ValueError('Minimum history gate violated')
    ref_invalid=frame.sleep_reference_observed_n_28d.lt(14)|frame.sleep_reference_concentration.lt(.5)
    if frame.loc[ref_invalid,['sleep_reference_sin','sleep_reference_cos']].notna().any().any():raise ValueError('Circular abstention violation')
    common=frame[shared.columns].sort_values(KEY).reset_index(drop=True)
    selected=shared.set_index(KEY).loc[pd.MultiIndex.from_frame(frame[KEY])].reset_index()[shared.columns].sort_values(KEY).reset_index(drop=True)
    pd.testing.assert_frame_equal(common,selected,check_exact=True)
    hp=Path(config.wellness_history_path) if config.wellness_history_path else directory/'diagnostics/wellness_daily.parquet'
    history=pd.read_parquet(hp) if hp.is_file() else None
    lineage_path=directory/'diagnostics/feature_lineage.parquet'
    lineage_status='not supplied; upstream reports reviewed, no new lineage certification'
    if lineage_path.is_file():
        lineage=pd.read_parquet(lineage_path,columns=['feature','cutoff_date','history_end','latest_event','source_available_at','availability_status'])
        end=pd.to_datetime(lineage.history_end)
        event=pd.to_datetime(lineage.latest_event)
        if (event.notna() & event.dt.normalize().gt(end)).any():raise ValueError('Future lineage contributor')
        wellness_feature=lineage.feature.str.startswith(('fatigue_','stress_','mood_','readiness_'))
        last_allowed=pd.to_datetime(lineage.cutoff_date)-pd.to_timedelta(np.where(wellness_feature,lag,1),unit='D')
        if (event.notna() & event.dt.normalize().gt(last_allowed)).any():raise ValueError('Lineage violates exact conservative lag')
        if ((lineage.availability_status=='verified')&lineage.source_available_at.isna()).any():raise ValueError('Unknown arrival mislabeled verified')
        arrived=lineage[lineage.source_available_at.notna()]
        for r in arrived.itertuples():
            when=pd.Timestamp(r.source_available_at)
            cutoff=pd.Timestamp(r.cutoff_date)+pd.Timedelta(hours=20)
            if when.tzinfo is not None or when>cutoff:raise ValueError('Known late/unresolved input arrival in lineage')
        lineage_status='provided temporal/availability metadata checked; unknown ingestion remains assumed'
    fps=dict(schema_fingerprint=file_hash(config.schema_path),split_fingerprint=fingerprint({n:file_hash(paths[n]) for n in ('split_manifest.csv','grouped_split_manifest.csv')}),
             preprocessing_fingerprint=file_hash(paths['preprocessing_run.json']),dataset_fingerprint=file_hash(paths['fatigue_dataset.parquet']),
             history_fingerprint=file_hash(hp) if history is not None else None)
    support={}
    for partition in ('train','validation'):
        part=frame[frame.split.eq(partition)]
        support[partition]=dict(n=len(part),participants=part.participant_id.nunique(),positive=int(part[LABEL].sum()),negative=int((~part[LABEL].astype(bool)).sum()))
    summary=dict(task='fatigue',scenario_id=scenario,preprocessing_version=metadata['version'],rows=len(frame),
        split_row_counts=frame.groupby('split').size().to_dict(),development_support=support,
        protected_test_outcomes='redacted',mandatory_checks_passed=True,upstream_check_count=len(checks),
        availability='assumed; unresolved device timezone and ingestion',history_available=history is not None,
        lineage_status=lineage_status,
        **fps)
    return DataBundle(frame.sort_values(KEY).reset_index(drop=True),schema,manifest,groups,metadata,fps,history,summary)
