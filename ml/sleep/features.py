"""Authoritative schema selections; optional nulls never remove rows."""
import numpy as np
import pandas as pd
from .config import EXPERIMENTS


def read_schema(path):
    schema=pd.read_csv(path)
    required={'name','group','role','feature_allowlist','unit','dtype'}
    if not required<=set(schema):raise ValueError('Incomplete upstream feature schema')
    if schema.name.duplicated().any():raise ValueError('Duplicate schema columns')
    schema['feature_allowlist']=schema.feature_allowlist.astype(str).str.lower().map({'true':True,'false':False})
    if schema.feature_allowlist.isna().any():raise ValueError('Invalid allowlist booleans')
    return schema


def select_features(schema,experiment_id,calendar=False):
    groups=EXPERIMENTS[experiment_id]+(('Calendar',) if calendar else ())
    chosen=schema[(schema.role=='feature')&schema.feature_allowlist&schema.group.isin(groups)].name.tolist()
    if not chosen or 'sleep_tst_prev' not in chosen:raise ValueError('Core sleep feature absent')
    for name in chosen:
        if name.startswith('target_') or name in ('participant_id','cutoff_date','scenario','split'):
            raise ValueError('Forbidden predictor in schema')
    return chosen


def matrix(frame,columns):
    absent=set(columns)-set(frame)
    if absent:raise ValueError(f'Missing approved features: {sorted(absent)}')
    result=frame[columns].apply(pd.to_numeric,errors='raise').astype('float64')
    if np.isinf(result.to_numpy()).any():raise ValueError('Infinite feature values')
    return result


def validate_masks(frame,schema):
    for name in schema.loc[(schema.role=='feature')&schema.name.str.endswith('_missing'),'name']:
        base=name[:-8]
        if name in frame and base in frame and not frame[name].eq(frame[base].isna().astype(int)).all():
            raise ValueError(f'Inconsistent missingness mask: {name}')
