"""Fold-fitted numeric transforms with an explicit all-null training-column policy."""
import numpy as np
from sklearn.base import BaseEstimator,TransformerMixin


def numeric_matrix(values):
    if hasattr(values,'to_numpy'):result=values.to_numpy(dtype=float,na_value=np.nan)
    else:result=np.asarray(values,dtype=float)
    if result.ndim!=2 or np.isinf(result).any():raise ValueError('Expected finite-or-NaN numeric matrix')
    return result


class MedianImputer(BaseEstimator,TransformerMixin):
    """Preserve every column; an entirely absent training column uses constant 0.

    This is a deterministic software fallback, never a mean learned from validation.
    Approved missingness masks remain separate model inputs.
    """
    def fit(self,X,y=None):
        a=numeric_matrix(X)
        self.n_features_in_=a.shape[1]
        self.all_null_columns_=np.isnan(a).all(axis=0)
        self.statistics_=np.array([np.median(c[~np.isnan(c)]) if (~np.isnan(c)).any() else 0.0 for c in a.T])
        return self

    def transform(self,X):
        a=numeric_matrix(X)
        if a.shape[1]!=self.n_features_in_:raise ValueError('Feature dimension changed')
        return np.where(np.isnan(a),self.statistics_,a)


class NumericCaster(BaseEstimator,TransformerMixin):
    def fit(self,X,y=None):self.n_features_in_=numeric_matrix(X).shape[1];return self
    def transform(self,X):
        a=numeric_matrix(X)
        if a.shape[1]!=self.n_features_in_:raise ValueError('Feature dimension changed')
        return a
