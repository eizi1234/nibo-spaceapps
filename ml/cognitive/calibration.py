"""Forward/group OOF training calibration, separate validation adequacy/threshold sets."""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from .models import fit_model
from .evaluation import metrics,choose_threshold


@dataclass
class CalibrationState:
    method: str = 'native'
    slope: float | None = None
    intercept: float | None = None
    probability_verified: bool = False
    threshold: float = .5
    evidence: dict | None = None

    def apply(self,scores):
        scores=np.asarray(scores,dtype=float)
        if self.method=='sigmoid':
            z=np.clip(self.slope*scores+self.intercept,-700,700)
            return 1/(1+np.exp(-z))
        return scores


def calibration_partitions(validation):
    dates=sorted(validation.cutoff_date.unique())
    if len(dates)<2:return validation.iloc[:0],validation
    boundary=dates[len(dates)//2]
    return validation[validation.cutoff_date<boundary],validation[validation.cutoff_date>=boundary]


def oof_training_scores(train,name,features,params,config,logger=None,grouped=False):
    out=pd.Series(np.nan,index=train.index,dtype=float)
    splits=[]
    if grouped:
        n=min(config.outer_inner_folds,train.participant_id.nunique())
        if n<2:return out
        splits=[(train.iloc[a],train.iloc[b]) for a,b in GroupKFold(n_splits=n).split(train,groups=train.participant_id)]
    else:
        dates=np.array(sorted(train.cutoff_date.unique()),dtype=object)
        blocks=np.array_split(dates,4)
        for i in range(1,4):
            if not len(blocks[i]):continue
            first=blocks[i][0]
            a=train[(train.cutoff_date<first)&(pd.to_datetime(train.target_fatigue_date).dt.date<first)]
            b=train[train.cutoff_date.isin(blocks[i])]
            splits.append((a,b))
    for fold,(a,b) in enumerate(splits):
        if a.target_elevated_fatigue.nunique()<2 or b.empty:continue
        model=fit_model(name,features,a,None,config,logger,f'CAL-OOF-{fold}',params=params)
        out.loc[b.index]=model.scores(b)
    return out


def calibrate_and_threshold(model,train,validation,config,logger=None,adequacy_approved=False,grouped=False):
    state=CalibrationState(evidence={})
    adequacy,threshold_rows=calibration_partitions(validation)
    candidate=None
    oof=oof_training_scores(train,model.model_name,model.features,model.params,config,logger,grouped)
    good=oof.notna();ys=train.loc[good,'target_elevated_fatigue'].astype(int)
    enough=good.sum()>=config.calibration_min_samples and ys.value_counts().reindex([0,1],fill_value=0).min()>=config.calibration_min_class
    if enough:
        fitter=LogisticRegression(C=1.,random_state=config.seed)
        fitter.fit(oof.loc[good].to_numpy().reshape(-1,1),ys)
        candidate=CalibrationState('sigmoid',float(fitter.coef_[0,0]),float(fitter.intercept_[0]))
    state.evidence={'calibration_fit':'training-only forward OOF' if not grouped else 'outer-training-only inner group OOF','oof_n':int(good.sum()),'adequacy_n':len(adequacy),'threshold_n':len(threshold_rows),'partition_overlap':len(set(adequacy.index)&set(threshold_rows.index)),'model_selection_used_full_validation':True,'limitation':'Adequacy and threshold are development estimates after validation model selection; not independent final evidence'}
    support=adequacy.target_elevated_fatigue.value_counts().reindex([0,1],fill_value=0) if len(adequacy) else pd.Series([0,0])
    if len(adequacy)>=config.calibration_min_samples and support.min()>=config.calibration_min_class:
        native=model.scores(adequacy)
        native_metrics=metrics(adequacy.target_elevated_fatigue,native)
        chosen_metrics=native_metrics
        if candidate:
            adjusted=metrics(adequacy.target_elevated_fatigue,candidate.apply(native))
            if adjusted['brier']<native_metrics['brier']:state.method='sigmoid';state.slope=candidate.slope;state.intercept=candidate.intercept;chosen_metrics=adjusted
            state.evidence['sigmoid_metrics']=adjusted
        state.evidence['native_metrics']=native_metrics
        state.probability_verified=bool(adequacy_approved and chosen_metrics['ece']<=config.calibration_max_ece)
    state.evidence['probability_verified']=state.probability_verified
    state.evidence['adequacy_criteria_human_approved']=adequacy_approved
    if len(threshold_rows):
        state.threshold,details=choose_threshold(threshold_rows.target_elevated_fatigue,state.apply(model.scores(threshold_rows)))
        state.evidence['threshold_selection']=details
    else:state.evidence['threshold_selection']={'status':'fallback','reason':'No independent threshold rows'}
    return state
