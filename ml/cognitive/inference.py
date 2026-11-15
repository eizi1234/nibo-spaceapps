"""Independent CPU inference for Agents 5/6; no raw-data or server dependency."""
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
import datetime as dt


def predict_fatigue(features,artifact=None):
    frame=pd.DataFrame([features]) if isinstance(features,dict) else features.copy()
    if len(frame)!=1:raise ValueError('Inference helper expects one participant/cutoff row')
    r=frame.iloc[0]
    result=dict(status='unavailable',fatigue_risk_probability=None,fatigue_risk_score=None,predicted_elevated_fatigue=None,decision_threshold=None,prediction_horizon='next_day',cutoff_wallclock=str(r.get('cutoff_wallclock')) if pd.notna(r.get('cutoff_wallclock')) else None,cutoff_datetime_utc=None,model_version=None,input_coverage={},explanation_available=False,explanations=None,uncertainty=None)
    core=pd.to_numeric(pd.Series([r.get('sleep_tst_prev')]),errors='coerce').iloc[0]
    explicit_core=r.get('core_eligible',True)
    stale=False
    if pd.notna(r.get('sleep_prev_end')) and pd.notna(r.get('cutoff_date')):
        stale=pd.Timestamp(r.sleep_prev_end).date()!=pd.Timestamp(r.cutoff_date).date()-dt.timedelta(days=1)
    if pd.isna(core) or not 1<=core<=1440 or (pd.notna(explicit_core) and not bool(explicit_core)) or stale:
        result['status']='insufficient_data';return result
    if artifact is None:return result
    # Load only a trusted private artifact; joblib/pickle is not a safe untrusted format.
    try:state=joblib.load(Path(artifact)/'model.joblib') if not isinstance(artifact,dict) else artifact
    except Exception:return result
    if not isinstance(state,dict) or not {'model','calibration','metadata'}.issubset(state):return result
    model,calibration,metadata=state['model'],state['calibration'],state['metadata']
    for column in model.features:
        if column not in frame:raise ValueError(f'Missing approved input column: {column}')
        numeric=pd.to_numeric(frame[column],errors='coerce')
        if (frame[column].notna()&numeric.isna()).any() or np.isinf(numeric.to_numpy(dtype=float,na_value=np.nan)).any():raise ValueError(f'Invalid numeric input: {column}')
        if column.endswith('_missing') and column[:-8] in frame:
            if not numeric.eq(frame[column[:-8]].isna().astype(int)).all():raise ValueError('Input missing mask inconsistent')
    try:
        model.cpu()
        scores=calibration.apply(model.scores(frame))
    except Exception:return result
    if not np.isfinite(scores).all() or not ((scores>=0)&(scores<=1)).all():return result
    score=float(scores[0]);result.update(status='ok',model_version=metadata.get('model_version'),fatigue_risk_score=score,predicted_elevated_fatigue=bool(score>=calibration.threshold),decision_threshold=calibration.threshold,input_coverage={c:bool(pd.notna(r[c])) for c in model.features if not c.endswith('_missing')})
    if calibration.probability_verified:result['fatigue_risk_probability']=score
    return result
