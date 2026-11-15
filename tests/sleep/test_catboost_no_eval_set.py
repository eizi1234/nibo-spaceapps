"""Regression test: fixed-iteration CatBoost fits must support no eval_set."""
import numpy as np
import pandas as pd
import pytest
from ml.sleep.models import fit_attempt

def test_catboost_no_eval_set_and_native_shap():
    catboost = pytest.importorskip("catboost")
    X = pd.DataFrame({"sleep_tst_prev": np.arange(32, dtype=float)+380, "rhr_prev": np.arange(32, dtype=float)+60})
    y = X.sleep_tst_prev + 5
    fit, _ = fit_attempt("catboost", X, y, params={"iterations": 5}, device="cpu", threads=1, verbose=False)
    assert fit.best_iteration is None
    assert fit.estimator.tree_count_ == 5
    values = fit.estimator.get_feature_importance(catboost.Pool(X.to_numpy()), type="ShapValues", thread_count=1)
    np.testing.assert_allclose(values.sum(axis=1), fit.predict(X), rtol=1e-6, atol=1e-4)
