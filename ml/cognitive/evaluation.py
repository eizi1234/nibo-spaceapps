"""AP convention is sklearn.average_precision_score, not trapezoidal PR integral."""
import numpy as np
from sklearn.metrics import (average_precision_score,balanced_accuracy_score,f1_score,roc_auc_score,brier_score_loss,confusion_matrix,log_loss)
from sklearn.calibration import calibration_curve


def metrics(y,scores,threshold=.5,probability_valued=True,participants=None):
    y=np.asarray(y,dtype=int);scores=np.asarray(scores,dtype=float)
    if not len(y) or len(y)!=len(scores) or not np.isin(y,[0,1]).all() or not np.isfinite(scores).all():raise ValueError('Invalid scoring inputs')
    if probability_valued and not ((scores>=0)&(scores<=1)).all():raise ValueError('Probability-valued scores outside [0,1]')
    pred=scores>=threshold
    tn,fp,fn,tp=confusion_matrix(y,pred,labels=[0,1]).ravel()
    two=len(np.unique(y))==2
    result=dict(n=len(y),positive=int(y.sum()),negative=int((y==0).sum()),
        average_precision=float(average_precision_score(y,scores)) if two else None,
        average_precision_reason=None if two else 'one-class sample; ranking discrimination unavailable',
        balanced_accuracy=float(balanced_accuracy_score(y,pred)) if two else None,
        macro_f1=float(f1_score(y,pred,labels=[0,1],average='macro',zero_division=0)),
        recall=float(tp/(tp+fn)) if tp+fn else None,specificity=float(tn/(tn+fp)) if tn+fp else None,
        roc_auc=float(roc_auc_score(y,scores)) if two else None,roc_auc_reason=None if two else 'one-class sample',
        brier=float(brier_score_loss(y,scores)) if probability_valued else None,
        log_loss=float(log_loss(y,scores,labels=[0,1])) if probability_valued else None,
        confusion_matrix=[[int(tn),int(fp)],[int(fn),int(tp)]],decision_threshold=float(threshold))
    if probability_valued:
        observed,predicted=calibration_curve(y,scores,n_bins=5,strategy='uniform')
        result['calibration_curve']={'mean_score':predicted.tolist(),'observed_frequency':observed.tolist()}
        bins=np.minimum((scores*5).astype(int),4)
        result['ece']=float(sum(np.mean(bins==b)*abs(scores[bins==b].mean()-y[bins==b].mean()) for b in np.unique(bins)))
    if participants is not None:
        ids=np.asarray(participants)
        per={str(pid):metrics(y[ids==pid],scores[ids==pid],threshold,probability_valued) for pid in np.unique(ids)}
        keys=('average_precision','balanced_accuracy','macro_f1','recall','specificity','roc_auc','brier')
        result['participants']=len(per)
        result['participant_macro']={key:float(np.mean([r[key] for r in per.values() if r[key] is not None])) if any(r[key] is not None for r in per.values()) else None for key in keys}
        result['participant_defined_counts']={key:sum(r[key] is not None for r in per.values()) for key in keys}
        result['participant_metrics']=per
    return result


def choose_threshold(y,scores):
    y=np.asarray(y,dtype=int);scores=np.asarray(scores,dtype=float)
    if len(np.unique(y))<2:return .5,{'status':'fallback','reason':'one-class threshold partition'}
    grid=np.unique(np.r_[np.linspace(0,1,101),.5])
    values=[(float(f1_score(y,scores>=t,average='macro',labels=[0,1],zero_division=0)),-abs(t-.5),-t,t) for t in grid]
    best=max(values)
    return float(best[3]),dict(status='selected',criterion='validation-only macro F1',tie_break='closest to 0.5, then smaller threshold')


def cluster_bootstrap(y,scores,participants,threshold=.5,replicates=1000,seed=42,baseline=None):
    y=np.asarray(y);scores=np.asarray(scores);ids=np.asarray(participants);people=np.unique(ids)
    rng=np.random.default_rng(seed);values=[];improvements=[];invalid=0
    for _ in range(replicates):
        sampled=rng.choice(people,len(people),replace=True)
        indexes=np.concatenate([np.flatnonzero(ids==pid) for pid in sampled])
        if len(np.unique(y[indexes]))<2:invalid+=1;continue
        ap=float(average_precision_score(y[indexes],scores[indexes]));values.append(ap)
        if baseline is not None:improvements.append(ap-float(average_precision_score(y[indexes],np.asarray(baseline)[indexes])))
    def interval(vals):return np.quantile(vals,[.025,.975]).tolist() if vals else None
    return dict(metric='average_precision',interval_95=interval(values),paired_AP_improvement_interval_95=interval(improvements),replicates=replicates,invalid_replicates=invalid,seed=seed,clusters=len(people),warning='Participants resampled with all rows; small independent subject count limits interval reliability')
