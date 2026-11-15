"""Calendar baselines using Agent 2 shared history, never supervised target rows."""
import numpy as np
import pandas as pd


def sleep_history(shared):
    required={'participant_id','cutoff_date','sleep_tst_prev','core_eligible'}
    if not required<=set(shared):raise ValueError('B2 blocked: full Agent 2 shared history unavailable')
    history=shared.loc[shared.core_eligible.fillna(False),['participant_id','cutoff_date','sleep_tst_prev']].copy()
    history['event_date']=pd.to_datetime(history.cutoff_date)-pd.Timedelta(days=1)
    if history.duplicated(['participant_id','event_date']).any():raise ValueError('Nonunique daily history')
    return history


def baseline_predictions(train,evaluation,shared):
    from .config import TARGET
    median=float(np.median(train[TARGET].to_numpy(dtype=float)))
    persistence=evaluation.sleep_tst_prev.to_numpy(dtype=float)
    if not np.isfinite(persistence).all():raise ValueError('Core sleep absent; eligible rows must not be fabricated')
    history=sleep_history(shared)
    rolling=[];observed=[]
    for r in evaluation.itertuples():
        t=pd.Timestamp(r.cutoff_date)
        h=history[(history.participant_id==r.participant_id)&history.event_date.between(t-pd.Timedelta(days=7),t-pd.Timedelta(days=1))].sleep_tst_prev.dropna()
        observed.append(len(h));rolling.append(float(h.median()) if len(h)>=4 else np.nan)
    rolling=np.array(rolling);personal=evaluation.sleep_tst_baseline_past28d.to_numpy(dtype=float)
    return {'B0':dict(predictions=np.full(len(evaluation),median),available_n=len(evaluation),fallback_n=0),
        'B1':dict(predictions=persistence,available_n=len(evaluation),fallback_n=0),
        'B2':dict(predictions=np.where(np.isfinite(rolling),rolling,persistence),available_n=int(np.isfinite(rolling).sum()),fallback_n=int((~np.isfinite(rolling)).sum()),observed_n=observed),
        'B3':dict(predictions=np.where(np.isfinite(personal),personal,persistence),available_n=int(np.isfinite(personal).sum()),fallback_n=int((~np.isfinite(personal)).sum()))}
