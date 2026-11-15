"""Fold-local deterministic median imputation; all-empty columns remain present."""
import numpy as np
from sklearn.base import BaseEstimator,TransformerMixin
from sklearn.preprocessing import StandardScaler


class StableMedianImputer(BaseEstimator,TransformerMixin):
    def fit(self,X,y=None):
        a=np.asarray(X,dtype=float)
        if a.ndim!=2 or np.isinf(a).any():raise ValueError('Expected finite-or-null numeric matrix')
        self.n_features_in_=a.shape[1]
        self.statistics_=np.array([np.median(c[np.isfinite(c)]) if np.isfinite(c).any() else 0. for c in a.T])
        self.empty_training_columns_=np.array([not np.isfinite(c).any() for c in a.T])
        return self
    def transform(self,X):
        a=np.asarray(X,dtype=float).copy()
        if a.shape[1]!=self.n_features_in_:raise ValueError('Feature dimension changed')
        if np.isinf(a).any():raise ValueError('Infinite feature')
        missing=np.isnan(a);a[missing]=np.broadcast_to(self.statistics_,a.shape)[missing]
        return a


def transformer(scale):
    from sklearn.pipeline import Pipeline
    return Pipeline([('imputer',StableMedianImputer())]+([('scaler',StandardScaler())] if scale else []))
