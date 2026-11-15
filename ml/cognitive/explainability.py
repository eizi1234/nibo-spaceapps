"""Validation or explicitly unlocked evaluation only; associations are not causes."""
import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance


def permutation_ap(model,frame,seed=42,repeats=5):
    from sklearn.base import BaseEstimator,ClassifierMixin
    class Wrapper(ClassifierMixin,BaseEstimator):
        def __init__(self):self.classes_=np.array([0,1]);self.fitted_=True
        def fit(self,X,y):return self
        def predict_proba(self,X):
            s=model.scores(pd.DataFrame(X,columns=model.features))
            return np.c_[1-s,s]
    importance=permutation_importance(Wrapper(),frame[model.features],frame.target_elevated_fatigue.astype(int),scoring='average_precision',random_state=seed,n_repeats=repeats,n_jobs=1)
    return pd.DataFrame(dict(feature=model.features,AP_decrease_mean=importance.importances_mean,AP_decrease_sd=importance.importances_std)).sort_values('AP_decrease_mean',ascending=False)
