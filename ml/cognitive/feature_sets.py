"""Use exact upstream schema membership, including derivative masks/ages/counts."""
import numpy as np
import pandas as pd
from .config import EXPERIMENTS

BASE = {
 'A': {'sleep_tst_prev','sleep_score_prev','sleep_midpoint_sin_prev','sleep_midpoint_cos_prev','sleep_tst_mean_3d','sleep_tst_mean_7d','sleep_tst_sd_7d','sleep_observed_n_3d','sleep_observed_n_7d','sleep_age_days'},
 'B': {'fatigue_prev','stress_prev','mood_prev','readiness_prev','fatigue_age_days','stress_age_days','mood_age_days','readiness_age_days'},
 'C': {'rhr_prev','rhr_baseline_past28d','rhr_delta_past28d','rhr_observed_n_28d','rhr_age_days'},
 'D': {'steps_prev','active_minutes_prev','activity_coverage_prev','exercise_load_prev','steps_age_days','active_minutes_age_days'},
 'E': {'sleep_tst_baseline_past28d','sleep_tst_delta_past28d','sleep_tst_observed_n_28d','sleep_reference_sin','sleep_reference_cos','sleep_reference_concentration','sleep_reference_observed_n_28d','fatigue_baseline_past28d','fatigue_observed_n_28d'},
 'Calendar': {'weekday_sin','weekday_cos'},
}


def read_schema(path):
    schema=pd.read_csv(path)
    required={'name','role','group','feature_allowlist','unit','dtype'}
    if not required.issubset(schema):raise ValueError('Schema fields absent')
    if schema.name.duplicated().any():raise ValueError('Duplicate schema names')
    flag=schema.feature_allowlist.astype(str).str.lower().map({'true':True,'false':False})
    if flag.isna().any():raise ValueError('Ambiguous feature allowlist flag')
    schema['feature_allowlist']=flag
    for r in schema[schema.feature_allowlist].itertuples():
        base=r.name[:-8] if r.name.endswith('_missing') else r.name
        if r.role!='feature' or base not in BASE.get(r.group,set()):
            raise ValueError(f'Unapproved predictor or group: {r.name}')
    if not {'sleep_tst_prev','fatigue_prev'}.issubset(set(schema.name)):
        raise ValueError('Frozen required schema absent')
    return schema


def columns_for(schema,experiment='E5',calendar=False):
    if experiment in EXPERIMENTS:groups=EXPERIMENTS[experiment]
    elif experiment in ('SUP_NO_FATIGUE','SUP_WEARABLE_ONLY'):groups=EXPERIMENTS['E5']
    else:raise ValueError(f'Unknown experiment: {experiment}')
    cols=schema[schema.feature_allowlist & schema.role.eq('feature') & schema.group.isin(groups)].name.tolist()
    if experiment=='SUP_NO_FATIGUE':cols=[c for c in cols if not c.startswith('fatigue_')]
    if experiment=='SUP_WEARABLE_ONLY':
        wellness=set(schema[schema.group.eq('B')].name)
        cols=[c for c in cols if c not in wellness and not c.startswith(('fatigue_','exercise_load_'))]
    if calendar:cols+=schema[schema.feature_allowlist & schema.group.eq('Calendar')].name.tolist()
    if 'sleep_tst_prev' not in cols:raise ValueError('Mandatory core sleep absent')
    return cols


def validate_masks(frame,schema):
    for name in schema[schema.feature_allowlist].name:
        if name not in frame:raise ValueError(f'Missing approved feature: {name}')
        if name.endswith('_missing'):
            base=name[:-8]
            values=pd.to_numeric(frame[name],errors='coerce')
            if not values.isin([0,1]).all() or not values.eq(frame[base].isna().astype(int)).all():
                raise ValueError(f'Invalid missing mask: {name}')
        values=pd.to_numeric(frame[name],errors='coerce')
        if (frame[name].notna() & values.isna()).any() or np.isinf(values.to_numpy(dtype=float,na_value=np.nan)).any():
            raise ValueError(f'Non-numeric/nonfinite feature: {name}')


def simulate_missing_modality(frame,schema,groups):
    if 'A' in groups:raise ValueError('Core sleep cannot be simulated away')
    result=frame.copy()
    for r in schema[schema.feature_allowlist & schema.group.isin(groups)].itertuples():
        if r.name.endswith('_missing'):continue
        if '_observed_n_' in r.name:result[r.name]=0
        else:result[r.name]=np.nan
        mask=r.name+'_missing'
        if mask in result:result[mask]=result[r.name].isna().astype(int)
    return result
