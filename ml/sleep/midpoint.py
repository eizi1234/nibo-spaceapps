"""Optional interval timing. Magnitude is not a confidence measure."""
import numpy as np


def decode_midpoint(sin,cos,tolerance=1e-8):
    s,c=np.asarray(sin,dtype=float),np.asarray(cos,dtype=float)
    norm=np.hypot(s,c);valid=np.isfinite(s)&np.isfinite(c)&(norm>tolerance)
    minutes=np.where(valid,np.mod(np.arctan2(s,c),2*np.pi)*1440/(2*np.pi),np.nan)
    return minutes,valid


def circular_error(pred,true):
    a,b=np.asarray(pred,dtype=float),np.asarray(true,dtype=float)
    return np.abs((a-b+720)%1440-720)


def midpoint_metrics(sin,cos,true_sin,true_cos,participants):
    from .evaluation import regression_metrics
    pred,valid=decode_midpoint(sin,cos);true,tvalid=decode_midpoint(true_sin,true_cos)
    valid &= tvalid
    if not valid.any():return dict(circular_mae_minutes=None,available_n=0,unavailable_n=len(pred))
    errors=circular_error(pred[valid],true[valid]);ids=np.asarray(participants)[valid]
    macro=np.mean([errors[ids==pid].mean() for pid in np.unique(ids)])
    return dict(circular_mae_minutes=float(errors.mean()),participant_macro_circular_mae_minutes=float(macro),available_n=int(valid.sum()),unavailable_n=int((~valid).sum()))
