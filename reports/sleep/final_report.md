# Agent 4 — Final Sleep Prediction Research Report

## Executive summary

Agent 4 developed and evaluated a personalized
next-main-sleep total sleep time regression model.

The selected model is the original tuned CatBoost
with full E5 feature configuration.

The final checkpoint was frozen before the protected
chronological test. Subsequent evaluations did not
change the selected checkpoint.

The optional midpoint task was intentionally skipped.

## Completed workflow

1. Data validation and preprocessing contract review
2. Baseline B0-B3 evaluation
3. Initial model-feature experiments
4. Hyperparameter optimization
5. Personalized residual learning
6. Targeted feature ablation
7. Advanced tuning F5/F6
8. Final model selection and freeze
9. Protected chronological test
10. Participant-independent nested grouped evaluation
11. Preprocessing sensitivity analysis
12. Native CatBoost TreeSHAP
13. CPU-compatible model export

## Model selection

Selected model: CatBoost E5 Tuned.

Validation MAE: 54.6561 minutes.

Selected features: 68.

The residual, ablation and advanced tuning experiments
did not replace the original selected configuration.

## Chronological test results

| Metric | Validation | Test |
|---|---:|---:|
| MAE (min) | 54.6561 | 53.9427 |
| RMSE (min) | 77.3696 | 72.8776 |
| Participant-macro MAE | 55.2311 | 54.0887 |

Test persistence improvement:
28.9628%.

Test personalized median MAE:
55.5828 minutes.

Test improvement versus personalized median:
2.9507%.

Test MAE change relative to validation:
-1.3053%.

Negative improvement means higher error than the baseline.

## Participant-independent nested evaluation

Outer folds: 4.

Inner folds: 3.

Pooled predictions:
1682.

Pooled MAE:
56.5781 minutes.

Pooled RMSE:
77.3048 minutes.

Pooled macro MAE:
56.4650 minutes.

Improvement versus persistence:
24.1416%.

The grouped evaluation assesses the nested learning
procedure, not the same frozen chronological checkpoint.

Secondary inner selection metrics for some tuned
candidates are placeholders; reported outer held-out
participant-macro metrics remain the actual evaluations.

## Preprocessing sensitivity analysis

| Scenario | MAE (min) | RMSE (min) | MAE change |
|---|---:|---:|---:|
| primary | 54.6561 | 77.3696 | 0.0000% |
| offset_plus1 | 55.3898 | 78.0310 | 1.3423% |
| offset_plus2 | 55.5174 | 78.0001 | 1.5758% |
| wellness_lag2 | 56.4779 | 79.4135 | 3.3331% |

The scenarios are validation-only comparisons with
separate training fits and fixed model configuration.

The results do not identify participants' true
timezones or actual ingestion delays.

## SHAP explainability

Method: CatBoost native TreeSHAP.

Partition: validation.

Samples: 329.

Additivity verification: passed.

| Rank | Feature | Mean absolute SHAP (min) |
|---:|---|---:|
| 1 | sleep_tst_baseline_past28d | 8.8189 |
| 2 | sleep_tst_mean_7d | 8.5704 |
| 3 | sleep_tst_mean_3d | 4.0870 |
| 4 | sleep_tst_prev | 3.4363 |
| 5 | sleep_tst_sd_7d | 3.2241 |
| 6 | rhr_baseline_past28d | 2.3150 |
| 7 | stress_prev | 2.2238 |
| 8 | rhr_prev | 2.1604 |
| 9 | steps_prev | 1.8572 |
| 10 | sleep_reference_sin | 1.8407 |

SHAP values measure contribution to model predictions,
not causal effects on sleep or health.

## Release status

- CPU-compatible model artifact: exported
- Midpoint prediction: unavailable
- Individual uncertainty: unavailable
- Runtime local SHAP: unavailable
- Offline global explainability: completed
- Release scope: private research demonstration

## Scientific and operational limitations

The model uses a small terrestrial convenience cohort
with wearable-estimated outcomes and correlated
participant-level observations.

Unknown timezone and data ingestion assumptions remain.

Chronological and internal validation periods were
reused during development.

The final model is not clinically validated and has
not been evaluated on astronaut-domain observations.

Grouped evaluation does not establish new-user
performance of the identical frozen checkpoint.

The small improvement over personalized median
should not be described as statistically significant
without a dedicated paired comparison.

PMData license discrepancy remains unresolved.

## Artifact integrity

Original freeze fingerprint:
bdbe21ed03d1101ad97b862c3ee5bfb7a395fcf59766f2a2bcdb9aab30d14558

Original checkpoint SHA256:
c6ba5340adf983eb281da3e362d9e386c7f4c1e4d9a47c38b53f6689646917ca

Exported model SHA256:
781644a60a592950aa8e70a6163d2bbab7c4f5d8a74d8577492ace97b1460237

See evaluation_summary.json for machine-readable
results and the detailed report subdirectories for
experiment-level evidence.
