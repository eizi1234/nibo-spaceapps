"""Past-only source-history baselines; never reconstruct history from target rows."""
import datetime as dt
import numpy as np
import pandas as pd


def baseline_scores(train,evaluation,history=None,history_days=28,min_days=14,wellness_lag=1):
    prevalence=float(train.target_elevated_fatigue.astype(int).mean())
    if not np.isfinite(prevalence):raise ValueError('Training prevalence unavailable')
    n=len(evaluation)
    scores={'B0_PREVALENCE':np.full(n,prevalence),'B0_MAJORITY':np.full(n,prevalence)}
    previous=pd.to_numeric(evaluation.fatigue_prev,errors='coerce')
    valid=previous.between(1,5)
    scores['B1_PERSISTENCE']=np.where(valid,previous.le(2).astype(float),prevalence)
    coverage=[dict(baseline='B0_PREVALENCE',coverage_n=n,fallback_n=0,score_semantics='training prevalence; not validated individual probability'),
              dict(baseline='B0_MAJORITY',coverage_n=n,fallback_n=0,score_semantics='prevalence ranking score; class is prevalence>=0.5, ties positive'),
              dict(baseline='B1_PERSISTENCE',coverage_n=int(valid.sum()),fallback_n=int((~valid).sum()),freshness=f'exact t-{wellness_lag}',score_semantics='binary historical persistence score with training-prevalence fallback')]
    if history is None:
        coverage.append(dict(baseline='B2_PERSONAL_PREVALENCE',status='blocked',reason='Approved daily fatigue history unavailable; target rows are not substituted'))
        return scores,coverage
    h=history.copy()
    if 'variable' in h:h=h[h.variable.eq('fatigue')]
    needed={'participant_id','date','value','effective_time','source_available_at'}
    if not needed.issubset(h):raise ValueError('Daily history provenance missing')
    h['date']=pd.to_datetime(h.date).dt.date
    if h.duplicated(['participant_id','date']).any() or not pd.to_numeric(h.value).isin([1,2,3,4,5]).all():raise ValueError('Invalid approved history')
    personal=[];observed=0
    for r in evaluation.itertuples():
        last=r.cutoff_date-dt.timedelta(days=wellness_lag);first=last-dt.timedelta(days=history_days-1)
        daily=h[h.participant_id.eq(r.participant_id)&h.date.between(first,last)].copy()
        cutoff=pd.Timestamp(r.cutoff_wallclock)
        allowed=[]
        for z in daily.itertuples():
            event=pd.Timestamp(z.effective_time)
            arrival=z.source_available_at
            okay=event.tzinfo is None and event.date()<=last
            if pd.notna(arrival):
                arrival=pd.Timestamp(arrival);okay=okay and arrival.tzinfo is None and arrival<=cutoff
            allowed.append(okay)
        daily=daily.loc[allowed]
        if len(daily)>=min_days:personal.append(float(daily.value.le(2).mean()));observed+=1
        else:personal.append(prevalence)
    scores['B2_PERSONAL_PREVALENCE']=np.asarray(personal)
    coverage.append(dict(baseline='B2_PERSONAL_PREVALENCE',coverage_n=observed,fallback_n=n-observed,history_days=history_days,min_days=min_days,score_semantics='past-only personal prevalence; unknown ingestion remains assumed'))
    return scores,coverage
