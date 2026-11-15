"""Minutes, participant macro metrics and participant-cluster bootstrap."""
import numpy as np
import pandas as pd


def regression_metrics(y,pred,participants,persistence=None):
    y=np.asarray(y,dtype=float);pred=np.asarray(pred,dtype=float);participants=np.asarray(participants)
    if not len(y) or y.shape!=pred.shape or not np.isfinite(y).all() or not np.isfinite(pred).all():raise ValueError('Finite aligned nonempty outcomes required')
    err=pred-y
    participant=pd.DataFrame({'participant_id':participants,'absolute_error':abs(err),'signed_error':err}).groupby('participant_id').agg(mae=('absolute_error','mean'),signed_error=('signed_error','mean'),n=('absolute_error','size'))
    out=dict(mae_minutes=float(np.mean(abs(err))),rmse_minutes=float(np.sqrt(np.mean(err**2))),
        participant_macro_mae_minutes=float(participant.mae.mean()),mean_signed_error_minutes=float(err.mean()),
        n=len(y),participants=len(participant),improvement_vs_persistence_pct=None)
    if persistence is not None:
        base=float(np.mean(abs(np.asarray(persistence)-y)))
        out['persistence_mae_minutes']=base
        out['improvement_vs_persistence_pct']=(base-out['mae_minutes'])/base*100 if base>0 else None
        if base==0:out['improvement_unavailable_reason']='persistence MAE is zero'
    return out,participant.reset_index()


def clustered_bootstrap(y,pred,participants,persistence=None,replicates=1000,seed=42):
    y,pred,participants=np.asarray(y),np.asarray(pred),np.asarray(participants)
    ids=np.unique(participants);rng=np.random.default_rng(seed);values=[]
    if len(ids)<2:return dict(intervals=None,reason='fewer than two participants',invalid_replicates=replicates)
    for _ in range(replicates):
        sampled=rng.choice(ids,size=len(ids),replace=True)
        positions=np.concatenate([np.flatnonzero(participants==pid) for pid in sampled])
        # Distinguish duplicated sampled clusters for macro aggregation.
        labels=np.concatenate([np.full(np.sum(participants==pid),i) for i,pid in enumerate(sampled)])
        m,_=regression_metrics(y[positions],pred[positions],labels,np.asarray(persistence)[positions] if persistence is not None else None)
        values.append(m)
    metrics=('mae_minutes','rmse_minutes','participant_macro_mae_minutes','improvement_vs_persistence_pct')
    intervals={}
    for metric in metrics:
        finite=[v[metric] for v in values if v.get(metric) is not None and np.isfinite(v[metric])]
        intervals[metric]=dict(lower=float(np.quantile(finite,.025)),upper=float(np.quantile(finite,.975)),valid_replicates=len(finite)) if finite else None
    return dict(intervals=intervals,replicates=replicates,seed=seed,invalid_replicates=0,warning='Participant bootstrap; small subject count limits interval stability')
